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
    # identificação exigida no site pelo Decreto 7.962/2013 (comércio eletrônico)
    legal_name: Mapped[str] = mapped_column(String(120), default="", server_default="")
    cnpj: Mapped[str] = mapped_column(String(18), default="", server_default="")
    announcement: Mapped[str] = mapped_column(String(160), default="")
    whatsapp: Mapped[str] = mapped_column(String(20), default="")
    instagram: Mapped[str] = mapped_column(String(60), default="")
    email: Mapped[str] = mapped_column(String(120), default="")
    address: Mapped[str] = mapped_column(String(200), default="")
    opening_hours: Mapped[str] = mapped_column(String(120), default="")
    # faixas de frete: o cliente paga; a loja escolhe a faixa pelo CEP de destino
    shipping_fee: Mapped[float] = mapped_column(default=0)  # mesma cidade da loja
    shipping_state_fee: Mapped[float] = mapped_column(default=0, server_default="0")  # mesmo estado
    shipping_other_fee: Mapped[float] = mapped_column(default=0, server_default="0")  # outros estados
    free_shipping_min: Mapped[float] = mapped_column(default=0)  # acima disso, a opção mais barata é grátis
    # frete real pelo Melhor Envio (token fica só no banco; o painel nunca recebe de volta)
    melhor_envio_token: Mapped[str | None] = mapped_column(Text)
    melhor_envio_sandbox: Mapped[bool] = mapped_column(default=False, server_default="0")
    # embalagem padrão de UMA peça (cm e gramas): o Melhor Envio junta as peças do pedido
    package_width_cm: Mapped[int] = mapped_column(default=20, server_default="20")
    package_height_cm: Mapped[int] = mapped_column(default=5, server_default="5")
    package_length_cm: Mapped[int] = mapped_column(default=28, server_default="28")
    package_weight_g: Mapped[int] = mapped_column(default=400, server_default="400")
    pix_discount_percent: Mapped[float] = mapped_column(default=0)
    pix_key: Mapped[str] = mapped_column(String(120), default="")
    max_installments: Mapped[int] = mapped_column(default=1)
    pickup_enabled: Mapped[bool] = mapped_column(default=False)
    # pedido "novo" não pago é cancelado depois desse prazo e o estoque volta (0 = nunca)
    order_hold_hours: Mapped[int] = mapped_column(default=24, server_default="24")
    max_qty_per_item: Mapped[int] = mapped_column(default=10, server_default="10")
    privacy_policy: Mapped[str] = mapped_column(Text, default="", server_default="")
    # trocas e devoluções: prazo para troca de tamanho e texto próprio (vazio = modelo automático)
    exchange_days: Mapped[int] = mapped_column(default=30, server_default="30")
    exchange_policy: Mapped[str] = mapped_column(Text, default="", server_default="")
    # cupom oferecido no pop-up de boas-vindas da vitrine (vazio = sem pop-up)
    welcome_coupon: Mapped[str] = mapped_column(String(30), default="", server_default="")
