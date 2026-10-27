from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.validators import ImageUrl


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class SizeGuide(BaseModel):
    """Tabela de medidas: a 1ª coluna é o tamanho (P, M, G...), as outras são medidas em cm."""

    columns: list[Annotated[str, Field(max_length=30)]] = Field(min_length=2, max_length=5)
    rows: list[list[Annotated[str, Field(max_length=12)]]] = Field(max_length=12)

    @model_validator(mode="after")
    def same_width(self):
        # linhas sem nenhuma medida preenchida são descartadas
        self.rows = [r for r in self.rows if any(c.strip() for c in r[1:])]
        if any(len(r) != len(self.columns) for r in self.rows):
            raise ValueError("Cada linha da tabela de medidas precisa ter uma medida para cada coluna")
        return self


class CategoryIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    image: ImageUrl = None
    sort: int = 0
    active: bool = True
    size_guide: SizeGuide | None = None


class CategoryOut(ORM):
    id: int
    name: str
    slug: str
    image: str | None
    sort: int
    active: bool
    size_guide: SizeGuide | None = None
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
    image_colors: dict[str, Annotated[str, Field(max_length=40)]] = Field(default={}, max_length=12)
    featured: bool = False
    is_new: bool = False
    active: bool = True
    variants: list[VariantIn] = Field(default=[], max_length=100)

    @model_validator(mode="after")
    def _drop_stale_colors(self):
        # foto removida ou cor apagada não deixa sobra
        self.image_colors = {url: c.strip() for url, c in self.image_colors.items() if url in self.images and c.strip()}
        return self


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
    image_colors: dict[str, str] = {}
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
