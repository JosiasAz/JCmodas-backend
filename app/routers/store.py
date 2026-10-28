"""Rotas públicas usadas pela vitrine."""
import math
import re
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload

from app.core.deps import DB
from app.core.rate_limit import RateLimiter, client_ip, limit
from app.models import Banner, BannerPlacement, Category, Combo, ComboItem, Coupon, CouponKind, Order, Product, ProductVariant
from app.schemas.catalog import CategoryOut, ProductFilters, ProductOut, ProductPage
from app.schemas.marketing import BannerOut, ComboOut, PromotionOut
from app.schemas.order import OrderIn, OrderOut, QuoteIn, QuoteOut, TrackIn
from app.schemas.store import PublicSettingsOut
from app.services.exchange import exchange_text
from app.services.orders import create_order, expire_if_due, expire_pending_orders
from app.services.pricing import build_quote, get_settings, running_promotions, serialize_combo, serialize_product
from app.services.privacy import privacy_text
from app.services.storage import thumbnail

router = APIRouter(prefix="/api", tags=["Loja"])

Sort = Literal["relevance", "price_asc", "price_desc", "newest", "best_sellers", "discount"]


def _product_query():
    return (
        select(Product)
        .where(Product.active)
        .options(selectinload(Product.variants), selectinload(Product.category))
    )


def _active_combos(db: DB) -> list[Combo]:
    return list(db.scalars(
        select(Combo)
        .where(Combo.active)
        .options(selectinload(Combo.items).selectinload(ComboItem.product).selectinload(Product.variants))
        .order_by(Combo.id)
    ))


PHOTO_NAME = re.compile(r"[0-9a-f]{32}\.(jpg|png|webp)")  # só o nome que save_image gera: nada de "../"


@router.get("/img/{width}/{name}", include_in_schema=False)
def image_thumb(width: int, name: str):
    path = thumbnail(name, width) if PHOTO_NAME.fullmatch(name) else None
    if not path:
        raise HTTPException(404, "Imagem não encontrada")
    return FileResponse(path, media_type="image/webp", headers={"Cache-Control": "public, max-age=31536000, immutable"})


@router.get("/store", response_model=PublicSettingsOut)
def store_info(db: DB):
    return get_settings(db)


@router.get("/privacy")
def privacy(db: DB, template: bool = False):
    """Política de privacidade (a escrita no painel ou, se vazia ou ?template=1, o modelo padrão)."""
    store = get_settings(db)
    use_template = template or not store.privacy_policy.strip()
    return {"text": privacy_text(store, force_template=template), "is_template": use_template}


@router.get("/welcome")
def welcome(db: DB):
    """Oferta do pop-up de boas-vindas: o cupom escolhido em Configurações, se ainda estiver valendo."""
    code = get_settings(db).welcome_coupon.strip().upper()
    coupon = db.scalar(select(Coupon).where(Coupon.code == code)) if code else None
    if not coupon or not coupon.is_running(datetime.now()):
        return None
    if coupon.max_uses is not None and coupon.used_count >= coupon.max_uses:
        return None
    if coupon.kind == CouponKind.PERCENT:
        offer = f"{coupon.value:g}% OFF"
    elif coupon.kind == CouponKind.FIXED:
        offer = f"R$ {coupon.value:,.2f} OFF".replace(",", "X").replace(".", ",").replace("X", ".")
    else:
        offer = "Frete grátis"
    return {"code": coupon.code, "offer": offer, "min_order": coupon.min_order}


@router.get("/exchange")
def exchange(db: DB, template: bool = False):
    """Política de trocas e devoluções (a escrita no painel ou, se vazia ou ?template=1, o modelo padrão)."""
    store = get_settings(db)
    use_template = template or not store.exchange_policy.strip()
    return {"text": exchange_text(store, force_template=template), "is_template": use_template}


