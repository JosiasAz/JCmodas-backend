"""Trilha de auditoria e log de segurança.

- `record()` grava uma linha em `audit_log` (aparece na tela Atividades do painel).
- `security_log` escreve eventos de segurança em JSON no stdout (para um coletor de logs/SIEM).
- O middleware em `main.py` chama `record()` para toda alteração feita no painel; as rotas podem
  detalhar o resumo com `request.state.audit_summary`.
"""
import json
import logging

from fastapi import Request

from app.core.database import SessionLocal
from app.core.rate_limit import client_ip
from app.models import AuditLog

security_log = logging.getLogger("jc.security")
if not security_log.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(message)s"))
    security_log.addHandler(_handler)
    security_log.setLevel(logging.INFO)
    security_log.propagate = False


def security_event(event: str, request: Request | None = None, **fields) -> None:
    payload = {"event": event, "ip": client_ip(request) if request else "", **fields}
    security_log.info(json.dumps(payload, ensure_ascii=False, default=str))


def record(
    action: str,
    *,
    request: Request | None = None,
    user_id: int | None = None,
    user_email: str = "",
    entity: str = "",
    entity_id: str | int = "",
    summary: str = "",
) -> None:
    """Grava a entrada em uma sessão própria: nunca derruba a operação principal."""
    try:
        with SessionLocal() as db:
            db.add(AuditLog(
                user_id=user_id,
                user_email=user_email[:120],
                action=action[:40],
                entity=entity[:40],
                entity_id=str(entity_id)[:40],
                summary=summary[:300],
                ip=client_ip(request)[:64] if request else "",
            ))
            db.commit()
    except Exception:  # noqa: BLE001 - auditoria não pode quebrar a venda
        security_log.exception("falha ao gravar auditoria")
