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


def _hex(value: str) -> str:
    if not _HEX.match(value):
        raise ValueError("Cor inválida (use o formato #RRGGBB)")
    return value


ImageUrl = Annotated[str | None, AfterValidator(_image_url)]
Link = Annotated[str, AfterValidator(_link)]
HexColor = Annotated[str, AfterValidator(_hex)]
