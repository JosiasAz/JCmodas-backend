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
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
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


_ADDRESS_PARTS = re.compile(
    r"^(?P<street>.+), (?P<number>[^,()]+?)(?: \((?P<complement>[^)]*)\))? - (?:(?P<district>.+?), )?"
    r"(?P<city>[^,]+)/(?P<state>[A-Z]{2}) - CEP (?P<cep>\d{5}-\d{3})$"
)


def parse_address(address: str) -> dict[str, str] | None:
    """Endereço da loja em partes (rua, número, complemento, bairro, cidade, UF, CEP) para a etiqueta."""
    m = _ADDRESS_PARTS.match((address or "").strip())
    return {k: (v or "").strip() for k, v in m.groupdict().items()} if m else None


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


# ---------------------------------------------------------------- conexão (OAuth do Melhor Envio)
# O token vale 30 dias e o refresh_token 45: a tarefa de fundo (main.py) renova antes de vencer.
# cotação + etiqueta (carrinho, compra com o saldo da Melhor Carteira, geração, impressão e rastreio).
# Mudou a lista? O lojista precisa clicar em "Conectar de novo" para o token ganhar as permissões novas.
SCOPE = "shipping-calculate cart-read cart-write shipping-checkout shipping-generate shipping-print shipping-tracking"
REFRESH_BEFORE = timedelta(days=7)


def authorize_url(settings: Any, state: str, redirect_uri: str) -> str:
    query = urllib.parse.urlencode({
        "client_id": settings.melhor_envio_client_id, "redirect_uri": redirect_uri,
        "response_type": "code", "state": state, "scope": SCOPE,
    })
    return f"{API[bool(settings.melhor_envio_sandbox)]}/oauth/authorize?{query}"


