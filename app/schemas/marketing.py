from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from app.models import BannerPlacement, CouponKind, PromotionKind, PromotionScope
from app.schemas.catalog import ORM, ProductOut
from app.schemas.validators import HexColor, ImageUrl, Link


class PromotionIn(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    badge: str = Field(default="Promoção", max_length=30)
    kind: PromotionKind
    value: float = Field(ge=0, default=0)
    buy_qty: int = Field(ge=0, default=0)
    pay_qty: int = Field(ge=0, default=0)
    scope: PromotionScope = PromotionScope.ALL
    category_id: int | None = None
    product_ids: list[int] = []
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    active: bool = True

    @model_validator(mode="after")
    def check_rules(self):
        if self.kind == PromotionKind.PERCENT and not 0 < self.value < 100:
            raise ValueError("Percentual deve estar entre 1 e 99")
        if self.kind == PromotionKind.FIXED and self.value <= 0:
            raise ValueError("Informe o valor do desconto")
        if self.kind == PromotionKind.BUY_X_PAY_Y and not 0 < self.pay_qty < self.buy_qty:
            raise ValueError("Em 'Leve X Pague Y', Y precisa ser menor que X")
        if self.scope == PromotionScope.CATEGORY and not self.category_id:
            raise ValueError("Escolha a categoria da promoção")
        if self.scope == PromotionScope.PRODUCTS and not self.product_ids:
            raise ValueError("Escolha ao menos um produto")
        return self


class PromotionOut(ORM):
    id: int
    name: str
    badge: str
    kind: PromotionKind
    value: float
    buy_qty: int
    pay_qty: int
    scope: PromotionScope
    category_id: int | None
    product_ids: list[int]
    starts_at: datetime | None
    ends_at: datetime | None
    active: bool
    running: bool = False


class CouponIn(BaseModel):
    code: str = Field(min_length=3, max_length=30)
    description: str = ""
    kind: CouponKind
    value: float = Field(ge=0, default=0)
    min_order: float = Field(ge=0, default=0)
    max_uses: int | None = Field(default=None, ge=1)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    active: bool = True


class CouponOut(ORM):
    id: int
    code: str
    description: str
    kind: CouponKind
    value: float
    min_order: float
    max_uses: int | None
    used_count: int
    starts_at: datetime | None
    ends_at: datetime | None
    active: bool


class ComboItemIn(BaseModel):
    product_id: int
    quantity: int = Field(ge=1, default=1)


class ComboIn(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    description: str = Field(default="", max_length=2000)
    image: ImageUrl = None
    price: float = Field(gt=0)
    active: bool = True
    items: list[ComboItemIn] = Field(min_length=1)


class ComboItemOut(BaseModel):
    product_id: int
    quantity: int
    product: ProductOut


class ComboOut(ORM):
    id: int
    name: str
    slug: str
    description: str
    image: str | None
    price: float
    original_price: float
    savings: float = 0
    active: bool
    items: list[ComboItemOut]


class BannerIn(BaseModel):
    title: str = Field(min_length=2, max_length=120)
    subtitle: str = Field(default="", max_length=200)
    image: ImageUrl = None
    cta_label: str = Field(default="Ver agora", max_length=40)
    link: Link = "/loja"
    placement: BannerPlacement = BannerPlacement.HERO
    bg_color: HexColor = "#111111"
    text_color: HexColor = "#ffffff"
    sort: int = 0
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    active: bool = True


class BannerOut(BannerIn, ORM):
    id: int
