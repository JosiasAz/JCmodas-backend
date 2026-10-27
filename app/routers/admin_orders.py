"""Painel: pedidos, resumo de vendas e configurações da loja."""
import math
from datetime import date, datetime, timedelta

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

from app.core.deps import DB, Admin
from app.models import Order, OrderItem, OrderStatus, Product, ProductVariant
from app.schemas.order import OrderOut, OrderPage, OrderStatusIn
from app.schemas.store import DashboardOut, SettingsIn, SettingsOut
from app.services.orders import anonymize_orders, change_status, expire_pending_orders
from app.services.pricing import get_settings

router = APIRouter(prefix="/api/admin", tags=["Painel - Vendas"])

LOW_STOCK = 3
# teto anual de faturamento do MEI (LC 123/2006, art. 18-A). Em out/2026 o aumento ainda não foi aprovado.
MEI_LIMIT = 81_000
# pedidos que contam como venda feita (o "novo" ainda não foi pago; o cancelado não conta)
SOLD = (OrderStatus.PAID, OrderStatus.PREPARING, OrderStatus.SHIPPED, OrderStatus.DELIVERED)


@router.get("/orders", response_model=OrderPage)
def list_orders(
    db: DB,
    _: Admin,
    status: OrderStatus | None = None,
    q: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    expire_pending_orders(db)  # garante que a lista não mostre pedidos que já venceram
    query = select(Order).options(selectinload(Order.items))
    if status:
        query = query.where(Order.status == status)
    if q:
        like = f"%{q.strip()}%"
        query = query.where(or_(Order.code.ilike(like), Order.customer_name.ilike(like), Order.phone.ilike(like)))
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    orders = db.scalars(query.order_by(Order.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return OrderPage(items=orders, total=total, page=page, pages=max(1, math.ceil(total / page_size)))


@router.get("/orders/{order_id}", response_model=OrderOut)
def get_order(order_id: int, db: DB, _: Admin):
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(404, "Pedido não encontrado")
    return order


@router.patch("/orders/{order_id}/status", response_model=OrderOut)
def update_status(order_id: int, data: OrderStatusIn, db: DB, _: Admin, request: Request):
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(404, "Pedido não encontrado")
    request.state.audit_summary = f"{order.code}: {order.status} → {data.status} (total R$ {order.total:.2f})"
    return change_status(db, order, data.status)


class AnonymizeIn(BaseModel):
    months: int = Field(ge=1, le=120)


@router.post("/orders/anonymize")
def anonymize(data: AnonymizeIn, db: DB, _: Admin, request: Request):
    """LGPD: apaga nome, telefone, e-mail e endereço de pedidos entregues/cancelados mais antigos."""
    count = anonymize_orders(db, data.months)
    request.state.audit_summary = f"{count} pedido(s) com mais de {data.months} meses anonimizados"
    return {"anonymized": count}


@router.get("/dashboard", response_model=DashboardOut)
def dashboard(db: DB, _: Admin, days: int = Query(30, ge=1, le=365)):
    expire_pending_orders(db)
    since = datetime.combine(date.today() - timedelta(days=days - 1), datetime.min.time())
    valid = (Order.status != OrderStatus.CANCELED, Order.created_at >= since)

    revenue, count = db.execute(select(func.coalesce(func.sum(Order.total), 0), func.count()).where(*valid)).one()

    by_day = dict(db.execute(
        select(func.date(Order.created_at), func.sum(Order.total)).where(*valid).group_by(func.date(Order.created_at))
    ).all())
    sales_by_day = []
    for i in range(min(days, 30) - 1, -1, -1):
        day = (date.today() - timedelta(days=i)).isoformat()
        sales_by_day.append({"date": day, "total": round(by_day.get(day, 0) or 0, 2)})

    top = db.execute(
        select(OrderItem.name, func.sum(OrderItem.quantity).label("qty"), func.sum(OrderItem.total))
        .join(Order).where(*valid)
        .group_by(OrderItem.name).order_by(func.sum(OrderItem.quantity).desc()).limit(5)
    ).all()

    low = db.execute(
        select(Product.id, Product.name, ProductVariant.size, ProductVariant.color, ProductVariant.stock)
        .join(ProductVariant).where(Product.active, ProductVariant.stock <= LOW_STOCK)
        .order_by(ProductVariant.stock).limit(10)
    ).all()

    statuses = dict(db.execute(select(Order.status, func.count()).group_by(Order.status)).all())
    year_start = datetime(date.today().year, 1, 1)
    year_revenue = db.scalar(
        select(func.coalesce(func.sum(Order.total), 0)).where(Order.status.in_(SOLD), Order.created_at >= year_start)
    )

    return DashboardOut(
        revenue=round(revenue, 2),
        year_revenue=round(year_revenue, 2),
        mei_limit=MEI_LIMIT,
        orders=count,
        average_ticket=round(revenue / count, 2) if count else 0,
        new_orders=statuses.get(OrderStatus.NEW, 0),
        products_active=db.scalar(select(func.count()).where(Product.active)),
        low_stock=[{"product_id": r[0], "name": r[1], "size": r[2], "color": r[3], "stock": r[4]} for r in low],
        top_products=[{"name": r[0], "quantity": r[1], "total": round(r[2], 2)} for r in top],
        sales_by_day=sales_by_day,
        orders_by_status={s.value: statuses.get(s, 0) for s in OrderStatus},
    )


@router.get("/settings", response_model=SettingsOut)
def read_settings(db: DB, _: Admin):
    return get_settings(db)


@router.put("/settings", response_model=SettingsOut)
def save_settings(data: SettingsIn, db: DB, _: Admin):
    settings = get_settings(db)
    for key, value in data.model_dump().items():
        setattr(settings, key, value)
    db.commit()
    return settings
