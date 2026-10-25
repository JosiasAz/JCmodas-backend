"""Painel: categorias, produtos e upload de imagens."""
from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from PIL import Image, ImageOps
from starlette.concurrency import run_in_threadpool
from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

from app.core.deps import DB, Admin
from app.core.rate_limit import limit
from app.models import Category, ComboItem, Product, ProductVariant
from app.schemas.catalog import CategoryIn, CategoryOut, ProductIn, ProductOut
from app.services.pricing import running_promotions, serialize_product
from app.services.slug import unique_slug
from app.services.storage import save_image

router = APIRouter(prefix="/api/admin", tags=["Painel - Catálogo"])

# 4 MB (o Nginx do servidor aceita até 6 MB: client_max_body_size)
MAX_UPLOAD = 4 * 1024 * 1024
MAX_PIXELS = 40_000_000  # ~ 7000 x 5700: acima disso é "bomba" de descompressão, não foto de produto
Image.MAX_IMAGE_PIXELS = MAX_PIXELS
_SAVE_FORMAT = {".jpg": ("JPEG", {"quality": 88, "optimize": True}), ".png": ("PNG", {"optimize": True}),
                ".webp": ("WEBP", {"quality": 88})}


def _image_extension(content: bytes) -> str | None:
    """Identifica a imagem pelos primeiros bytes (a extensão do nome pode ser falsa).

    SVG não é aceito: pode conter JavaScript e roubar a sessão de quem abrir a imagem.
    """
    if content.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if content[:6] in (b"GIF87a", b"GIF89a"):
        return ".gif"
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return ".webp"
    return None


def _clean_image(content: bytes, ext: str) -> bytes:
    """Regrava a imagem sem metadados (EXIF com GPS, modelo do celular, data...).

    A rotação que vinha no EXIF é aplicada antes, para a foto não ficar deitada. Regravar também
    desmonta arquivos "poliglotas" (imagem válida com outro conteúdo escondido no fim).
    GIF fica como está (não tem EXIF e regravar perderia a animação).
    """
    if ext == ".gif":
        return content
    try:
        with Image.open(BytesIO(content)) as img:
            img = ImageOps.exif_transpose(img)
            if ext == ".jpg" and img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            out = BytesIO()
            fmt, options = _SAVE_FORMAT[ext]
            img.save(out, fmt, **options)
            return out.getvalue()
    except Image.DecompressionBombError:
        raise HTTPException(400, "Imagem com resolução grande demais")
    except Exception:
        raise HTTPException(400, "Não foi possível ler a imagem. Tente outro arquivo.")


# ---------------------------------------------------------------- categorias


@router.get("/categories", response_model=list[CategoryOut])
def list_categories(db: DB, _: Admin):
    counts = dict(db.execute(select(Product.category_id, func.count()).group_by(Product.category_id)).all())
    categories = db.scalars(select(Category).order_by(Category.sort, Category.name)).all()
    return [CategoryOut.model_validate(c).model_copy(update={"product_count": counts.get(c.id, 0)})
            for c in categories]


@router.post("/categories", response_model=CategoryOut, status_code=201)
def create_category(data: CategoryIn, db: DB, _: Admin):
    category = Category(**data.model_dump(), slug=unique_slug(db, Category, data.name))
    db.add(category)
    db.commit()
    return category


@router.put("/categories/{category_id}", response_model=CategoryOut)
def update_category(category_id: int, data: CategoryIn, db: DB, _: Admin):
    category = db.get(Category, category_id) or _not_found("Categoria")
    for key, value in data.model_dump().items():
        setattr(category, key, value)
    category.slug = unique_slug(db, Category, data.name, category.id)
    db.commit()
    return category


@router.delete("/categories/{category_id}", status_code=204)
def delete_category(category_id: int, db: DB, _: Admin):
    category = db.get(Category, category_id) or _not_found("Categoria")
    if db.scalar(select(func.count()).where(Product.category_id == category_id)):
        raise HTTPException(400, "Mova ou exclua os produtos desta categoria antes de removê-la")
    db.delete(category)
    db.commit()


