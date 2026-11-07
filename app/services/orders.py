import hashlib
import hmac
import re
import secrets
import string
import time
from collections import Counter
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import case, func, or_, select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Coupon, Order, OrderItem, OrderStatus, Product, ProductVariant
from app.schemas.order import OrderIn
from app.services.audit import record
from app.services.pricing import build_quote, get_settings

_ALPHABET = string.ascii_uppercase + string.digits
MAX_OPEN_ORDERS_PER_PHONE = 3


def _digits(phone: str | None) -> str:
    return re.sub(r"\D", "", phone or "")


def _utcnow() -> datetime:
    # created_at é gravado pelo banco em UTC, sem fuso
    return datetime.now(UTC).replace(tzinfo=None)


def _new_code(db: Session) -> str:
    while True:
        code = "JC" + "".join(secrets.choice(_ALPHABET) for _ in range(6))
        if not db.scalar(select(Order.id).where(Order.code == code)):
            return code


def client_ref(ip: str) -> str:
    """Identifica o visitante sem guardar o IP: HMAC com a chave secreta da API."""
    return hmac.new(settings.secret_key.encode(), ip.encode(), hashlib.sha256).hexdigest()[:16]


def create_order(db: Session, data: OrderIn, ref: str = "") -> Order:
    if data.website:
        # honeypot preenchido: robô. Resposta genérica para não ensinar o truque.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Não foi possível concluir o pedido. Tente novamente.")

    # o telefone é digitado pelo cliente (dá para trocar a cada pedido); o visitante (IP) não
    # shortcut: contar e inserir não é atômico; pedidos simultâneos do mesmo IP podem passar de 3
    # (o limite de 5 pedidos/10 min por IP segura o resto)
    if ref and db.scalar(
        select(func.count()).where(Order.status == OrderStatus.NEW, Order.client_ref == ref)
    ) >= MAX_OPEN_ORDERS_PER_PHONE:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Você já tem pedidos aguardando pagamento. Conclua-os ou fale com a loja pelo WhatsApp.",
        )

    # um mesmo telefone não segura estoque com vários pedidos sem pagar
    phone = _digits(data.phone)[-8:]
    open_orders = db.scalars(select(Order.phone).where(Order.status == OrderStatus.NEW)).all()
    if sum(1 for p in open_orders if _digits(p).endswith(phone)) >= MAX_OPEN_ORDERS_PER_PHONE:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Você já tem pedidos aguardando pagamento. Conclua-os ou fale com a loja pelo WhatsApp.",
        )

    result = build_quote(db, data)
    quote = result.quote
    if not quote.lines:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Seu carrinho está vazio")
    if not quote.can_checkout:
        problem = next((line.message for line in quote.lines if line.message), None)
        problem = problem or (quote.shipping_note if quote.shipping_pending else "Revise seu carrinho")
        raise HTTPException(status.HTTP_409_CONFLICT, problem)

    order = Order(
        code=_new_code(db),
        **data.model_dump(exclude={"items", "combos", "coupon_code", "installments", "website"}),
        installments=min(data.installments, quote.max_installments) if data.payment_method == "cartao" else 1,
        subtotal=quote.subtotal,
        discount=quote.discount_total,
        shipping=quote.shipping,
        total=quote.total,
        coupon_code=quote.coupon_code,
        client_ref=ref,
    )

    # baixa de estoque atômica: o UPDATE só acontece se ainda houver saldo. Assim, dois clientes
    # comprando a última peça ao mesmo tempo não conseguem os dois finalizar.
    needed: Counter[int] = Counter()
    for line in result.lines:
        for v in [line.variant] if line.variant else line.combo_variants:
            needed[v.id] += line.quote.quantity
            v.product.sold_count += line.quote.quantity
    for variant_id, qty in needed.items():
        done = db.execute(
            update(ProductVariant)
            .where(ProductVariant.id == variant_id, ProductVariant.stock >= qty)
            .values(stock=ProductVariant.stock - qty)
        ).rowcount
        if not done:
            db.rollback()
            raise HTTPException(status.HTTP_409_CONFLICT, "Uma das peças acabou de esgotar. Revise seu carrinho.")

    for line in result.lines:
        q = line.quote
        order.items.append(OrderItem(
            product_id=line.product.id if line.product else None,
            variant_id=line.variant.id if line.variant else None,
            combo_id=line.combo.id if line.combo else None,
            combo_variant_ids=",".join(str(v.id) for v in line.combo_variants),
            name=q.name,
            detail=q.detail,
            image=q.image,
            quantity=q.quantity,
            unit_price=q.unit_price,
            total=q.total,
        ))

    if result.coupon:
        # mesmo cuidado com o limite de usos do cupom
        done = db.execute(
            update(Coupon)
            .where(Coupon.id == result.coupon.id,
                   or_(Coupon.max_uses.is_(None), Coupon.used_count < Coupon.max_uses))
            .values(used_count=Coupon.used_count + 1)
        ).rowcount
        if not done:
            db.rollback()
            raise HTTPException(status.HTTP_409_CONFLICT, "Este cupom acabou de atingir o limite de usos.")

    db.add(order)
    db.commit()
    db.refresh(order)
    return order