def _token_request(settings: Any, extra: dict[str, Any]) -> None:
    """Troca o code (ou o refresh_token) por um token novo e grava em settings (quem chama faz o commit)."""
    body = {"client_id": int(settings.melhor_envio_client_id), "client_secret": settings.melhor_envio_client_secret, **extra}
    req = urllib.request.Request(
        f"{API[bool(settings.melhor_envio_sandbox)]}/oauth/token", data=json.dumps(body).encode(), method="POST",
        headers={"Accept": "application/json", "Content-Type": "application/json",
                 "User-Agent": f"JC Moda ({settings.email or 'contato@jcmoda.com.br'})"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as res:
            data = json.loads(res.read())
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        log.warning("Melhor Envio recusou o token: %s", exc)
        raise ShippingUnavailable from exc
    if not data.get("access_token"):
        raise ShippingUnavailable
    settings.melhor_envio_token = data["access_token"]
    settings.melhor_envio_refresh_token = data.get("refresh_token") or settings.melhor_envio_refresh_token
    settings.melhor_envio_expires_at = datetime.now(UTC).replace(tzinfo=None) + timedelta(
        seconds=int(data.get("expires_in") or 2592000))
    _cache.clear()


def exchange_code(settings: Any, code: str, redirect_uri: str) -> None:
    _token_request(settings, {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri})


def refresh_if_needed(settings: Any) -> bool:
    """Renova o token quando faltam menos de 7 dias. True se renovou."""
    expires = settings.melhor_envio_expires_at
    if not settings.melhor_envio_refresh_token or (expires and expires - datetime.now(UTC).replace(tzinfo=None) > REFRESH_BEFORE):
        return False
    _token_request(settings, {"grant_type": "refresh_token", "refresh_token": settings.melhor_envio_refresh_token})
    return True


def shipping_options(settings: Any, dest_cep: str, items: list[tuple[int, float]]) -> list[ShippingOption]:
    """Opções reais de entrega para o carrinho (items = [(quantidade, preço unitário)])."""
    origin = parse_origin(settings.address)
    token = (getattr(settings, "melhor_envio_token", None) or "").strip()
    expires = getattr(settings, "melhor_envio_expires_at", None)
    if not origin or not token or (expires and expires < datetime.now(UTC).replace(tzinfo=None)):
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


# ---------------------------------------------------------------- etiqueta (botão "Gerar etiqueta" do pedido)
class LabelError(Exception):
    """Etiqueta não saiu; a mensagem já vem pronta para o lojista."""


# situações do envio no Melhor Envio, na ordem em que acontecem
_PAID = {"released", "generated", "posted", "delivered"}
_GENERATED = {"generated", "posted", "delivered"}


def _me_call(settings: Any, path: str, body: dict[str, Any]) -> Any:
    token = (getattr(settings, "melhor_envio_token", None) or "").strip()
    if not token:
        raise LabelError("O Melhor Envio não está conectado. Conecte em Configurações > Frete.")
    req = urllib.request.Request(
        f"{API[bool(getattr(settings, 'melhor_envio_sandbox', False))]}{path}",
        data=json.dumps(body).encode(), method="POST",
        headers={"Accept": "application/json", "Content-Type": "application/json",
                 "Authorization": f"Bearer {token}",
                 "User-Agent": f"JC Moda ({settings.email or 'contato@jcmoda.com.br'})"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as res:
            return json.loads(res.read() or b"{}")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode(errors="replace")[:2000]
        log.warning("Melhor Envio recusou %s: %s %s", path, exc.code, raw)
        if exc.code in (401, 403):
            raise LabelError("O Melhor Envio não deu permissão para gerar etiqueta. Em Configurações > Frete, "
                             "clique em \"Conectar de novo\" e autorize.") from exc
        raise LabelError(f"O Melhor Envio recusou: {_me_message(raw)}") from exc
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        log.warning("Melhor Envio não respondeu (%s): %s", path, exc)
        raise LabelError("O Melhor Envio não respondeu. Tente de novo em alguns minutos.") from exc


def _me_message(raw: str) -> str:
    """Tira a mensagem legível do erro do Melhor Envio ({"message": ..., "errors": {campo: [..]}})."""
    try:
        data = json.loads(raw)
    except ValueError:
        return raw[:200] or "erro desconhecido"
    parts = []
    errors = data.get("errors") or data.get("error") or {}
    if isinstance(errors, dict):
        for value in errors.values():
            parts.extend(str(v) for v in (value if isinstance(value, list) else [value]))
    if not parts and data.get("message"):
        parts.append(str(data["message"]))
    return "; ".join(parts)[:400] or "erro desconhecido"


def _digits(value: str | None) -> str:
    return re.sub(r"\D", "", value or "")


def label_payload(settings: Any, order: Any) -> dict[str, Any]:
    """Pedido no formato do carrinho do Melhor Envio (POST /api/v2/me/cart)."""
    store = parse_address(settings.address)
    if not store:
        raise LabelError("Preencha o endereço completo da loja (com CEP) em Configurações.")
    cnpj = _digits(settings.cnpj)
    if len(cnpj) != 14:
        raise LabelError("Preencha o CNPJ da loja em Configurações: ele vai como remetente na etiqueta.")
    qty = sum(i.quantity for i in order.items) or 1
    width, height, length, weight_g = (settings.package_width_cm, settings.package_height_cm,
                                       settings.package_length_cm, settings.package_weight_g)
    goods = money(max(order.subtotal - (order.discount or 0), 0.01))
    return {
        "service": order.shipping_service_id,
        "from": {
            "name": (settings.legal_name or settings.store_name)[:60], "phone": _digits(settings.whatsapp)[-11:],
            "email": settings.email or "", "company_document": cnpj,
            "state_register": "",  # envio sem nota (declaração de conteúdo): inscrição estadual vazia
            "address": store["street"], "number": store["number"], "complement": store["complement"],
            "district": store["district"], "city": store["city"], "state_abbr": store["state"],
            "country_id": "BR", "postal_code": _digits(store["cep"]),
        },
        "to": {
            "name": order.customer_name[:60], "phone": _digits(order.phone)[-11:], "email": order.email or "",
            "address": order.street or "", "number": order.number or "s/n", "complement": order.complement or "",
            "district": order.district or "", "city": order.city or "", "state_abbr": order.state or "",
            "country_id": "BR", "postal_code": _digits(order.cep),
        },
        # vai na declaração de conteúdo: precisa estar completo (nome, quantidade, valor de cada item)
        "products": [{"name": f"{i.name} {i.detail}".strip()[:100], "quantity": i.quantity,
                      "unitary_value": money(i.unit_price)} for i in order.items],
        # shortcut: uma caixa só, com as peças empilhadas (altura x quantidade); se a loja usar
        # caixas de tamanhos diferentes, trocar por uma escolha de caixa no pedido
        "volumes": [{"width": width, "height": height * qty, "length": length,
                     "weight": round(weight_g * qty / 1000, 3)}],
        "options": {"insurance_value": goods, "receipt": False, "own_hand": False, "reverse": False,
                    "non_commercial": True, "platform": "JC Moda", "tags": [{"tag": order.code}]},
    }


def buy_label(settings: Any, order: Any) -> None:
    """Compra e gera a etiqueta do pedido (quem chama faz o commit, inclusive se der erro no meio).

    Pode ser chamada de novo depois de um erro: continua do passo em que parou, sem comprar duas vezes.
    """
    if str(getattr(order.delivery_method, "value", order.delivery_method)) != "entrega":
        raise LabelError("Pedido de retirada na loja não tem etiqueta.")
    if not order.shipping_service_id:
        raise LabelError("Este pedido é de antes da etiqueta automática e não guardou o frete escolhido. "
                         "Gere a etiqueta direto no site do Melhor Envio.")
    status = ""
    if order.me_shipment_id:
        status = label_status(settings, order)
    else:
        created = _me_call(settings, "/api/v2/me/cart", label_payload(settings, order))
        if not created.get("id"):
            raise LabelError("O Melhor Envio não devolveu o envio criado. Tente de novo.")
        order.me_shipment_id = str(created["id"])
    ids = {"orders": [order.me_shipment_id]}
    if status not in _PAID:
        _me_call(settings, "/api/v2/me/shipment/checkout", ids)  # paga com o saldo da Melhor Carteira
    if status not in _GENERATED:
        _me_call(settings, "/api/v2/me/shipment/generate", ids)
    label_status(settings, order)  # já traz o código de rastreio, quando a transportadora libera


def label_status(settings: Any, order: Any) -> str:
    """Situação do envio no Melhor Envio; guarda o código de rastreio no pedido quando houver."""
    info = (_me_call(settings, "/api/v2/me/shipment/tracking", {"orders": [order.me_shipment_id]}) or {})
    info = info.get(order.me_shipment_id) or {}
    if info.get("tracking"):
        order.tracking_code = str(info["tracking"])[:40]
    return str(info.get("status") or "")


def label_print_url(settings: Any, order: Any) -> str:
    """Link do PDF da etiqueta (abre logado na conta do Melhor Envio da loja)."""
    data = _me_call(settings, "/api/v2/me/shipment/print", {"mode": "private", "orders": [order.me_shipment_id]})
    if not data.get("url"):
        raise LabelError("O Melhor Envio não devolveu o link da etiqueta. Tente de novo.")
    return str(data["url"])
