"""Regras de preço da loja.

Tudo que envolve dinheiro passa por aqui, para que vitrine, carrinho e pedido mostrem sempre o
mesmo valor:
  1. promoções por peça (% ou R$) -> preço final de cada produto
  2. promoções "Leve X Pague Y" -> desconto no carrinho, as peças mais baratas saem de graça
  3. combos -> preço fechado do kit
  4. cupom -> % / R$ / frete grátis
  5. desconto no Pix
  6. frete (grátis acima de um valor ou na retirada)
"""
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    Combo,
    ComboItem,
    Coupon,
    CouponKind,
    DeliveryMethod,
    PaymentMethod,
    Product,
    ProductVariant,
    Promotion,
    PromotionKind,
    StoreSettings,
)
from app.schemas.catalog import ProductOut
from app.schemas.marketing import ComboItemOut, ComboOut
from app.schemas.order import Discount, QuoteIn, QuoteLine, QuoteOut

MIN_INSTALLMENT = 30.0  # valor mínimo de cada parcela no cartão


def money(value: float) -> float:
    return round(value + 1e-9, 2)


def running_promotions(db: Session, now: datetime | None = None) -> list[Promotion]:
    now = now or datetime.now()
    promos = db.scalars(select(Promotion).where(Promotion.active).order_by(Promotion.id)).all()
    return [p for p in promos if p.is_running(now)]


def get_settings(db: Session) -> StoreSettings:
    settings = db.get(StoreSettings, 1)
    if settings is None:
        settings = StoreSettings(id=1)
        db.add(settings)
        db.commit()
    return settings


# ---------------------------------------------------------------- vitrine


def price_product(product: Product, promos: list[Promotion]) -> dict:
    """Preço que o cliente vê na vitrine, já com a melhor promoção por peça aplicada."""
    final = product.price
    badges: list[str] = []
    for promo in promos:
        if not promo.applies_to(product):
            continue
        if promo.kind == PromotionKind.BUY_X_PAY_Y:
            badges.append(promo.badge or f"Leve {promo.buy_qty} Pague {promo.pay_qty}")
            continue
        if promo.kind == PromotionKind.PERCENT:
            candidate = product.price * (1 - promo.value / 100)
        else:
            candidate = product.price - promo.value
        candidate = max(money(candidate), 0.01)
        if candidate < final:
            final = candidate
            badges.insert(0, promo.badge)

    reference = max(product.price, product.compare_at_price or 0)
    old_price = reference if reference > final else None
    discount = round((1 - final / reference) * 100) if old_price else 0
    if product.is_new:
        badges.append("Novo")
    return {
        "final_price": money(final),
        "old_price": old_price,
        "discount_percent": discount,
        "badges": list(dict.fromkeys(badges)),  # sem repetidos, mantendo a ordem
    }


def serialize_product(product: Product, promos: list[Promotion]) -> ProductOut:
    out = ProductOut.model_validate(product)
    if product.category:
        out.category_name, out.category_slug = product.category.name, product.category.slug
    return out.model_copy(update=price_product(product, promos))


def serialize_combo(combo: Combo, promos: list[Promotion]) -> ComboOut:
    items = [
        ComboItemOut(product_id=i.product_id, quantity=i.quantity, product=serialize_product(i.product, promos))
        for i in combo.items
    ]
    return ComboOut(
        id=combo.id,
        name=combo.name,
        slug=combo.slug,
        description=combo.description,
        image=combo.image,
        price=combo.price,
        original_price=combo.original_price,
        savings=money(max(combo.original_price - combo.price, 0)),
        active=combo.active,
        items=items,
    )


# ---------------------------------------------------------------- carrinho


def variant_label(variant: ProductVariant) -> str:
    return f"Tam. {variant.size}" + (f" · {variant.color}" if variant.color else "")


@dataclass
class ResolvedLine:
    """Linha do carrinho já validada, usada para gravar o pedido."""

    quote: QuoteLine
    product: Product | None = None
    variant: ProductVariant | None = None
    combo: Combo | None = None
    combo_variants: list[ProductVariant] = field(default_factory=list)


@dataclass
class QuoteResult:
    quote: QuoteOut
    lines: list[ResolvedLine]
    coupon: Coupon | None