# ---------------------------------------------------------------- produtos


@router.get("/products", response_model=list[ProductOut])
def list_products(db: DB, _: Admin, q: str | None = None, category_id: int | None = None):
    query = (
        select(Product)
        .options(selectinload(Product.variants), selectinload(Product.category))
        .order_by(Product.id.desc())
    )
    if q:
        query = query.where(or_(Product.name.ilike(f"%{q}%"), Product.slug.ilike(f"%{q}%")))
    if category_id:
        query = query.where(Product.category_id == category_id)
    promos = running_promotions(db)
    return [serialize_product(p, promos) for p in db.scalars(query)]


@router.get("/products/{product_id}", response_model=ProductOut)
def get_product(product_id: int, db: DB, _: Admin):
    product = db.get(Product, product_id) or _not_found("Produto")
    return serialize_product(product, running_promotions(db))


@router.post("/products", response_model=ProductOut, status_code=201)
def create_product(data: ProductIn, db: DB, _: Admin, request: Request):
    request.state.audit_summary = f"{data.name} · R$ {data.price:.2f}"
    product = Product(
        **data.model_dump(exclude={"variants"}),
        slug=unique_slug(db, Product, data.name),
        variants=[ProductVariant(**v.model_dump(exclude={"id"})) for v in data.variants],
    )
    db.add(product)
    db.commit()
    return serialize_product(product, running_promotions(db))


@router.put("/products/{product_id}", response_model=ProductOut)
def update_product(product_id: int, data: ProductIn, db: DB, _: Admin, request: Request):
    product = db.get(Product, product_id) or _not_found("Produto")
    # preço é o que mais importa vigiar na trilha de auditoria
    price = f"R$ {product.price:.2f} → R$ {data.price:.2f}" if product.price != data.price else f"R$ {data.price:.2f}"
    request.state.audit_summary = f"{data.name} · {price}" + ("" if data.active else " · escondido da loja")
    for key, value in data.model_dump(exclude={"variants"}).items():
        setattr(product, key, value)
    product.slug = unique_slug(db, Product, data.name, product.id)

    # atualiza variações existentes (mantém o id, que está nos pedidos), cria novas e remove as que saíram
    current = {v.id: v for v in product.variants}
    keep = []
    for v in data.variants:
        variant = current.get(v.id) if v.id else None
        if variant:
            variant.size, variant.color, variant.stock = v.size, v.color, v.stock
        else:
            variant = ProductVariant(size=v.size, color=v.color, stock=v.stock)
        keep.append(variant)
    product.variants = keep
    db.commit()
    return serialize_product(product, running_promotions(db))


@router.delete("/products/{product_id}", status_code=204)
def delete_product(product_id: int, db: DB, _: Admin, request: Request):
    product = db.get(Product, product_id) or _not_found("Produto")
    request.state.audit_summary = product.name
    if db.scalar(select(func.count()).where(ComboItem.product_id == product_id)):
        raise HTTPException(400, "Este produto faz parte de um combo. Remova-o do combo primeiro.")
    if product.sold_count:
        # já foi vendido: só desativa, para não perder o histórico dos pedidos
        product.active = False
    else:
        db.delete(product)
    db.commit()


# ---------------------------------------------------------------- imagens


@router.post("/uploads", dependencies=[Depends(limit(30, 60))])
async def upload_image(file: UploadFile, _: Admin):
    content = await file.read(MAX_UPLOAD + 1)
    if len(content) > MAX_UPLOAD:
        raise HTTPException(400, "Imagem muito grande (máximo 4 MB)")
    ext = _image_extension(content)
    if not ext:
        raise HTTPException(400, "Envie uma imagem JPG, PNG, WEBP ou GIF")
    content = _clean_image(content, ext)
    return {"url": await run_in_threadpool(save_image, content, ext)}


def _not_found(what: str):
    raise HTTPException(404, f"{what} não encontrado(a)")
