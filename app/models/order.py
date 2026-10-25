from datetime import datetime
from enum import StrEnum

from sqlalchemy import ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class OrderStatus(StrEnum):
    NEW = "novo"
    PAID = "pago"
    PREPARING = "separando"
    SHIPPED = "enviado"
    DELIVERED = "entregue"
    CANCELED = "cancelado"


class PaymentMethod(StrEnum):
    PIX = "pix"
    CARD = "cartao"
    CASH = "dinheiro"


class DeliveryMethod(StrEnum):
    DELIVERY = "entrega"
    PICKUP = "retirada"


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(12), unique=True, index=True)
    status: Mapped[OrderStatus] = mapped_column(String(12), default=OrderStatus.NEW)

    customer_name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str] = mapped_column(String(30))
    email: Mapped[str | None] = mapped_column(String(120))

    delivery_method: Mapped[DeliveryMethod] = mapped_column(String(10))
    cep: Mapped[str | None] = mapped_column(String(10))
    street: Mapped[str | None] = mapped_column(String(120))
    number: Mapped[str | None] = mapped_column(String(20))
    complement: Mapped[str | None] = mapped_column(String(80))
    district: Mapped[str | None] = mapped_column(String(80))
    city: Mapped[str | None] = mapped_column(String(80))
    state: Mapped[str | None] = mapped_column(String(2))

    payment_method: Mapped[PaymentMethod] = mapped_column(String(10))
    installments: Mapped[int] = mapped_column(default=1)
    notes: Mapped[str] = mapped_column(Text, default="")

    subtotal: Mapped[float]
    discount: Mapped[float] = mapped_column(default=0)
    shipping: Mapped[float] = mapped_column(default=0)
    total: Mapped[float]
    coupon_code: Mapped[str | None] = mapped_column(String(30))

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    items: Mapped[list["OrderItem"]] = relationship(
        back_populates="order", cascade="all, delete-orphan", order_by="OrderItem.id"
    )


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"))
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"))
    variant_id: Mapped[int | None] = mapped_column(ForeignKey("product_variants.id"))
    combo_id: Mapped[int | None] = mapped_column(ForeignKey("combos.id"))
    combo_variant_ids: Mapped[str] = mapped_column(String(200), default="")  # "5,6,7"
    name: Mapped[str] = mapped_column(String(200))
    detail: Mapped[str] = mapped_column(String(300), default="")  # ex.: "Tam. M · Preto"
    image: Mapped[str | None] = mapped_column(String(255))
    quantity: Mapped[int]
    unit_price: Mapped[float]
    total: Mapped[float]

    order: Mapped[Order] = relationship(back_populates="items")
