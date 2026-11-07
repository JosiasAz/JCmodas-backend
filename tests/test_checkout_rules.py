"""Regras do checkout que a auditoria de segurança (nov/2026) pediu para travar no servidor.

Roda sem pytest:  python -m tests.test_checkout_rules   (de dentro da pasta backend)
Usa um banco SQLite em memória: não toca no jcmoda.db nem no Neon.
"""
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import create_engine, update
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models import Combo, ComboItem, Order, OrderItem, OrderStatus, Product, ProductVariant, StoreSettings
from app.routers.admin_catalog import update_product
from app.routers.store import _active_combos
from app.schemas.catalog import ProductIn, VariantIn
from app.schemas.order import CartLineIn, OrderIn, QuoteIn
from app.services.orders import change_status, client_ref, create_order
from app.services.pricing import build_quote
from app.services import shipping

# resposta simulada do Melhor Envio (preço em texto, como a API real devolve); sem internet nos testes
CHAMADAS = []


def _melhor_envio_falso(token, sandbox, contact, body):
    CHAMADAS.append(body)
    if body["to"]["postal_code"] == "99999999":
        raise shipping.ShippingUnavailable
    return sorted([
        shipping.ShippingOption(id=2, name="SEDEX", company="Correios", price=38.5, days=3),
        shipping.ShippingOption(id=1, name="PAC", company="Correios", price=21.9, days=9),
    ], key=lambda o: o.price)


_fetch_real = shipping._fetch_options
shipping._fetch_options = _melhor_envio_falso


