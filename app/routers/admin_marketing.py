"""Painel: promoções, cupons, combos e anúncios (banners)."""
from datetime import datetime

from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.deps import DB, Admin
from app.models import Banner, Combo, ComboItem, Coupon, Product, Promotion
from app.schemas.marketing import (
    BannerIn,
    BannerOut,
    ComboIn,
    ComboOut,
    CouponIn,
    CouponOut,
    PromotionIn,
    PromotionOut,
)
from app.services.pricing import running_promotions, serialize_combo
from app.services.slug import unique_slug

router = APIRouter(prefix="/api/admin", tags=["Painel - Marketing"])


def _get(db, model, item_id: int):
    item = db.get(model, item_id)
    if not item:
        raise HTTPException(404, "Registro não encontrado")
    return item


def _apply(item, data) -> None:
    for key, value in data.model_dump().items():
        setattr(item, key, value)


def _delete(db, model, item_id: int) -> None:
    db.delete(_get(db, model, item_id))
    db.commit()


# ---------------------------------------------------------------- promoções


def _promotion_out(promo: Promotion) -> PromotionOut:
    return PromotionOut.model_validate(promo).model_copy(update={"running": promo.is_running(datetime.now())})


@router.get("/promotions", response_model=list[PromotionOut])
def list_promotions(db: DB, _: Admin):
    return [_promotion_out(p) for p in db.scalars(select(Promotion).order_by(Promotion.id.desc()))]


@router.post("/promotions", response_model=PromotionOut, status_code=201)
def create_promotion(data: PromotionIn, db: DB, _: Admin):
    promo = Promotion(**data.model_dump())
    db.add(promo)
    db.commit()
    return _promotion_out(promo)


@router.put("/promotions/{promo_id}", response_model=PromotionOut)
def update_promotion(promo_id: int, data: PromotionIn, db: DB, _: Admin):
    promo = _get(db, Promotion, promo_id)
    _apply(promo, data)
    db.commit()
    return _promotion_out(promo)


@router.delete("/promotions/{promo_id}", status_code=204)
def delete_promotion(promo_id: int, db: DB, _: Admin):
    _delete(db, Promotion, promo_id)


# ---------------------------------------------------------------- cupons


@router.get("/coupons", response_model=list[CouponOut])
def list_coupons(db: DB, _: Admin):
    return db.scalars(select(Coupon).order_by(Coupon.id.desc())).all()


@router.post("/coupons", response_model=CouponOut, status_code=201)
def create_coupon(data: CouponIn, db: DB, _: Admin):
    code = data.code.strip().upper()
    if db.scalar(select(Coupon.id).where(Coupon.code == code)):
        raise HTTPException(400, "Já existe um cupom com esse código")
    coupon = Coupon(**data.model_dump(exclude={"code"}), code=code)
    db.add(coupon)
    db.commit()
    return coupon


@router.put("/coupons/{coupon_id}", response_model=CouponOut)
def update_coupon(coupon_id: int, data: CouponIn, db: DB, _: Admin):
    coupon = _get(db, Coupon, coupon_id)
    code = data.code.strip().upper()
    if db.scalar(select(Coupon.id).where(Coupon.code == code, Coupon.id != coupon_id)):
        raise HTTPException(400, "Já existe um cupom com esse código")
    _apply(coupon, data)
    coupon.code = code
    db.commit()
    return coupon


@router.delete("/coupons/{coupon_id}", status_code=204)
def delete_coupon(coupon_id: int, db: DB, _: Admin):
    _delete(db, Coupon, coupon_id)


# ---------------------------------------------------------------- combos


def _load_combo(db, combo_id: int) -> Combo:
    combo = db.scalar(
        select(Combo).where(Combo.id == combo_id)
        .options(selectinload(Combo.items).selectinload(ComboItem.product).selectinload(Product.variants))
    )
    if not combo:
        raise HTTPException(404, "Combo não encontrado")
    return combo


def _combo_items(db, data: ComboIn) -> list[ComboItem]:
    ids = {i.product_id for i in data.items}
    found = set(db.scalars(select(Product.id).where(Product.id.in_(ids))))
    if found != ids:
        raise HTTPException(400, "Um dos produtos do combo não existe mais")
    return [ComboItem(product_id=i.product_id, quantity=i.quantity) for i in data.items]


@router.get("/combos", response_model=list[ComboOut])
def list_combos(db: DB, _: Admin):
    promos = running_promotions(db)
    combos = db.scalars(
        select(Combo).order_by(Combo.id.desc())
        .options(selectinload(Combo.items).selectinload(ComboItem.product).selectinload(Product.variants))
    )
    return [serialize_combo(c, promos) for c in combos]


@router.post("/combos", response_model=ComboOut, status_code=201)
def create_combo(data: ComboIn, db: DB, _: Admin):
    combo = Combo(
        **data.model_dump(exclude={"items"}),
        slug=unique_slug(db, Combo, data.name),
        items=_combo_items(db, data),
    )
    db.add(combo)
    db.commit()
    return serialize_combo(_load_combo(db, combo.id), running_promotions(db))


@router.put("/combos/{combo_id}", response_model=ComboOut)
def update_combo(combo_id: int, data: ComboIn, db: DB, _: Admin):
    combo = _load_combo(db, combo_id)
    for key, value in data.model_dump(exclude={"items"}).items():
        setattr(combo, key, value)
    combo.slug = unique_slug(db, Combo, data.name, combo.id)
    combo.items = _combo_items(db, data)
    db.commit()
    db.expire_all()
    return serialize_combo(_load_combo(db, combo_id), running_promotions(db))


@router.delete("/combos/{combo_id}", status_code=204)
def delete_combo(combo_id: int, db: DB, _: Admin):
    _delete(db, Combo, combo_id)


# ---------------------------------------------------------------- anúncios


@router.get("/banners", response_model=list[BannerOut])
def list_banners(db: DB, _: Admin):
    return db.scalars(select(Banner).order_by(Banner.placement, Banner.sort, Banner.id)).all()


@router.post("/banners", response_model=BannerOut, status_code=201)
def create_banner(data: BannerIn, db: DB, _: Admin):
    banner = Banner(**data.model_dump())
    db.add(banner)
    db.commit()
    return banner


@router.put("/banners/{banner_id}", response_model=BannerOut)
def update_banner(banner_id: int, data: BannerIn, db: DB, _: Admin):
    banner = _get(db, Banner, banner_id)
    _apply(banner, data)
    db.commit()
    return banner


@router.delete("/banners/{banner_id}", status_code=204)
def delete_banner(banner_id: int, db: DB, _: Admin):
    _delete(db, Banner, banner_id)
