from pydantic import BaseModel, ConfigDict, Field

from app.schemas.validators import ImageUrl


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class CategoryIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    image: ImageUrl = None
    sort: int = 0
    active: bool = True


class CategoryOut(ORM):
    id: int
    name: str
    slug: str
    image: str | None
    sort: int
    active: bool
    product_count: int = 0


class VariantIn(BaseModel):
    id: int | None = None
    size: str = Field(min_length=1, max_length=10)
    color: str | None = Field(default=None, max_length=40)
    stock: int = Field(ge=0, default=0)


class VariantOut(ORM):
    id: int
    size: str
    color: str | None
    stock: int


class ProductIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    description: str = Field(default="", max_length=5000)
    price: float = Field(gt=0)
    compare_at_price: float | None = Field(default=None, gt=0)
    category_id: int | None = None
    images: list[ImageUrl] = Field(default=[], max_length=12)
    featured: bool = False
    is_new: bool = False
    active: bool = True
    variants: list[VariantIn] = Field(default=[], max_length=100)


class ProductOut(ORM):
    id: int
    name: str
    slug: str
    description: str
    price: float
    compare_at_price: float | None
    category_id: int | None
    category_name: str | None = None
    category_slug: str | None = None
    images: list[str]
    featured: bool
    is_new: bool
    active: bool
    sold_count: int
    stock: int
    variants: list[VariantOut]
    # calculados pelas promoções ativas
    final_price: float = 0
    old_price: float | None = None
    discount_percent: int = 0
    badges: list[str] = []


class ProductPage(BaseModel):
    items: list[ProductOut]
    total: int
    page: int
    pages: int


class ProductFilters(BaseModel):
    """Opções disponíveis para os filtros da vitrine."""

    sizes: list[str]
    colors: list[str]
    min_price: float
    max_price: float
