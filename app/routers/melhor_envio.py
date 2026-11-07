"""Conexão com o Melhor Envio (OAuth): o lojista autoriza uma vez e o token se renova sozinho."""
import hmac
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.core.config import settings as config
from app.core.deps import DB, Admin
from app.core.rate_limit import limit
from app.services.pricing import get_settings
from app.services.shipping import ShippingUnavailable, authorize_url, exchange_code

router = APIRouter(prefix="/api", tags=["Painel - Melhor Envio"])


def _callback_url(request: Request) -> str:
    # precisa ser idêntico ao "Callback" cadastrado no aplicativo do Melhor Envio
    return str(request.url_for("melhor_envio_callback"))


def _panel_url(result: str) -> str:
    site = next((o for o in config.cors_origins if o.startswith("https://")), config.cors_origins[0])
    return f"{site.rstrip('/')}/admin/configuracoes?melhorenvio={result}"


@router.get("/admin/melhor-envio/callback-url")
def callback_url(request: Request, _: Admin):
    """Endereço que o lojista cola no campo Callback ao criar o aplicativo no Melhor Envio."""
    return {"callback_url": _callback_url(request)}


@router.post("/admin/melhor-envio/connect")
def connect(request: Request, db: DB, _: Admin):
    """Gera o link de autorização (o painel abre esse link e o lojista aprova no Melhor Envio)."""
    settings = get_settings(db)
    if not settings.melhor_envio_client_id or not settings.melhor_envio_client_secret:
        raise HTTPException(400, "Salve o Client ID e o Secret do aplicativo do Melhor Envio antes de conectar.")
    settings.melhor_envio_state = secrets.token_urlsafe(32)
    db.commit()
    return {"url": authorize_url(settings, settings.melhor_envio_state, _callback_url(request))}


@router.get("/melhor-envio/callback", name="melhor_envio_callback", include_in_schema=False,
            dependencies=[Depends(limit(10, 60))])
def callback(request: Request, db: DB, code: str = "", state: str = ""):
    """O Melhor Envio volta para cá depois que o lojista aprova. Sem login: quem prova é o `state`."""
    settings = get_settings(db)
    expected = settings.melhor_envio_state or ""
    if not code or not expected or not hmac.compare_digest(state, expected):
        return RedirectResponse(_panel_url("erro"), status_code=303)
    settings.melhor_envio_state = None  # cada autorização vale uma vez só
    try:
        exchange_code(settings, code, _callback_url(request))
    except ShippingUnavailable:
        db.commit()
        return RedirectResponse(_panel_url("erro"), status_code=303)
    db.commit()
    return RedirectResponse(_panel_url("ok"), status_code=303)
