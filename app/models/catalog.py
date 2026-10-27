from datetime import datetime

from sqlalchemy import JSON, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    slug: Mapped[str] = mapped_column(String(90), unique=True, index=True)
    image: Mapped[str | None] = mapped_column(String(255))
    sort: Mapped[int] = mapped_column(default=0)
    active: Mapped[bool] = mapped_column(default=True)
    # tabela de medidas mostrada em "Qual meu tamanho?": {"columns": [...], "rows": [[...], ...]}
    size_guide: Mapped[dict | None] = mapped_column(JSON)

    products: Mapped[list["Product"]] = relationship(back_populates="category")


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    slug: Mapped[str] = mapped_column(String(140), unique=True, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    price: Mapped[float]
    # "preço de" riscado, para mostrar desconto manual sem precisar criar promoção
    compare_at_price: Mapped[float | None]
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"))
    images: Mapped[list[str]] = mapped_column(JSON, default=list)
    # foto -> cor (ex.: {"/static/x.jpg": "Azul"}): na loja, escolher a cor mostra a foto dela
    image_colors: Mapped[dict[str, str]] = mapped_column(JSON, default=dict, server_default="{}")
    featured: Mapped[bool] = mapped_column(default=False)
    is_new: Mapped[bool] = mapped_column(default=False)
    active: Mapped[bool] = mapped_column(default=True)
    sold_count: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    category: Mapped[Category | None] = relationship(back_populates="products")
    variants: Mapped[list["ProductVariant"]] = relationship(
        back_populates="product", cascade="all, delete-orphan", order_by="ProductVariant.id"
    )

    @property
    def stock(self) -> int:
        return sum(v.stock for v in self.variants)


class ProductVariant(Base):
    """Uma combinação de tamanho/cor com seu próprio estoque."""

    __tablename__ = "product_variants"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"))
    size: Mapped[str] = mapped_column(String(10))
    color: Mapped[str | None] = mapped_column(String(40))
    stock: Mapped[int] = mapped_column(default=0)

    product: Mapped[Product] = relationship(back_populates="variants")
