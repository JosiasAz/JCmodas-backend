"""Importação de produtos por planilha.

Roda sem pytest:  python -m tests.test_product_import   (de dentro da pasta backend)
Usa SQLite em memória: não toca no Neon.
"""
import zipfile
from io import BytesIO

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models import Category, Product
from app.services.product_import import TEMPLATE, SheetError, import_products, parse_money, read_sheet


def _xlsx(rows: list[list[str]]) -> bytes:
    """Planilha mínima como o Excel grava (textos em sharedStrings, números direto na célula)."""
    strings, cells_xml = [], []
    for r, row in enumerate(rows, start=1):
        cells = []
        for c, value in enumerate(row):
            ref = f"{chr(65 + c)}{r}"
            if isinstance(value, (int, float)):
                cells.append(f'<c r="{ref}"><v>{value}</v></c>')
            elif value != "":
                strings.append(value)
                cells.append(f'<c r="{ref}" t="s"><v>{len(strings) - 1}</v></c>')
        cells_xml.append(f'<row r="{r}">{"".join(cells)}</row>')
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/sharedStrings.xml", f"<sst {ns}>" + "".join(f"<si><t>{s}</t></si>" for s in strings) + "</sst>")
        z.writestr("xl/worksheets/sheet1.xml", f"<worksheet {ns}><sheetData>{''.join(cells_xml)}</sheetData></worksheet>")
    return buf.getvalue()


def _db() -> Session:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return Session(engine)


def test_money():
    assert parse_money("49,90") == 49.9
    assert parse_money("R$ 1.234,56") == 1234.56
    assert parse_money("49.9") == 49.9
    assert parse_money("abc") is None


def test_template_csv():
    db = _db()
    result = import_products(db, read_sheet(TEMPLATE.encode("utf-8-sig")))
    assert result["created"] == ["Camiseta Básica", "Bermuda Sarja"], result
    assert not result["errors"]
    camiseta = db.scalar(select(Product).where(Product.name == "Camiseta Básica"))
    assert camiseta.price == 49.9 and not camiseta.active
    assert sorted((v.color, v.size, v.stock) for v in camiseta.variants) == [
        ("Branco", "M", 4), ("Preto", "M", 8), ("Preto", "P", 5)]
    bermuda = db.scalar(select(Product).where(Product.name == "Bermuda Sarja"))
    assert bermuda.compare_at_price == 119.9
    assert {c.name for c in db.scalars(select(Category))} == {"Camisetas", "Bermudas"}

    # importar de novo não duplica
    again = import_products(db, read_sheet(TEMPLATE.encode("utf-8-sig")))
    assert again["created"] == [] and len(again["skipped"]) == 2


def test_xlsx_and_errors():
    db = _db()
    sheet = _xlsx([
        ["Produto", "Valor", "Tamanho", "Cor", "Qtd"],
        ["Polo Piquet", 79.9, "G", "Azul", 3],
        ["Polo Piquet", "", "M", "Azul", 2],
        ["Calça Jeans", "", "42", "", 1],       # sem preço
        ["Boné", "39,90", "", "", "dois"],       # estoque inválido
        ["", "10", "", "", ""],                  # sem nome
    ])
    result = import_products(db, read_sheet(sheet))
    assert result["created"] == ["Polo Piquet"], result
    assert len(result["errors"]) == 3, result["errors"]
    polo = db.scalar(select(Product).where(Product.name == "Polo Piquet"))
    assert polo.price == 79.9 and len(polo.variants) == 2


def test_rejects_bad_files():
    for content in (b"Coluna;Outra\r\nx;y\r\n", b"PK\x03\x04lixo"):
        try:
            read_sheet(content)
        except SheetError:
            continue
        raise AssertionError("deveria recusar")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
