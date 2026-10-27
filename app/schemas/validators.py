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


def _cnpj_digit(base: str) -> str:
    """Dígito verificador do CNPJ (vale também para o CNPJ com letras, emitido a partir de jul/2026)."""
    weights = list(range(len(base) - 7, 1, -1)) + list(range(9, 1, -1))
    total = sum((ord(c) - 48) * w for c, w in zip(base, weights))
    rest = total % 11
    return "0" if rest < 2 else str(11 - rest)


def _cnpj(value: str) -> str:
    """Aceita com ou sem pontuação e guarda no formato 00.000.000/0000-00."""
    raw = re.sub(r"[^0-9A-Za-z]", "", value).upper()
    if not raw:
        return ""
    if not re.fullmatch(r"[0-9A-Z]{12}[0-9]{2}", raw) or len(set(raw)) == 1:
        raise ValueError("CNPJ inválido: confira os 14 caracteres")
    first = _cnpj_digit(raw[:12])
    if raw[12:] != first + _cnpj_digit(raw[:12] + first):
        raise ValueError("CNPJ inválido: confira os números")
    return f"{raw[:2]}.{raw[2:5]}.{raw[5:8]}/{raw[8:12]}-{raw[12:]}"


def _hex(value: str) -> str:
    if not _HEX.match(value):
        raise ValueError("Cor inválida (use o formato #RRGGBB)")
    return value


ImageUrl = Annotated[str | None, AfterValidator(_image_url)]
Link = Annotated[str, AfterValidator(_link)]
HexColor = Annotated[str, AfterValidator(_hex)]
Whatsapp = Annotated[str, AfterValidator(_whatsapp)]
Instagram = Annotated[str, AfterValidator(_instagram)]
Cnpj = Annotated[str, AfterValidator(_cnpj)]
