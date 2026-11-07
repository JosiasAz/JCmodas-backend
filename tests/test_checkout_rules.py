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
from app.services.shipping import Origin, classify

MANAUS = Origin(city="Manaus", state="AM", cep="69085-000")


def test_frete_segue_o_cep():
    # cliente de SP digitando Manaus/AM não ganha frete local
    assert classify(MANAUS, "01001-000", "Manaus", "AM") == "other"
    # cliente do interior do AM digitando "Manaus" não ganha frete local
    assert classify(MANAUS, "69400-000", "Manaus", "AM") == "state"
    # cliente de Manaus continua com frete local
    assert classify(MANAUS, "69010-000", "Manaus", "AM") == "local"
    # CEP curto, incompleto ou fora das faixas não deixa o texto digitado decidir
    assert classify(MANAUS, None, "Manaus", "AM") is None
    assert classify(MANAUS, "1234", "Manaus", "AM") is None
    assert classify(MANAUS, "6915000", "Manaus", "AM") is None
    assert classify(MANAUS, "00000-000", "X", "AM") == "other"


def _db():
    # StaticPool: as duas sessões dos testes de concorrência enxergam o mesmo banco em memória
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = Session(engine)
    db.add(StoreSettings(id=1, address="Rua A, 1 - Centro, Manaus/AM - CEP 69085-000",
                         shipping_fee=10, shipping_state_fee=20, shipping_other_fee=40,
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


def test_entrega_sem_cep_valido_nao_fecha_pedido():
    db, pid, vid = _db()
    item = [CartLineIn(product_id=pid, variant_id=vid, quantity=1)]
    q = build_quote(db, QuoteIn(items=item, cep="1234", city="Manaus", state="AM")).quote
    assert q.can_checkout is False and q.shipping == 0
    q = build_quote(db, QuoteIn(items=item, cep="01001-000", city="Manaus", state="AM")).quote
    assert q.can_checkout is True and q.shipping == 40


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


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
