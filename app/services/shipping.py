"""Frete real pelo Melhor Envio (Correios, Jadlog...): o cliente escolhe a opção e paga na compra.

A loja informa no painel o token do Melhor Envio, o endereço (de onde sai o CEP de origem) e o tamanho
padrão da embalagem. Sem isso, ou se o Melhor Envio não responder, NÃO há frete: o pedido com entrega
fica bloqueado. Nunca vira "frete grátis" por falta de configuração.
"""
from __future__ import annotations

import json
import logging
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("app.shipping")

# "Rua Massapê, 40 (Loja 2) - São José Operário, Manaus/AM - CEP 69085-000"
_ADDRESS = re.compile(
    r"^.+, [^,()]+?(?: \([^)]*\))? - (?:.+?, )?([^,]+)/([A-Z]{2}) - CEP (\d{5}-\d{3})$"
)
API = {False: "https://melhorenvio.com.br", True: "https://sandbox.melhorenvio.com.br"}
CACHE_SECONDS = 10 * 60  # o checkout recalcula a cada mudança: não consulta o Melhor Envio toda hora
_cache: dict[tuple, tuple[float, list[ShippingOption]]] = {}


def money(value: float) -> float:
    return round(value + 1e-9, 2)


def digits_cep(value: str | None) -> str:
    return re.sub(r"\D", "", value or "")[:8]


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


@dataclass(frozen=True)
class ShippingOption:
    id: int  # código do serviço no Melhor Envio (ex.: 1 = PAC, 2 = SEDEX)
    name: str
    company: str
    price: float
    days: int
    free: bool = False


@dataclass
class ShippingQuote:
    amount: float
    pending: bool  # True: ainda não dá para fechar a entrega (sem CEP, sem configuração ou erro)
    note: str
    options: list[ShippingOption] = field(default_factory=list)
    selected: int | None = None


class ShippingUnavailable(Exception):
    pass


def _fetch_options(token: str, sandbox: bool, contact: str, body: dict[str, Any]) -> list[ShippingOption]:
    req = urllib.request.Request(
        f"{API[sandbox]}/api/v2/me/shipment/calculate",
        data=json.dumps(body).encode(),
        method="POST",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "User-Agent": f"JC Moda ({contact})",  # o Melhor Envio exige nome do app + e-mail de contato
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as res:
            data = json.loads(res.read())
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        log.warning("Melhor Envio não respondeu: %s", exc)
        raise ShippingUnavailable from exc
    options = []
    for s in data if isinstance(data, list) else []:
        price = s.get("custom_price") or s.get("price")
        if s.get("error") or not price:
            continue  # serviço indisponível para esse trecho/tamanho
        options.append(ShippingOption(
            id=int(s["id"]), name=str(s.get("name", "")), company=str((s.get("company") or {}).get("name", "")),
            price=money(float(price)), days=int(s.get("custom_delivery_time") or s.get("delivery_time") or 0),
        ))
    if not options:
        raise ShippingUnavailable
    return sorted(options, key=lambda o: (o.price, o.days))


def shipping_options(settings: Any, dest_cep: str, items: list[tuple[int, float]]) -> list[ShippingOption]:
    """Opções reais de entrega para o carrinho (items = [(quantidade, preço unitário)])."""
    origin = parse_origin(settings.address)
    token = (getattr(settings, "melhor_envio_token", None) or "").strip()
    if not origin or not token:
        raise ShippingUnavailable
    sandbox = bool(getattr(settings, "melhor_envio_sandbox", False))
    box = (settings.package_width_cm, settings.package_height_cm, settings.package_length_cm, settings.package_weight_g)
    key = (digits_cep(origin.cep), dest_cep, tuple(items), box, sandbox, token[-8:])
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
        return hit[1]
    width, height, length, weight_g = box
    body = {
        "from": {"postal_code": digits_cep(origin.cep)},
        "to": {"postal_code": dest_cep},
        "products": [
            {"id": str(i), "width": width, "height": height, "length": length, "weight": weight_g / 1000,
             "insurance_value": money(price), "quantity": qty}
            for i, (qty, price) in enumerate(items)
        ],
        "options": {"receipt": False, "own_hand": False},
    }
    options = _fetch_options(token, sandbox, settings.email or "contato@jcmoda.com.br", body)
    if len(_cache) > 500:
        _cache.clear()
    _cache[key] = (time.monotonic(), options)
    return options


def quote_shipping(
    settings: Any,
    *,
    delivery_method: str,
    goods_total: float,
    free_shipping_coupon: bool,
    dest_cep: str | None = None,
    items: list[tuple[int, float]] | None = None,
    service: int | None = None,
) -> ShippingQuote:
    pickup = str(getattr(delivery_method, "value", delivery_method)) == "retirada"
    if pickup:
        return ShippingQuote(0.0, False, "Retirada na loja")
    if not items:
        return ShippingQuote(0.0, False, "")
    cep = digits_cep(dest_cep)
    if len(cep) != 8:
        return ShippingQuote(0.0, True, "Informe o CEP para calcular")
    try:
        options = shipping_options(settings, cep, items)
    except ShippingUnavailable:
        return ShippingQuote(0.0, True, "Não deu para calcular o frete agora. Tente de novo ou fale com a loja no WhatsApp.")
    # frete grátis só na opção mais barata (quem quer receber mais rápido paga a entrega)
    if free_shipping_coupon or (settings.free_shipping_min and goods_total >= settings.free_shipping_min):
        options = [ShippingOption(**{**o.__dict__, "price": 0.0, "free": True}) if i == 0 else o
                   for i, o in enumerate(options)]
    chosen = next((o for o in options if o.id == service), options[0])
    label = f"{chosen.company} {chosen.name}".strip()
    note = f"{label} · chega em até {chosen.days} {'dia útil' if chosen.days == 1 else 'dias úteis'}"
    return ShippingQuote(chosen.price, False, note, options, chosen.id)