def change_status(db: Session, order: Order, new_status: OrderStatus) -> Order:
    if order.status == new_status:
        return order
    # a troca de status é "reivindicada" no banco (como na expiração): se outro pedido ao mesmo tempo
    # já cancelou, este não muda nada e o estoque não volta duas vezes
    changed = db.execute(
        update(Order).where(Order.id == order.id, Order.status != OrderStatus.CANCELED)
        .values(status=new_status)
    ).rowcount
    if not changed:
        db.rollback()
        db.refresh(order)
        if new_status == OrderStatus.CANCELED:
            return order  # já estava cancelado: nada a fazer
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Pedido cancelado não pode ser reaberto")
    if new_status == OrderStatus.CANCELED:
        _return_stock(db, order)
    db.commit()
    db.refresh(order)
    return order


def _return_stock(db: Session, order: Order) -> None:
    """Devolve ao estoque as peças de um pedido cancelado.

    UPDATE relativo (stock = stock + qtd) no banco: não sobrescreve uma venda feita no mesmo instante.
    """
    for item in order.items:
        variant_ids = [item.variant_id] if item.variant_id else _combo_variant_ids(item) if item.combo_id else []
        for variant_id in variant_ids:
            product_id = db.scalar(
                update(ProductVariant).where(ProductVariant.id == variant_id)
                .values(stock=ProductVariant.stock + item.quantity).returning(ProductVariant.product_id)
            )
            if product_id is not None:
                db.execute(
                    update(Product).where(Product.id == product_id)
                    .values(sold_count=case((Product.sold_count > item.quantity, Product.sold_count - item.quantity), else_=0))
                )


def _combo_variant_ids(item: OrderItem) -> list[int]:
    return [int(v) for v in (item.combo_variant_ids or "").split(",") if v]


def expire_pending_orders(db: Session) -> int:
    """Cancela pedidos "novo" não pagos depois do prazo configurado e devolve o estoque."""
    hours = get_settings(db).order_hold_hours
    if not hours:
        return 0
    limit = _utcnow() - timedelta(hours=hours)
    stale_ids = db.scalars(
        select(Order.id).where(Order.status == OrderStatus.NEW, Order.created_at < limit)
    ).all()
    expired = 0
    for order_id in stale_ids:
        # tarefa de fundo, painel e loja podem rodar isto ao mesmo tempo: só quem conseguir trocar o status
        # de "novo" para "cancelado" devolve o estoque (nunca duas vezes)
        claimed = db.execute(
            update(Order).where(Order.id == order_id, Order.status == OrderStatus.NEW)
            .values(status=OrderStatus.CANCELED)
        ).rowcount
        if not claimed:
            db.rollback()
            continue
        order = db.get(Order, order_id)
        _return_stock(db, order)
        db.commit()
        record("expirou", user_email="sistema", entity="orders", entity_id=order.id,
               summary=f"{order.code}: não pago em {hours} h, estoque devolvido")
        expired += 1
    return expired


_last_expire = 0.0
EXPIRE_THROTTLE_SECONDS = 5 * 60


def expire_if_due(db: Session) -> None:
    """Versão "preguiçosa" para a vitrine: roda no máximo a cada 5 min por instância.

    Complementa a tarefa de fundo (main.py, a cada 10 min): o estoque de pedidos vencidos volta
    para a loja assim que ela é visitada.
    """
    global _last_expire
    now = time.monotonic()
    if now - _last_expire < EXPIRE_THROTTLE_SECONDS:
        return
    _last_expire = now
    expire_pending_orders(db)


ANONYMOUS = "Cliente anonimizado"


def anonymize_orders(db: Session, months: int) -> int:
    """LGPD: apaga os dados pessoais de pedidos antigos já encerrados, mantendo valores e produtos."""
    limit = _utcnow() - timedelta(days=30 * months)
    orders = db.scalars(
        select(Order).where(
            Order.created_at < limit,
            Order.status.in_([OrderStatus.DELIVERED, OrderStatus.CANCELED]),
            Order.customer_name != ANONYMOUS,
        )
    ).all()
    for o in orders:
        o.customer_name, o.phone, o.email, o.notes, o.client_ref = ANONYMOUS, "", None, "", ""
        o.cep = o.street = o.number = o.complement = o.district = o.city = o.state = None
    db.commit()
    return len(orders)
