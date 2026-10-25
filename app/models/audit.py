from datetime import datetime

from sqlalchemy import String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AuditLog(Base):
    """Trilha de auditoria: quem fez o quê no painel (e eventos de login)."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), index=True)
    user_id: Mapped[int | None]
    user_email: Mapped[str] = mapped_column(String(120), default="")
    action: Mapped[str] = mapped_column(String(40))  # criou, alterou, excluiu, login, login_falhou...
    entity: Mapped[str] = mapped_column(String(40), default="")  # products, orders, users...
    entity_id: Mapped[str] = mapped_column(String(40), default="")
    summary: Mapped[str] = mapped_column(String(300), default="")
    ip: Mapped[str] = mapped_column(String(64), default="")
