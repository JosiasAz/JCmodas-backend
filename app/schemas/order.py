from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, model_validator

from app.models import DeliveryMethod, OrderStatus, PaymentMethod
from app.schemas.catalog import ORM


class CartLineIn(BaseModel):
    product_id: int
    variant_id: int
    quantity: int = Field(ge=1, le=50)


class CartComboIn(BaseModel):
    combo_id: int
    quantity: int = Field(ge=1, le=20)
    # um variant_id por peça do combo, na ordem dos itens (ex.: 3 camisetas -> 3 tamanhos)
    variant_ids: list[int] = Field(max_length=20)


class QuoteIn(BaseModel):
    items: list[CartLineIn] = Field(default=[], max_length=50)
    combos: list[CartComboIn] = Field(default=[], max_length=20)
    coupon_code: str | None = Field(default=None, max_length=30)
    delivery_method: DeliveryMethod = DeliveryMethod.DELIVERY
    payment_method: PaymentMethod = PaymentMethod.PIX
    # CEP/cidade/UF do cliente: o frete só fecha quando o destino existe
    cep: str | None = Field(default=None, max_length=10)
    city: str | None = Field(default=None, max_length=80)
    state: str | None = Field(default=None, max_length=2)


class QuoteLine(BaseModel):
    key: str  # identifica a linha no carrinho do front ("p:12" ou "c:3:5,6,7")
    name: str
    detail: str
    image: str | None
    quantity: int
    unit_price: float
    old_unit_price: float | None
    total: float
    available: bool = True
    message: str | None = None


class Discount(BaseModel):
    label: str
    amount: float


class QuoteOut(BaseModel):
    lines: list[QuoteLine]
    subtotal: float
    discounts: list[Discount]
    discount_total: float
    shipping: float
    shipping_pending: bool = False
    shipping_note: str | None = None
    total: float
    coupon_code: str | None = None
    coupon_message: str | None = None
    coupon_valid: bool = False
    free_shipping_missing: float = 0
    max_installments: int = 1
    can_checkout: bool = True


class TrackIn(BaseModel):
    code: str = Field(min_length=4, max_length=12)
    phone: str = Field(min_length=8, max_length=30)


class OrderIn(QuoteIn):
    customer_name: str = Field(min_length=3, max_length=120)
    phone: str = Field(min_length=8, max_length=30)
    email: EmailStr | None = None
    cep: str | None = Field(default=None, max_length=10)
    street: str | None = Field(default=None, max_length=120)
    number: str | None = Field(default=None, max_length=20)
    complement: str | None = Field(default=None, max_length=80)
    district: str | None = Field(default=None, max_length=80)
    city: str | None = Field(default=None, max_length=80)
    state: str | None = Field(default=None, max_length=2)
    installments: int = Field(ge=1, le=12, default=1)
    notes: str = Field(default="", max_length=500)
    # campo invisível para pessoas; robôs que preenchem tudo caem aqui (anti-bot)
    website: str = Field(default="", max_length=200)

    @model_validator(mode="after")
    def address_required_for_delivery(self):
        if self.delivery_method == DeliveryMethod.DELIVERY:
            missing = [f for f in ("cep", "street", "number", "district", "city", "state") if not getattr(self, f)]
            if missing:
                raise ValueError("Preencha o endereço completo para entrega")
        return self


class OrderItemOut(ORM):
    id: int
    product_id: int | None
    combo_id: int | None
    name: str
    detail: str
    image: str | None
    quantity: int
    unit_price: float
    total: float


class OrderOut(ORM):
    id: int
    code: str
    status: OrderStatus
    customer_name: str
    phone: str
    email: str | None
    delivery_method: DeliveryMethod
    cep: str | None
    street: str | None
    number: str | None
    complement: str | None
    district: str | None
    city: str | None
    state: str | None
    payment_method: PaymentMethod
    installments: int
    notes: str
    subtotal: float
    discount: float
    shipping: float
    total: float
    coupon_code: str | None
    created_at: datetime
    items: list[OrderItemOut]


class OrderPage(BaseModel):
    items: list[OrderOut]
    total: int
    page: int
    pages: int


class OrderStatusIn(BaseModel):
    status: OrderStatus
