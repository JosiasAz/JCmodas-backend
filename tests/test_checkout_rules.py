"""Regras do checkout que a auditoria de segurança (nov/2026) pediu para travar no servidor.

Roda sem pytest:  python -m tests.test_checkout_rules   (de dentro da pasta backend)
Usa um banco SQLite em memória: não toca no jcmoda.db nem no Neon.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import Product, ProductVariant, StoreSettings
from app.schemas.order import CartLineIn, QuoteIn
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
    # sem CEP completo ainda vale o que foi digitado (cotação antes do CEP)
    assert classify(MANAUS, None, "Manaus", "AM") == "local"


def _db():
    engine = create_engine("sqlite://")
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
    split = QuoteIn(items=[CartLineIn(product_id=pid, variant_id=vid, quantity=2)] * 5)
    assert build_quote(db, split).quote.can_checkout is False
    ok = QuoteIn(items=[CartLineIn(product_id=pid, variant_id=vid, quantity=2)])
    assert build_quote(db, ok).quote.can_checkout is True


def test_retirada_desligada_e_recusada():
    db, pid, vid = _db()
    item = [CartLineIn(product_id=pid, variant_id=vid, quantity=1)]
    assert build_quote(db, QuoteIn(items=item, delivery_method="retirada")).quote.can_checkout is False
    db.get(StoreSettings, 1).pickup_enabled = True
    db.commit()
    assert build_quote(db, QuoteIn(items=item, delivery_method="retirada")).quote.can_checkout is True


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
