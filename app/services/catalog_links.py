"""Apagar produto, tamanho ou combo que já aparece em pedidos.

O item de pedido guarda uma cópia do nome, da foto, do tamanho e do preço. O vínculo com o produto só
importa enquanto o pedido está em andamento: se ele for cancelado, é por ali que as peças voltam ao
estoque. Com o pedido encerrado (cancelado ou entregue), o vínculo é solto e o produto pode ser apagado.
"""
from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import InstrumentedAttribute, Session

from app.models import Order, OrderItem, OrderStatus

CLOSED = (OrderStatus.CANCELED, OrderStatus.DELIVERED)


def release_from_orders(db: Session, column: InstrumentedAttribute, ids: list[int], what: str) -> None:
    """Solta `ids` dos pedidos encerrados; se algum pedido em andamento usa, recusa com o código dele."""
    if not ids:
        return
    open_codes = db.scalars(
        select(Order.code).join(OrderItem).where(column.in_(ids), Order.status.not_in(CLOSED)).distinct()
    ).all()
    if open_codes:
        codes = ", ".join(open_codes[:3]) + ("..." if len(open_codes) > 3 else "")
        raise HTTPException(
            400,
            f"{what} está no pedido em andamento {codes}. Conclua ou cancele o pedido antes de apagar.",
        )
    db.execute(update(OrderItem).where(column.in_(ids)).values({column.key: None}))
