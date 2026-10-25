from datetime import datetime
from enum import StrEnum

from sqlalchemy import JSON, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.catalog import Product


def _in_period(active: bool, starts_at: datetime | None, ends_at: datetime | None, now: datetime) -> bool:
    return active and (starts_at is None or starts_at <= now) and (ends_at is None or now <= ends_at)


class PromotionKind(StrEnum):
    PERCENT = "percent"          # 20% off
    FIXED = "fixed"              # R$ 30 off por peça
    BUY_X_PAY_Y = "buy_x_pay_y"  # leve 3 pague 2


class PromotionScope(StrEnum):
    ALL = "all"
    CATEGORY = "category"
    PRODUCTS = "products"


class Promotion(Base):
    __tablename__ = "promotions"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    badge: Mapped[str] = mapped_column(String(30), default="Promoção")
    kind: Mapped[PromotionKind] = mapped_column(String(20))
    value: Mapped[float] = mapped_column(default=0)
    buy_qty: Mapped[int] = mapped_column(default=0)
    pay_qty: Mapped[int] = mapped_column(default=0)
    scope: Mapped[PromotionScope] = mapped_column(String(20), default=PromotionScope.ALL)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"))
    product_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    starts_at: Mapped[datetime | None]
    ends_at: Mapped[datetime | None]
    active: Mapped[bool] = mapped_column(default=True)

    def is_running(self, now: datetime) -> bool:
        return _in_period(self.active, self.starts_at, self.ends_at, now)

    def applies_to(self, product: Product) -> bool:
        if self.scope == PromotionScope.ALL:
            return True
        if self.scope == PromotionScope.CATEGORY:
            return product.category_id == self.category_id
        return product.id in (self.product_ids or [])


class CouponKind(StrEnum):
    PERCENT = "percent"
    FIXED = "fixed"
    FREE_SHIPPING = "free_shipping"


class Coupon(Base):
    __tablename__ = "coupons"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    description: Mapped[str] = mapped_column(String(140), default="")
    kind: Mapped[CouponKind] = mapped_column(String(20))
    value: Mapped[float] = mapped_column(default=0)
    min_order: Mapped[float] = mapped_column(default=0)
    max_uses: Mapped[int | None]
    used_count: Mapped[int] = mapped_column(default=0)
    starts_at: Mapped[datetime | None]
    ends_at: Mapped[datetime | None]
    active: Mapped[bool] = mapped_column(default=True)

    def is_running(self, now: datetime) -> bool:
        return _in_period(self.active, self.starts_at, self.ends_at, now)


class Combo(Base):
    """Kit de peças vendido por um preço fechado (ex.: 3 camisetas por R$ 129)."""

    __tablename__ = "combos"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    image: Mapped[str | None] = mapped_column(String(255))
    price: Mapped[float]
    active: Mapped[bool] = mapped_column(default=True)

    items: Mapped[list["ComboItem"]] = relationship(
        back_populates="combo", cascade="all, delete-orphan", order_by="ComboItem.id"
    )

    @property
    def original_price(self) -> float:
        return round(sum(i.product.price * i.quantity for i in self.items), 2)


class ComboItem(Base):
    __tablename__ = "combo_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    combo_id: Mapped[int] = mapped_column(ForeignKey("combos.id", ondelete="CASCADE"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    quantity: Mapped[int] = mapped_column(default=1)

    combo: Mapped[Combo] = relationship(back_populates="items")
    product: Mapped[Product] = relationship()


class BannerPlacement(StrEnum):
    HERO = "hero"    # carrossel grande do topo
    STRIP = "strip"  # faixa larga no meio da página
    CARD = "card"    # cartões lado a lado


class Banner(Base):
    """Anúncio exibido na vitrine."""

    __tablename__ = "banners"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(120))
    subtitle: Mapped[str] = mapped_column(String(200), default="")
    image: Mapped[str | None] = mapped_column(String(255))
    cta_label: Mapped[str] = mapped_column(String(40), default="Ver agora")
    link: Mapped[str] = mapped_column(String(255), default="/loja")
    placement: Mapped[BannerPlacement] = mapped_column(String(10), default=BannerPlacement.HERO)
    bg_color: Mapped[str] = mapped_column(String(20), default="#111111")
    text_color: Mapped[str] = mapped_column(String(20), default="#ffffff")
    sort: Mapped[int] = mapped_column(default=0)
    starts_at: Mapped[datetime | None]
    ends_at: Mapped[datetime | None]
    active: Mapped[bool] = mapped_column(default=True)

    def is_running(self, now: datetime) -> bool:
        return _in_period(self.active, self.starts_at, self.ends_at, now)
