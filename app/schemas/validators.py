import re
from typing import Annotated

from pydantic import AfterValidator

_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def _image_url(value: str | None) -> str | None:
    """Só imagens enviadas pelo painel (/static/...) ou links https. Bloqueia javascript:, data: etc."""
    if value in (None, ""):
        return None
    if value.startswith("/static/") or value.startswith("https://"):
        return value
    raise ValueError("A imagem deve ser enviada pelo painel ou ser um link https://")


def _link(value: str) -> str:
    """Destino de anúncio: rota interna (/loja...) ou link https."""
    if value.startswith("/") and not value.startswith("//") or value.startswith("https://"):
        return value
    raise ValueError("O link deve começar com / (página da loja) ou https://")


def _whatsapp(value: str) -> str:
    """Aceita o número do jeito que vem do WhatsApp ("+55 92 99329-9773", "(92) 99329-9773") e guarda só os dígitos com DDI."""
    digits = re.sub(r"\D", "", value).lstrip("0")
    if not digits:
        return ""
    if not value.strip().startswith("+") and len(digits) in (10, 11):  # DDD + número, sem o 55
        digits = "55" + digits
    if not 10 <= len(digits) <= 15:
        raise ValueError("WhatsApp inválido: informe DDD e número, ex.: (92) 99329-9773")
    return digits


def _instagram(value: str) -> str:
    """Aceita "@perfil", "perfil" ou o link do perfil e guarda só o nome."""
    value = re.sub(r"^(https?://)?(www\.)?instagram\.com/", "", value.strip(), flags=re.I)
    return value.split("?")[0].strip("/").lstrip("@")


def _hex(value: str) -> str:
    if not _HEX.match(value):
        raise ValueError("Cor inválida (use o formato #RRGGBB)")
    return value


ImageUrl = Annotated[str | None, AfterValidator(_image_url)]
Link = Annotated[str, AfterValidator(_link)]
HexColor = Annotated[str, AfterValidator(_hex)]
Whatsapp = Annotated[str, AfterValidator(_whatsapp)]
Instagram = Annotated[str, AfterValidator(_instagram)]
