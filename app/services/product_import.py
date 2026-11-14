"""Importação de produtos por planilha (Excel .xlsx ou .csv), uma linha por tamanho/cor.

Linhas com o mesmo Nome viram um produto só. Produto que já existe (mesmo nome) é pulado,
então dá para corrigir a planilha e importar de novo sem duplicar nada.
"""
import csv
import re
import unicodedata
import zipfile
from io import BytesIO, StringIO
from xml.etree import ElementTree

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Category, Product, ProductVariant
from app.schemas.catalog import ProductIn
from app.services.slug import unique_slug

MAX_ROWS = 3000
MAX_UNZIPPED = 30 * 1024 * 1024  # planilha de produtos real tem poucos KB; acima disso é arquivo-bomba
NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"

# cabeçalho da planilha (sem acento, minúsculo) -> campo
COLUMNS = {
    "nome": "name", "produto": "name",
    "preco": "price", "valor": "price",
    "preco de": "compare_at_price", "preco de (opcional)": "compare_at_price", "preco antigo": "compare_at_price",
    "categoria": "category",
    "descricao": "description",
    "cor": "color",
    "tamanho": "size",
    "estoque": "stock", "quantidade": "stock", "qtd": "stock",
}

TEMPLATE = (
    "Nome;Preço;Preço de (opcional);Categoria;Cor;Tamanho;Estoque;Descrição\r\n"
    "Camiseta Básica;49,90;;Camisetas;Preto;P;5;Algodão 100%, gola careca\r\n"
    "Camiseta Básica;49,90;;Camisetas;Preto;M;8;\r\n"
    "Camiseta Básica;49,90;;Camisetas;Branco;M;4;\r\n"
    "Bermuda Sarja;89,90;119,90;Bermudas;Bege;40;3;\r\n"
)


class SheetError(ValueError):
    """Planilha que não dá para ler (mensagem pronta para o lojista)."""


def _plain(text: str) -> str:
    text = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", text).strip().lower()


def _col_index(ref: str) -> int:
    n = 0
    for ch in re.match(r"[A-Z]+", ref).group():
        n = n * 26 + ord(ch) - 64
    return n - 1


def _xml(data: bytes):
    if b"<!DOCTYPE" in data[:2048]:  # planilha de verdade não tem DTD; evita truques de entidade
        raise SheetError("Arquivo inválido.")
    return ElementTree.fromstring(data)


def _read_xlsx(content: bytes) -> list[list[str]]:
    try:
        zf = zipfile.ZipFile(BytesIO(content))
    except zipfile.BadZipFile as exc:
        raise SheetError("Não consegui abrir o arquivo. Salve no Excel como .xlsx ou .csv e tente de novo.") from exc
    if sum(i.file_size for i in zf.infolist()) > MAX_UNZIPPED:
        raise SheetError("Planilha grande demais.")
    names = zf.namelist()
    shared = []
    if "xl/sharedStrings.xml" in names:
        for si in _xml(zf.read("xl/sharedStrings.xml")).iter(f"{NS}si"):
            shared.append("".join(t.text or "" for t in si.iter(f"{NS}t")))
    # shortcut: lê sempre a primeira aba; se o lojista usar várias abas, trocar por workbook.xml + rels
    sheets = sorted(n for n in names if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n))
    if not sheets:
        raise SheetError("A planilha está vazia.")
    first = "xl/worksheets/sheet1.xml" if "xl/worksheets/sheet1.xml" in sheets else sheets[0]
    rows = []
    for row in _xml(zf.read(first)).iter(f"{NS}row"):
        cells: dict[int, str] = {}
        for c in row.iter(f"{NS}c"):
            kind, v = c.get("t"), c.find(f"{NS}v")
            if kind == "inlineStr":
                value = "".join(t.text or "" for t in c.iter(f"{NS}t"))
            elif v is None:
                continue
            elif kind == "s":
                value = shared[int(v.text)]
            else:
                value = v.text or ""
            cells[_col_index(c.get("r", "A"))] = value
        if cells:
            rows.append([cells.get(i, "") for i in range(max(cells) + 1)])
    return rows


def _read_csv(content: bytes) -> list[list[str]]:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode("cp1252")  # CSV salvo pelo Excel em português
    first = text.split("\n", 1)[0]
    return list(csv.reader(StringIO(text), delimiter=";" if first.count(";") >= first.count(",") else ","))