def build_quote(db: Session, data: QuoteIn) -> QuoteResult:
    settings = get_settings(db)
    promos = running_promotions(db)
    resolved: list[ResolvedLine] = []
    reserved: Counter[int] = Counter()  # quantas peças de cada variação o carrinho pede

    # --- produtos avulsos
    variant_ids = {i.variant_id for i in data.items} | {v for c in data.combos for v in c.variant_ids}
    variants = {
        v.id: v
        for v in db.scalars(
            select(ProductVariant)
            .where(ProductVariant.id.in_(variant_ids))
            .options(selectinload(ProductVariant.product).selectinload(Product.category))
        )
    }

    for item in data.items:
        variant = variants.get(item.variant_id)
        if not variant or variant.product_id != item.product_id or not variant.product.active:
            continue  # item removido da loja: some do carrinho
        product = variant.product
        pricing = price_product(product, promos)
        reserved[variant.id] += item.quantity
        resolved.append(ResolvedLine(
            quote=QuoteLine(
                key=f"p:{variant.id}",
                name=product.name,
                detail=variant_label(variant),
                image=product.images[0] if product.images else None,
                quantity=item.quantity,
                unit_price=pricing["final_price"],
                old_unit_price=pricing["old_price"],
                total=money(pricing["final_price"] * item.quantity),
            ),
            product=product,
            variant=variant,
        ))

    # --- combos
    combo_ids = {c.combo_id for c in data.combos}
    combos = {
        c.id: c
        for c in db.scalars(
            select(Combo)
            .where(Combo.id.in_(combo_ids), Combo.active)
            .options(selectinload(Combo.items).selectinload(ComboItem.product))
        )
    }
    for item in data.combos:
        combo = combos.get(item.combo_id)
        if not combo:
            continue
        expected = [ci.product_id for ci in combo.items for _ in range(ci.quantity)]
        chosen = [variants.get(v) for v in item.variant_ids]
        if len(chosen) != len(expected) or any(
            v is None or v.product_id != pid for v, pid in zip(chosen, expected)
        ):
            continue  # combo mudou desde que foi colocado no carrinho
        for v in chosen:
            reserved[v.id] += item.quantity
        resolved.append(ResolvedLine(
            quote=QuoteLine(
                key=f"c:{combo.id}:{','.join(str(v) for v in item.variant_ids)}",
                name=combo.name,
                detail=" + ".join(f"{v.product.name} ({variant_label(v)})" for v in chosen),
                image=combo.image or (chosen[0].product.images[0] if chosen[0].product.images else None),
                quantity=item.quantity,
                unit_price=combo.price,
                old_unit_price=combo.original_price if combo.original_price > combo.price else None,
                total=money(combo.price * item.quantity),
            ),
            combo=combo,
            combo_variants=chosen,
        ))

    # --- estoque
    can_checkout = bool(resolved)
    for line in resolved:
        needed = [line.variant] if line.variant else line.combo_variants
        short = [v for v in needed if reserved[v.id] > v.stock]
        if short:
            can_checkout = False
            line.quote.available = False
            v = short[0]
            line.quote.message = (
                f"Esgotado: {v.product.name} {variant_label(v)}"
                if v.stock == 0
                else f"Só temos {v.stock} un. de {v.product.name} {variant_label(v)}"
            )

    # limite por item (evita que um único pedido segure todo o estoque de uma peça)
    for line in resolved:
        if line.quote.quantity > settings.max_qty_per_item:
            can_checkout = False
            line.quote.available = False
            line.quote.message = f"Máximo de {settings.max_qty_per_item} unidades por item"

    subtotal = money(sum(line.quote.total for line in resolved))
    discounts: list[Discount] = []

    # --- leve X pague Y: as peças mais baratas do grupo saem de graça
    used_units: set[tuple[int, int]] = set()
    for promo in promos:
        if promo.kind != PromotionKind.BUY_X_PAY_Y or promo.buy_qty <= promo.pay_qty:
            continue
        units = [
            (line.quote.unit_price, idx, n)
            for idx, line in enumerate(resolved)
            if line.product and promo.applies_to(line.product)
            for n in range(line.quote.quantity)
            if (idx, n) not in used_units
        ]
        free = (len(units) // promo.buy_qty) * (promo.buy_qty - promo.pay_qty)
        if free:
            units.sort()
            used_units.update((idx, n) for _, idx, n in units[: (len(units) // promo.buy_qty) * promo.buy_qty])
            discounts.append(Discount(label=promo.name, amount=money(sum(p for p, _, _ in units[:free]))))

    # --- cupom
    coupon: Coupon | None = None
    coupon_message = None
    free_shipping_coupon = False
    if data.coupon_code:
        code = data.coupon_code.strip().upper()
        coupon = db.scalar(select(Coupon).where(Coupon.code == code))
        base = subtotal - sum(d.amount for d in discounts)
        if not coupon or not coupon.is_running(datetime.now()):
            coupon, coupon_message = None, "Cupom inválido ou expirado"
        elif coupon.max_uses and coupon.used_count >= coupon.max_uses:
            coupon, coupon_message = None, "Este cupom já atingiu o limite de usos"
        elif base < coupon.min_order:
            coupon_message = f"Válido para compras acima de R$ {coupon.min_order:.2f}".replace(".", ",")
            coupon = None
        else:
            if coupon.kind == CouponKind.FREE_SHIPPING:
                free_shipping_coupon = True
                coupon_message = "Frete grátis aplicado!"
            else:
                amount = base * coupon.value / 100 if coupon.kind == CouponKind.PERCENT else min(coupon.value, base)
                discounts.append(Discount(label=f"Cupom {coupon.code}", amount=money(amount)))
                coupon_message = "Cupom aplicado!"

    # --- frete (calculado antes do desconto Pix para não "perder" o frete grátis por causa dele)
    goods_total = max(subtotal - sum(d.amount for d in discounts), 0)
    free_shipping_missing = 0.0
    if data.delivery_method == DeliveryMethod.PICKUP or free_shipping_coupon or not resolved:
        shipping = 0.0
    elif settings.free_shipping_min and goods_total >= settings.free_shipping_min:
        shipping = 0.0
    else:
        shipping = settings.shipping_fee
        if settings.free_shipping_min:
            free_shipping_missing = money(settings.free_shipping_min - goods_total)

    # --- Pix
    if data.payment_method == PaymentMethod.PIX and settings.pix_discount_percent and goods_total:
        pct = settings.pix_discount_percent
        discounts.append(Discount(label=f"Desconto Pix ({pct:g}%)", amount=money(goods_total * pct / 100)))

    discount_total = money(min(sum(d.amount for d in discounts), subtotal))
    total = money(subtotal - discount_total + shipping)

    quote = QuoteOut(
        lines=[line.quote for line in resolved],
        subtotal=subtotal,
        discounts=discounts,
        discount_total=discount_total,
        shipping=money(shipping),
        total=total,
        coupon_code=coupon.code if coupon else None,
        coupon_message=coupon_message,
        coupon_valid=coupon is not None,
        free_shipping_missing=free_shipping_missing,
        max_installments=max(1, min(settings.max_installments, int(total // MIN_INSTALLMENT))),
        can_checkout=can_checkout,
    )
    return QuoteResult(quote=quote, lines=resolved, coupon=coupon)
