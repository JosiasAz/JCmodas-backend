from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.schemas.catalog import ORM
from app.schemas.validators import Cnpj, Instagram, Whatsapp
from app.services.shipping import format_cnpj


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class TokenOut(BaseModel):
    access_token: str
    name: str


class LoginOut(BaseModel):
    """Login: ou vem a sessão (access_token), ou vem o pedido do código de duas etapas (mfa_token)."""

    access_token: str | None = None
    name: str
    mfa_required: bool = False
    mfa_token: str | None = None
    mfa_enabled: bool = False
    mfa_setup_required: bool = False


class GoogleLoginIn(BaseModel):
    credential: str = Field(max_length=4000)  # ID token devolvido pelo botão do Google


class MfaLoginIn(BaseModel):
    mfa_token: str = Field(max_length=1000)
    code: str = Field(min_length=6, max_length=20)


class MfaSetupOut(BaseModel):
    secret: str
    otpauth_uri: str


class MfaCodeIn(BaseModel):
    code: str = Field(min_length=6, max_length=20)


class MfaDisableIn(BaseModel):
    password: str
    code: str = Field(min_length=6, max_length=20)


class MfaEnabledOut(BaseModel):
    recovery_codes: list[str]
    access_token: str


# senha forte o bastante para um painel com acesso a vendas e dados de clientes
Password = Annotated[str, Field(min_length=8, max_length=128)]


class UserCreate(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    email: EmailStr
    password: Password


class UserUpdate(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    email: EmailStr
    # vazio = mantém a senha atual
    password: Password | None = None
    # pessoa perdeu o celular: desliga a verificação em duas etapas dela (ela ativa de novo)
    reset_mfa: bool = False


class UserOut(ORM):
    id: int
    name: str
    email: str
    is_me: bool = False
    mfa_enabled: bool = False


class PasswordChange(BaseModel):
    current_password: str
    new_password: Password


class StoreBase(BaseModel):
    store_name: str = Field(min_length=2, max_length=80)
    legal_name: str = ""
    cnpj: str = ""
    exchange_days: int = Field(default=30, ge=7, le=365)
    announcement: str = ""
    whatsapp: str = ""
    instagram: str = ""
    email: str = ""
    address: str = ""
    opening_hours: str = ""
    shipping_fee: float = Field(ge=0)
    shipping_state_fee: float = Field(default=0, ge=0)
    shipping_other_fee: float = Field(default=0, ge=0)
    free_shipping_min: float = Field(ge=0)
    pix_discount_percent: float = Field(ge=0, lt=100)
    pix_key: str = ""
    max_installments: int = Field(ge=1, le=12)
    pickup_enabled: bool = True
    order_hold_hours: int = Field(default=24, ge=0, le=720)
    max_qty_per_item: int = Field(default=10, ge=1, le=50)


class SettingsIn(StoreBase):
    # normaliza o que o lojista cola (só na entrada: dados antigos no banco não travam a vitrine)
    whatsapp: Whatsapp = ""
    instagram: Instagram = Field(default="", max_length=60)
    email: str = Field(default="", max_length=120)
    address: str = Field(default="", max_length=200)
    opening_hours: str = Field(default="", max_length=120)
    legal_name: str = Field(default="", max_length=120)
    cnpj: Cnpj = ""
    privacy_policy: str = Field(default="", max_length=30000)
    exchange_policy: str = Field(default="", max_length=30000)
    welcome_coupon: str = Field(default="", max_length=30)


class SettingsOut(StoreBase, ORM):
    privacy_policy: str = ""
    exchange_policy: str = ""
    welcome_coupon: str = ""

    @field_validator("cnpj", mode="before")
    @classmethod
    def _cnpj_out(cls, value: str | None) -> str:
        return format_cnpj(value or "")


class PublicSettingsOut(StoreBase, ORM):
    """O que a vitrine recebe (sem a política de privacidade, que tem rota própria)."""

    @field_validator("cnpj", mode="before")
    @classmethod
    def _cnpj_out(cls, value: str | None) -> str:
        return format_cnpj(value or "")


class AuditOut(ORM):
    id: int
    created_at: datetime
    user_email: str
    action: str
    entity: str
    entity_id: str
    summary: str
    ip: str


class AuditPage(BaseModel):
    items: list[AuditOut]
    total: int
    page: int
    pages: int


class DashboardOut(BaseModel):
    revenue: float
    orders: int
    average_ticket: float
    new_orders: int
    products_active: int
    low_stock: list[dict]
    top_products: list[dict]
    sales_by_day: list[dict]
    orders_by_status: dict[str, int]
