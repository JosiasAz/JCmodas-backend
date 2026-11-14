"""Etiqueta automática do Melhor Envio (sem internet: o Melhor Envio é simulado).

Roda sem pytest:  python -m tests.test_label   (de dentro da pasta backend)
"""
from types import SimpleNamespace

from app.services import shipping
from app.services.shipping import LabelError, buy_label, label_payload, parse_address

SETTINGS = SimpleNamespace(
    address="Rua Cipó Alho, 441 (Loja 2) - Jorge Teixeira, Manaus/AM - CEP 69088-147",
    cnpj="12.345.678/0001-90", legal_name="JC Moda Masculina LTDA", store_name="JC Moda", whatsapp="+55 (92) 99999-1088",
    email="loja@exemplo.com", package_width_cm=20, package_height_cm=5, package_length_cm=28, package_weight_g=400,
    melhor_envio_token="tok", melhor_envio_sandbox=True,
)


def _order(**kw):
    item = SimpleNamespace(name="Camiseta Básica", detail="Tam. M · Preto", quantity=2, unit_price=49.9)
    base = dict(code="JC1234", delivery_method="entrega", shipping_service_id=1, me_shipment_id=None, tracking_code=None,
                customer_name="Maria Silva", phone="(11) 98888-7777", email=None, street="Rua A", number="10",
                complement=None, district="Centro", city="São Paulo", state="SP", cep="01001-000",
                subtotal=99.8, discount=0, items=[item])
    return SimpleNamespace(**{**base, **kw})


class FakeME:
    """Guarda as chamadas e simula a situação do envio lá no Melhor Envio."""

    def __init__(self, fail_checkout=False):
        self.calls, self.status, self.fail_checkout = [], "", fail_checkout

    def __call__(self, settings, path, body):
        self.calls.append(path.rsplit("/", 1)[-1])
        if path.endswith("/cart"):
            self.status = "pending"
            return {"id": "a" * 36}
        if path.endswith("/checkout"):
            if self.fail_checkout:
                raise LabelError("O Melhor Envio recusou: saldo insuficiente")
            self.status = "released"
            return {}
        if path.endswith("/generate"):
            self.status = "generated"
            return {}
        if path.endswith("/tracking"):
            return {"a" * 36: {"status": self.status, "tracking": "ME123BR" if self.status == "generated" else None}}
        return {}


def test_address_parts():
    assert parse_address(SETTINGS.address) == {
        "street": "Rua Cipó Alho", "number": "441", "complement": "Loja 2", "district": "Jorge Teixeira",
        "city": "Manaus", "state": "AM", "cep": "69088-147"}
    assert parse_address("endereço escrito à mão") is None


def test_payload():
    body = label_payload(SETTINGS, _order())
    assert body["service"] == 1
    assert body["from"]["company_document"] == "12345678000190" and body["from"]["postal_code"] == "69088147"
    assert body["to"]["postal_code"] == "01001000" and body["to"]["phone"] == "11988887777"
    assert body["products"] == [{"name": "Camiseta Básica Tam. M · Preto", "quantity": 2, "unitary_value": 49.9}]
    assert body["volumes"] == [{"width": 20, "height": 10, "length": 28, "weight": 0.8}]
    assert body["options"]["non_commercial"] is True and body["options"]["insurance_value"] == 99.8


def test_buy_and_never_twice():
    fake = FakeME()
    shipping._me_call = fake
    order = _order()
    buy_label(SETTINGS, order)
    assert fake.calls == ["cart", "checkout", "generate", "tracking"]
    assert order.me_shipment_id == "a" * 36 and order.tracking_code == "ME123BR"
    fake.calls.clear()
    buy_label(SETTINGS, order)  # reimprimir: só consulta, não compra de novo
    assert fake.calls == ["tracking", "tracking"]


def test_resume_after_no_balance():
    fake = FakeME(fail_checkout=True)
    shipping._me_call = fake
    order = _order()
    try:
        buy_label(SETTINGS, order)
        raise AssertionError("deveria falhar sem saldo")
    except LabelError as exc:
        assert "saldo" in str(exc)
    assert order.me_shipment_id  # o envio criado fica guardado
    fake.fail_checkout, fake.calls = False, []
    buy_label(SETTINGS, order)  # com saldo: continua do pagamento, sem criar outro envio
    assert fake.calls == ["tracking", "checkout", "generate", "tracking"]


def test_refusals():
    for order, words in ((_order(delivery_method="retirada"), "retirada"), (_order(shipping_service_id=None), "antes")):
        try:
            buy_label(SETTINGS, order)
            raise AssertionError("deveria recusar")
        except LabelError as exc:
            assert words in str(exc)
    try:
        label_payload(SimpleNamespace(**{**SETTINGS.__dict__, "cnpj": ""}), _order())
        raise AssertionError("deveria pedir o CNPJ")
    except LabelError as exc:
        assert "CNPJ" in str(exc)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