@router.get("/home")
def home(db: DB):
    """Tudo que a página inicial precisa, em uma chamada só."""
    now = datetime.now()
    promos = running_promotions(db, now)
    banners = [b for b in db.scalars(select(Banner).order_by(Banner.sort, Banner.id)) if b.is_running(now)]
    products = [serialize_product(p, promos) for p in db.scalars(_product_query())]
    in_stock = [p for p in products if p.stock > 0]

    def top(items, key, n=8):
        return sorted(items, key=key, reverse=True)[:n]

    return {
        "banners": {
            placement.value: [BannerOut.model_validate(b) for b in banners if b.placement == placement]
            for placement in BannerPlacement
        },
        "categories": [CategoryOut.model_validate(c) for c in db.scalars(
            select(Category).where(Category.active).order_by(Category.sort, Category.name)
        )],
        "featured": [p for p in in_stock if p.featured][:8],
        "on_sale": top([p for p in in_stock if p.discount_percent or p.badges and p.badges != ["Novo"]],
                       lambda p: p.discount_percent),
        "new_arrivals": top([p for p in in_stock if p.is_new], lambda p: p.id),
        "best_sellers": top(in_stock, lambda p: p.sold_count),
        "combos": [serialize_combo(c, promos) for c in _active_combos(db)][:4],
        "promotions": [
            PromotionOut.model_validate(p).model_copy(update={"running": True}) for p in promos
        ],
    }


@router.get("/categories", response_model=list[CategoryOut])
def categories(db: DB):
    return db.scalars(select(Category).where(Category.active).order_by(Category.sort, Category.name)).all()


@router.get("/products", response_model=ProductPage)
def products(
    db: DB,
    q: str | None = Query(None, max_length=80),
    category: str | None = Query(None, max_length=90),
    size: list[str] = Query(default=[]),
    color: list[str] = Query(default=[]),
    min_price: float | None = None,
    max_price: float | None = None,
    on_sale: bool = False,
    sort: Sort = "relevance",
    page: int = Query(1, ge=1),
    page_size: int = Query(12, ge=1, le=60),
):
    expire_if_due(db)  # estoque de pedidos não pagos vencidos volta antes de mostrar a vitrine
    query = _product_query()
    if q:
        like = f"%{q.strip()}%"
        query = query.where(or_(Product.name.ilike(like), Product.description.ilike(like)))
    if category:
        query = query.join(Category).where(Category.slug == category)
    if size or color:
        variant_filter = select(ProductVariant.product_id).where(ProductVariant.stock > 0)
        if size:
            variant_filter = variant_filter.where(ProductVariant.size.in_(size))
        if color:
            variant_filter = variant_filter.where(ProductVariant.color.in_(color))
        query = query.where(Product.id.in_(variant_filter))

    # o preço final depende das promoções, então filtramos/ordenamos depois de calcular
    promos = running_promotions(db)
    items = [serialize_product(p, promos) for p in db.scalars(query)]
    if min_price is not None:
        items = [p for p in items if p.final_price >= min_price]
    if max_price is not None:
        items = [p for p in items if p.final_price <= max_price]
    if on_sale:
        items = [p for p in items if p.discount_percent or any(b != "Novo" for b in p.badges)]

    sorters = {
        "relevance": lambda p: (p.stock > 0, p.featured, p.sold_count),
        "price_asc": lambda p: -p.final_price,
        "price_desc": lambda p: p.final_price,
        "newest": lambda p: p.id,
        "best_sellers": lambda p: p.sold_count,
        "discount": lambda p: p.discount_percent,
    }
    items.sort(key=sorters[sort], reverse=True)
    if sort != "relevance":  # esgotados sempre por último
        items.sort(key=lambda p: p.stock > 0, reverse=True)

    total = len(items)
    start = (page - 1) * page_size
    return ProductPage(
        items=items[start:start + page_size], total=total, page=page, pages=max(1, math.ceil(total / page_size))
    )


