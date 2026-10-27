"""Frete automático pelo CEP do cliente.

O lojista não cobra um valor único para o Brasil inteiro: a loja compara o destino com o
endereço dela e escolhe a faixa (cidade, estado ou outros estados). Quem compra paga a entrega.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# "Rua Massapê, 40 (Loja 2) - São José Operário, Manaus/AM - CEP 69085-000"
_ADDRESS = re.compile(
    r"^.+, [^,()]+?(?: \([^)]*\))? - (?:.+?, )?([^,]+)/([A-Z]{2}) - CEP (\d{5}-\d{3})$"
)

# primeiros 5 dígitos do CEP → UF (faixas dos Correios)
_CEP_UF: list[tuple[int, int, str]] = [
    (1000, 19999, "SP"),
    (20000, 28999, "RJ"),
    (29000, 29999, "ES"),
    (30000, 39999, "MG"),
    (40000, 48999, "BA"),
    (49000, 49999, "SE"),
    (50000, 56999, "PE"),
    (57000, 57999, "AL"),
    (58000, 58999, "PB"),
    (59000, 59999, "RN"),
    (60000, 63999, "CE"),
    (64000, 64999, "PI"),
    (65000, 65999, "MA"),
    (66000, 68899, "PA"),
    (68900, 68999, "AP"),
    (69000, 69299, "AM"),
    (69300, 69399, "RR"),
    (69400, 69899, "AM"),
    (69900, 69999, "AC"),
    (70000, 72799, "DF"),
    (72800, 72999, "GO"),
    (73000, 73699, "DF"),
    (73700, 76799, "GO"),
    (76800, 76999, "RO"),
    (77000, 77999, "TO"),
    (78000, 78899, "MT"),
    (79000, 79999, "MS"),
    (80000, 87999, "PR"),
    (88000, 89999, "SC"),
    (90000, 99999, "RS"),
]


def money(value: float) -> float:
    return round(value + 1e-9, 2)


def digits_cep(value: str | None) -> str:
    return re.sub(r"\D", "", value or "")[:8]


def uf_from_cep(cep: str | None) -> str | None:
    raw = digits_cep(cep)
    if len(raw) < 5:
        return None
    prefix = int(raw[:5])
    for start, end, uf in _CEP_UF:
        if start <= prefix <= end:
            return uf
    return None


@dataclass(frozen=True)
class Origin:
    city: str
    state: str
    cep: str


def parse_origin(address: str) -> Origin | None:
    """Lê o endereço salvo pela tela de Configurações. Endereço antigo, escrito à mão: None."""
    m = _ADDRESS.match((address or "").strip())
    if not m:
        return None
    return Origin(city=m.group(1).strip(), state=m.group(2), cep=m.group(3))


def format_cnpj(value: str | None) -> str:
    raw = re.sub(r"[^0-9A-Za-z]", "", value or "").upper()
    if len(raw) != 14:
        return (value or "").strip()
    return f"{raw[:2]}.{raw[2:5]}.{raw[5:8]}/{raw[8:12]}-{raw[12:]}"


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().casefold())


@dataclass(frozen=True)
class ShippingQuote:
    amount: float
    pending: bool
    note: str


def resolve_rates(settings: Any) -> tuple[float, float, float]:
    """Cidade / estado / outros. 0 nos dois últimos + taxa local > 0: deriva sozinho (loja antiga)."""
    local = float(settings.shipping_fee or 0)
    state = float(getattr(settings, "shipping_state_fee", 0) or 0)
    other = float(getattr(settings, "shipping_other_fee", 0) or 0)
    if state == 0 and other == 0 and local > 0:
        state = money(local + 10)
        other = money(max(local + 22, 29.9))
    return local, state, other


def classify(
    origin: Origin | None,
    dest_cep: str | None,
    dest_city: str | None,
    dest_state: str | None,
) -> str | None:
    """'local' | 'state' | 'other'. None se ainda não dá para saber o destino."""
    dest_uf = (dest_state or "").strip().upper() or uf_from_cep(dest_cep)
    if not dest_uf and not (dest_city or "").strip() and len(digits_cep(dest_cep)) < 8:
        return None
    if not dest_uf:
        dest_uf = uf_from_cep(dest_cep)
    if not dest_uf:
        return "other"
    if origin is None:
        return "other"
    if dest_uf != origin.state:
        return "other"
    # mesmo estado: cidade só entra se os dois lados tiverem nome
    if dest_city and origin.city and _norm(dest_city) == _norm(origin.city):
        return "local"
    origin_prefix = digits_cep(origin.cep)[:5]
    dest_prefix = digits_cep(dest_cep)[:5]
    if origin_prefix and dest_prefix and origin_prefix == dest_prefix:
        return "local"
    return "state"


def quote_shipping(
    settings: Any,
    *,
    delivery_method: str,
    goods_total: float,
    free_shipping_coupon: bool,
    dest_cep: str | None = None,
    dest_city: str | None = None,
    dest_state: str | None = None,
    has_items: bool = True,
) -> ShippingQuote:
    pickup = str(getattr(delivery_method, "value", delivery_method)) == "retirada"
    if pickup or free_shipping_coupon or not has_items:
        return ShippingQuote(0.0, False, "Grátis")

    if settings.free_shipping_min and goods_total >= settings.free_shipping_min:
        return ShippingQuote(0.0, False, "Frete grátis")

    zone = classify(parse_origin(settings.address), dest_cep, dest_city, dest_state)
    if zone is None:
        return ShippingQuote(0.0, True, "Informe o CEP para calcular")

    local, state, other = resolve_rates(settings)
    amount = {"local": local, "state": state, "other": other}[zone]
    notes = {
        "local": "Entrega na sua cidade",
        "state": "Entrega no seu estado",
        "other": "Entrega para outro estado",
    }
    if amount <= 0:
        return ShippingQuote(0.0, False, "Grátis")
    return ShippingQuote(money(amount), False, notes[zone])