def read_sheet(content: bytes) -> list[dict]:
    """Linhas da planilha como dicts {campo: texto}, com o número da linha em "_row"."""
    rows = _read_xlsx(content) if content[:2] == b"PK" else _read_csv(content)
    if not rows:
        raise SheetError("A planilha está vazia.")
    header = [COLUMNS.get(_plain(h)) for h in rows[0]]
    if "name" not in header or "price" not in header:
        raise SheetError('A primeira linha precisa ter as colunas "Nome" e "Preço". Baixe o modelo para ver como fica.')
    out = []
    for number, row in enumerate(rows[1:], start=2):
        item = {field: str(value).strip() for field, value in zip(header, row) if field}
        if any(item.values()):
            item["_row"] = number
            out.append(item)
    if len(out) > MAX_ROWS:
        raise SheetError(f"São {len(out)} linhas. Importe no máximo {MAX_ROWS} por vez.")
    return out


def parse_money(text: str) -> float | None:
    """Aceita 49,90 · 49.90 · R$ 1.234,56 · 49 (o Excel às vezes manda 49.9)."""
    text = re.sub(r"[^\d,.\-]", "", text or "")
    if not text:
        return None
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    try:
        return round(float(text), 2)
    except ValueError:
        return None


def _parse_stock(text: str) -> int | None:
    value = parse_money(text) if text else 0
    return int(value) if value is not None and value >= 0 and value == int(value) else None


def import_products(db: Session, rows: list[dict]) -> dict:
    """Cria os produtos da planilha. Produtos com erro ficam de fora e voltam na lista de erros."""
    groups: dict[str, list[dict]] = {}
    errors: list[str] = []
    for row in rows:
        if not row.get("name"):
            errors.append(f"Linha {row['_row']}: falta o nome do produto.")
            continue
        groups.setdefault(_plain(row["name"]), []).append(row)

    existing = {_plain(n) for n in db.scalars(select(Product.name))}
    categories = {_plain(c.name): c for c in db.scalars(select(Category))}
    created, skipped = [], []

    for key, group in groups.items():
        name, lines = group[0]["name"], ", ".join(str(r["_row"]) for r in group)
        if key in existing:
            skipped.append(name)
            continue
        price = next((parse_money(r["price"]) for r in group if r.get("price")), None)
        if not price or price <= 0:
            errors.append(f"{name} (linha {lines}): preço vazio ou inválido.")
            continue
        compare = next((parse_money(r["compare_at_price"]) for r in group if r.get("compare_at_price")), None)

        variants: dict[tuple, dict] = {}
        bad_stock = [r["_row"] for r in group if _parse_stock(r.get("stock", "")) is None]
        if bad_stock:
            errors.append(f"{name} (linha {', '.join(map(str, bad_stock))}): estoque precisa ser um número inteiro.")
            continue
        for r in group:
            size = r.get("size") or ("U" if r.get("color") or r.get("stock") else "")
            if size:
                color = r.get("color") or None
                variants[(_plain(color or ""), size.upper())] = {
                    "size": size.upper(), "color": color, "stock": _parse_stock(r.get("stock", ""))}

        category = None
        cat_name = next((r["category"] for r in group if r.get("category")), "")
        if cat_name:
            category = categories.get(_plain(cat_name))
            if category is None:
                category = Category(name=cat_name[:80], slug=unique_slug(db, Category, cat_name))
                db.add(category)
                db.flush()
                categories[_plain(cat_name)] = category
        try:
            data = ProductIn(
                name=name, price=price, description=next((r["description"] for r in group if r.get("description")), ""),
                compare_at_price=compare if compare and compare > price else None,
                category_id=category.id if category else None,
                # escondido até ganhar fotos: produto sem foto na vitrine afasta o cliente
                active=False, is_new=True, variants=list(variants.values()),
            )
        except ValidationError as exc:
            problem = exc.errors()[0]
            errors.append(f"{name} (linha {lines}): {problem['loc'][0] if problem['loc'] else ''} {problem['msg']}.")
            continue
        db.add(Product(
            **data.model_dump(exclude={"variants"}),
            slug=unique_slug(db, Product, data.name),
            variants=[ProductVariant(**v.model_dump(exclude={"id", "stock_before"})) for v in data.variants],
        ))
        db.flush()  # o próximo unique_slug já enxerga este
        existing.add(key)
        created.append(name)

    db.commit()
    return {"created": created, "skipped": skipped, "errors": errors}