def test_le_resposta_do_melhor_envio():
    import io, json, urllib.request
    resposta = [
        {"id": 2, "name": "SEDEX", "custom_price": "38.50", "custom_delivery_time": 3, "company": {"name": "Correios"}},
        {"id": 1, "name": "PAC", "price": "21.90", "custom_price": "21.90", "custom_delivery_time": 9, "company": {"name": "Correios"}},
        {"id": 3, "name": ".Package", "error": "Serviço indisponível para o trecho.", "company": {"name": "Jadlog"}},
    ]
    enviado = {}

    class Resp(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def urlopen_falso(req, timeout):
        enviado.update(url=req.full_url, headers=dict(req.header_items()), body=json.loads(req.data))
        return Resp(json.dumps(resposta).encode())

    original, urllib.request.urlopen = urllib.request.urlopen, urlopen_falso
    try:
        opcoes = _fetch_real("tok", False, "loja@x.com", {"to": {"postal_code": "01001000"}})
    finally:
        urllib.request.urlopen = original
    assert [(o.id, o.price, o.days) for o in opcoes] == [(1, 21.9, 9), (2, 38.5, 3)]  # Jadlog com erro some
    assert enviado["url"].endswith("/api/v2/me/shipment/calculate") and enviado["headers"]["Authorization"] == "Bearer tok"
    assert "loja@x.com" in enviado["headers"]["User-agent"]


def test_frete_real_cliente_escolhe_e_paga():
    db, pid, vid = _db()
    item = [CartLineIn(product_id=pid, variant_id=vid, quantity=1)]
    q = build_quote(db, QuoteIn(items=item, cep="01001-000")).quote
    assert [o.id for o in q.shipping_options] == [1, 2] and q.shipping == 21.9 and q.can_checkout  # mais barato
    q = build_quote(db, QuoteIn(items=item, cep="01001-000", shipping_service=2)).quote
    assert q.shipping == 38.5 and "SEDEX" in q.shipping_note and q.total == 138.5
    # serviço inventado pelo cliente não vale: cai no mais barato, preço sempre do servidor
    assert build_quote(db, QuoteIn(items=item, cep="01001-000", shipping_service=999)).quote.shipping == 21.9
    assert CHAMADAS[-1]["products"][0]["insurance_value"] == 100 and CHAMADAS[-1]["from"]["postal_code"] == "69085000"


def test_frete_gratis_so_na_opcao_mais_barata():
    db, pid, vid = _db()
    db.get(StoreSettings, 1).free_shipping_min = 50
    db.commit()
    item = [CartLineIn(product_id=pid, variant_id=vid, quantity=1)]
    q = build_quote(db, QuoteIn(items=item, cep="01001-000")).quote
    assert q.shipping == 0 and q.shipping_options[0].free and q.free_shipping_missing == 0
    assert build_quote(db, QuoteIn(items=item, cep="01001-000", shipping_service=2)).quote.shipping == 38.5


def test_sem_configuracao_ou_erro_nao_vira_frete_gratis():
    db, pid, vid = _db()
    item = [CartLineIn(product_id=pid, variant_id=vid, quantity=1)]
    q = build_quote(db, QuoteIn(items=item, cep="99999-999")).quote  # Melhor Envio fora do ar
    assert q.can_checkout is False and q.shipping_pending
    assert build_quote(db, QuoteIn(items=item, cep="1234")).quote.can_checkout is False  # CEP incompleto
    db.get(StoreSettings, 1).melhor_envio_token = None  # loja sem token (como ficou após perder o banco)
    db.commit()
    q = build_quote(db, QuoteIn(items=item, cep="01001-000")).quote
    assert q.can_checkout is False and q.shipping == 0 and q.shipping_pending


def _db():
    # StaticPool: as duas sessões dos testes de concorrência enxergam o mesmo banco em memória
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = Session(engine)
    db.add(StoreSettings(id=1, address="Rua A, 1 - Centro, Manaus/AM - CEP 69085-000",
                         melhor_envio_token="token-de-teste",
                         max_qty_per_item=2, pickup_enabled=False))
    product = Product(name="Camisa", slug="camisa", price=100)
    db.add(product)
    db.flush()
    variant = ProductVariant(product_id=product.id, size="M", stock=10)
    db.add(variant)
    db.commit()
    return db, product.id, variant.id


def test_limite_por_item_soma_linhas_repetidas():
    db, pid, vid = _db()
    split = QuoteIn(items=[CartLineIn(product_id=pid, variant_id=vid, quantity=2)] * 5, cep="69010-000")
    assert build_quote(db, split).quote.can_checkout is False
    ok = QuoteIn(items=[CartLineIn(product_id=pid, variant_id=vid, quantity=2)], cep="69010-000")
    assert build_quote(db, ok).quote.can_checkout is True


def test_retirada_desligada_e_recusada():
    db, pid, vid = _db()
    item = [CartLineIn(product_id=pid, variant_id=vid, quantity=1)]
    assert build_quote(db, QuoteIn(items=item, delivery_method="retirada")).quote.can_checkout is False
    db.get(StoreSettings, 1).pickup_enabled = True
    db.commit()
    assert build_quote(db, QuoteIn(items=item, delivery_method="retirada")).quote.can_checkout is True


def _pedido(db, vid, qty=2):
    order = Order(code="JCTESTE1", customer_name="Ana", phone="92999990000", delivery_method="retirada",
                  payment_method="pix", subtotal=1, total=1, items=[])
    order.items.append(OrderItem(variant_id=vid, name="Camisa", quantity=qty, unit_price=1, total=1))
    db.add(order)
    db.execute(update(ProductVariant).where(ProductVariant.id == vid).values(stock=ProductVariant.stock - qty))
    db.commit()
    return order


def test_cancelar_duas_vezes_devolve_estoque_uma_vez():
    db, pid, vid = _db()
    order = _pedido(db, vid)
    other = Session(db.get_bind())  # outra requisição que carregou o mesmo pedido "novo"
    stale = other.get(Order, order.id)
    change_status(db, order, OrderStatus.CANCELED)
    change_status(other, stale, OrderStatus.CANCELED)
    db.expire_all()
    assert db.get(ProductVariant, vid).stock == 10
    try:
        change_status(db, db.get(Order, order.id), OrderStatus.NEW)
        raise AssertionError("reabriu pedido cancelado")
    except HTTPException:
        pass


def test_devolucao_nao_apaga_venda_simultanea():
    db, pid, vid = _db()
    order = _pedido(db, vid)  # estoque 8
    db.get(ProductVariant, vid)  # variação já carregada na sessão (como num pedido em andamento)
    other = Session(db.get_bind())
    other.execute(update(ProductVariant).where(ProductVariant.id == vid).values(stock=ProductVariant.stock - 3))
    other.commit()  # venda de 3 peças no meio do cancelamento: estoque 5
    change_status(db, order, OrderStatus.CANCELED)
    db.expire_all()
    assert db.get(ProductVariant, vid).stock == 7


def test_combo_com_peca_escondida_sai_da_vitrine():
    db, pid, vid = _db()
    combo = Combo(name="Kit", slug="kit", price=50, active=True)
    combo.items.append(ComboItem(product_id=pid, quantity=1))
    db.add(combo)
    db.commit()
    assert [c.slug for c in _active_combos(db)] == ["kit"]
    db.get(Product, pid).active = False
    db.commit()
    assert _active_combos(db) == []


def test_limite_de_pedidos_abertos_por_visitante():
    db, pid, vid = _db()
    db.get(StoreSettings, 1).pickup_enabled = True
    db.commit()
    ref = client_ref("203.0.113.7")
    for n in range(3):
        create_order(db, OrderIn(items=[CartLineIn(product_id=pid, variant_id=vid, quantity=1)],
                                 delivery_method="retirada", customer_name="Ana", phone=f"9299999000{n}"), ref)
    try:
        create_order(db, OrderIn(items=[CartLineIn(product_id=pid, variant_id=vid, quantity=1)],
                                 delivery_method="retirada", customer_name="Ana", phone="92988887777"), ref)
        raise AssertionError("4º pedido aberto do mesmo visitante passou")
    except HTTPException as e:
        assert e.status_code == 429
    assert client_ref("203.0.113.7") == ref and client_ref("203.0.113.8") != ref


def test_salvar_produto_nao_apaga_venda_feita_com_formulario_aberto():
    db, pid, vid = _db()  # estoque 10: o admin abre o formulário e vê 10
    other = Session(db.get_bind())
    other.execute(update(ProductVariant).where(ProductVariant.id == vid).values(stock=ProductVariant.stock - 3))
    other.commit()  # um cliente compra 3 enquanto o formulário está aberto: estoque 7
    data = ProductIn(name="Camisa", price=100, variants=[VariantIn(id=vid, size="M", stock=12, stock_before=10)])
    req = SimpleNamespace(state=SimpleNamespace())
    out = update_product(pid, data, db, None, req)  # admin repôs 2 peças (10 -> 12)
    assert out.variants[0].stock == 9  # 7 + 2: a venda não sumiu


def test_fotos_ficam_no_banco_e_voltam_para_o_disco():
    import tempfile
    from pathlib import Path

    from sqlalchemy.orm import sessionmaker

    from app.core.config import settings
    from app.models import StoredFile
    from app.services import storage

    db, _, _ = _db()
    storage.SessionLocal = sessionmaker(bind=db.get_bind())
    settings.upload_dir = tempfile.mkdtemp()
    url = storage.save_image(b"foto-jpg", ".jpg")
    name = url.rsplit("/", 1)[1]
    (Path(settings.upload_dir) / name).unlink()  # disco do servidor perdido
    assert storage.local_file(name).read_bytes() == b"foto-jpg"  # volta do banco
    antiga = "a" * 32 + ".png"
    (Path(settings.upload_dir) / antiga).write_bytes(b"foto-antiga")  # enviada antes desta mudança
    assert storage.import_disk_files() == 1
    assert db.get(StoredFile, antiga).data == b"foto-antiga"
    assert storage.local_file("../../.env") is None
    from app.routers.admin_catalog import list_uploads
    lista = {f["url"]: f["in_use"] for f in list_uploads(db, None)}
    assert lista == {url: False, "/static/uploads/" + antiga: False}
    from app.routers.admin_catalog import delete_upload
    delete_upload(antiga, db, None, SimpleNamespace(state=SimpleNamespace()))
    assert db.get(StoredFile, antiga) is None and not (Path(settings.upload_dir) / antiga).exists()
    assert storage.import_disk_files() == 0  # não volta para o banco no próximo início
    db.add(Product(name="Kit", slug="kit-foto", price=1, images=[url]))
    db.commit()
    try:
        delete_upload(name, db, None, SimpleNamespace(state=SimpleNamespace()))
        raise AssertionError("apagou foto em uso")
    except HTTPException as e:
        assert e.status_code == 409


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