@router.get("/products/filters", response_model=ProductFilters)
def product_filters(db: DB):
    variants = db.scalars(
        select(ProductVariant).join(Product).where(Product.active, ProductVariant.stock > 0)
    ).all()
    size_order = ["PP", "P", "M", "G", "GG", "XG", "XGG", "EG"]
    sizes = sorted({v.size for v in variants}, key=lambda s: (
        size_order.index(s) if s in size_order else 100, int(s) if s.isdigit() else 0, s
    ))
    prices = [p.price for p in db.scalars(select(Product).where(Product.active))]
    return ProductFilters(
        sizes=sizes,
        colors=sorted({v.color for v in variants if v.color}),
        min_price=min(prices, default=0),
        max_price=max(prices, default=0),
    )


@router.get("/products/{slug}")
def product_detail(slug: str, db: DB):
    product = db.scalar(_product_query().where(Product.slug == slug))
    if not product:
        raise HTTPException(404, "Produto não encontrado")
    promos = running_promotions(db)
    related = db.scalars(
        _product_query().where(Product.category_id == product.category_id, Product.id != product.id).limit(8)
    )
    combos = [
        serialize_combo(c, promos) for c in _active_combos(db)
        if any(i.product_id == product.id for i in c.items)
    ]
    guide = product.category.size_guide if product.category else None
    return {
        "product": serialize_product(product, promos),
        "related": [serialize_product(p, promos) for p in related],
        "combos": combos,
        "size_guide": guide if guide and guide.get("rows") else None,
    }


@router.get("/combos", response_model=list[ComboOut])
def combos(db: DB):
    promos = running_promotions(db)
    return [serialize_combo(c, promos) for c in _active_combos(db)]


@router.get("/combos/{slug}", response_model=ComboOut)
def combo_detail(slug: str, db: DB):
    combo = next((c for c in _active_combos(db) if c.slug == slug), None)
    if not combo:
        raise HTTPException(404, "Combo não encontrado")
    return serialize_combo(combo, running_promotions(db))


# contra "adivinhar" cupons: no máximo 10 códigos diferentes que não funcionaram a cada 10 min por IP.
# Contamos códigos distintos para não punir quem só muda a quantidade no carrinho com o mesmo cupom.
_coupon_seen = RateLimiter(1, 10 * 60)
_coupon_misses = RateLimiter(10, 10 * 60)
COUPON_BLOCKED = "Muitas tentativas de cupom. Aguarde alguns minutos."


@router.post("/cart/quote", response_model=QuoteOut, dependencies=[Depends(limit(60, 60))])
def quote(data: QuoteIn, db: DB, request: Request):
    ip = client_ip(request)
    code = (data.coupon_code or "").strip().upper()
    if code and _coupon_misses.blocked(ip):
        result = build_quote(db, data.model_copy(update={"coupon_code": None})).quote
        return result.model_copy(update={"coupon_message": COUPON_BLOCKED})
    result = build_quote(db, data).quote
    if code and not result.coupon_valid and _coupon_seen.hit(f"{ip}|{code}") is None:
        _coupon_misses.hit(ip)
    return result


# pedidos reservam estoque: limite baixo evita que alguém "trave" a loja com pedidos falsos
@router.post("/orders", response_model=OrderOut, status_code=201, dependencies=[Depends(limit(5, 10 * 60))])
def place_order(data: OrderIn, db: DB):
    expire_pending_orders(db)  # libera o estoque preso em pedidos vencidos antes de reservar
    return create_order(db, data)


# POST com corpo JSON: código e telefone não ficam na URL (nem nos logs de acesso/proxy)
@router.post("/orders/track", response_model=OrderOut, dependencies=[Depends(limit(10, 60))])
def track_order(data: TrackIn, db: DB):
    """Acompanhar pedido: o cliente informa o código e o telefone usado na compra."""
    order = db.scalar(
        select(Order).where(Order.code == data.code.strip().upper()).options(selectinload(Order.items))
    )
    digits = re.sub(r"\D", "", data.phone)
    if not order or len(digits) < 8 or not re.sub(r"\D", "", order.phone).endswith(digits[-8:]):
        raise HTTPException(404, "Pedido não encontrado. Confira o código e o telefone.")
    return order
