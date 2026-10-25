from sqlalchemy import JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    email: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    is_admin: Mapped[bool] = mapped_column(default=True)
    # aumenta a cada troca de senha: tokens emitidos antes deixam de valer
    token_version: Mapped[int] = mapped_column(default=0, server_default="0")

    # verificação em duas etapas (TOTP)
    mfa_enabled: Mapped[bool] = mapped_column(default=False, server_default="0")
    mfa_secret: Mapped[str | None] = mapped_column(String(64))
    mfa_last_step: Mapped[int] = mapped_column(default=0, server_default="0")  # impede reusar o mesmo código
    mfa_recovery: Mapped[list[str]] = mapped_column(JSON, default=list, server_default="[]")  # hashes dos códigos de recuperação


class StoreSettings(Base):
    """Configurações gerais da loja (tabela de uma linha só)."""

    __tablename__ = "store_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    store_name: Mapped[str] = mapped_column(String(80), default="JC Moda Masculina")
    announcement: Mapped[str] = mapped_column(String(160), default="")
    whatsapp: Mapped[str] = mapped_column(String(20), default="")
    instagram: Mapped[str] = mapped_column(String(60), default="")
    email: Mapped[str] = mapped_column(String(120), default="")
    address: Mapped[str] = mapped_column(String(200), default="")
    opening_hours: Mapped[str] = mapped_column(String(120), default="")
    shipping_fee: Mapped[float] = mapped_column(default=0)
    free_shipping_min: Mapped[float] = mapped_column(default=0)
    pix_discount_percent: Mapped[float] = mapped_column(default=0)
    pix_key: Mapped[str] = mapped_column(String(120), default="")
    max_installments: Mapped[int] = mapped_column(default=1)
    pickup_enabled: Mapped[bool] = mapped_column(default=False)
    # pedido "novo" não pago é cancelado depois desse prazo e o estoque volta (0 = nunca)
    order_hold_hours: Mapped[int] = mapped_column(default=24, server_default="24")
    max_qty_per_item: Mapped[int] = mapped_column(default=10, server_default="10")
    privacy_policy: Mapped[str] = mapped_column(Text, default="", server_default="")
