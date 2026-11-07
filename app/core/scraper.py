"""Barra ferramenta que só veio copiar preço (curl, script, raspador).

Cliente no Chrome/Safari e o Google (busca) passam. Em desenvolvimento não filtra, para
não atrapalhar teste local. Quem imita um navegador ainda esbarra no limite por IP.
"""
import json
import re

from fastapi import HTTPException, Request, status

from app.core.config import settings
from app.services.audit import security_log

# busca e prévia de link: a loja precisa aparecer no Google e no WhatsApp
_ALLOWED = re.compile(
    r"googlebot|google-inspectiontool|adsbot-google|bingbot|duckduckbot|"
    r"facebookexternalhit|facebot|twitterbot|linkedinbot|whatsapp|"
    r"telegrambot|slackbot|applebot|pingdom|uptimerobot",
    re.I,
)

_BROWSER = re.compile(r"mozilla/.+(chrome/|firefox/|safari/|edg/)", re.I)


def block_scrapers(request: Request) -> None:
    if not settings.is_production:
        return
    ua = (request.headers.get("user-agent") or "").strip()
    if ua and (_ALLOWED.search(ua) or _BROWSER.search(ua)):
        return
    security_log.info(json.dumps({
        "event": "scraper_blocked",
        "ip": request.client.host if request.client else "",
        "path": request.url.path,
        "ua": ua[:180],
    }))
    raise HTTPException(status.HTTP_403_FORBIDDEN, "Acesso não permitido")
