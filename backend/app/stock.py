"""Materials used from stock (the van or the yard): pick a product, and it's costed at the price-file rate with the margin on top.

A product's cost is its cheapest current price across the supplier price files (or the price book when no supplier
lists it). The sell price is cost plus the margin for its product group, or the default stock margin.
"""
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from . import ops
from .models import PriceBookVersion, PriceItem, Supplier, SupplierPrice


def markup_for(db: Session, group: str) -> float:
    cfg = ops.settings(db)
    by_group = {k.lower(): v for k, v in (cfg.get("markup_by_group") or {}).items()}
    if group and group.lower() in by_group:
        return float(by_group[group.lower()])
    return float(cfg["stock_markup_pct"])


def search(db: Session, q: str, limit: int = 40) -> list[dict]:
    """Products matching words in the description, or a code, one row per product at its cheapest price."""
    words = [w for w in q.lower().split() if w]
    if not words:
        return []
    stmt = select(SupplierPrice).where(SupplierPrice.current.is_(True))
    for w in words:
        stmt = stmt.where(or_(SupplierPrice.description.ilike(f"%{w}%"), SupplierPrice.code.ilike(f"%{w}%"),
                              SupplierPrice.mfr_code.ilike(f"%{w}%"), SupplierPrice.brand.ilike(f"%{w}%")))
    best: dict[str, SupplierPrice] = {}
    for p in db.scalars(stmt.limit(500)):
        key = p.product_key or f"S{p.supplier_id}:{p.code}"
        if key not in best or p.price < best[key].price:
            best[key] = p
    sups = {s.id: s.name for s in db.scalars(select(Supplier))}
    out = [{"code": p.code, "supplier_id": p.supplier_id, "supplier": sups.get(p.supplier_id, ""), "description": p.description, "brand": p.brand,
            "group": p.group, "unit": p.unit, "cost": p.price, "source": "price file"} for p in best.values()]
    if len(out) < limit:
        version = db.scalar(select(PriceBookVersion).order_by(PriceBookVersion.id.desc()))
        if version is not None:
            pstmt = select(PriceItem).where(PriceItem.version_id == version.id)
            for w in words:
                pstmt = pstmt.where(or_(PriceItem.description.ilike(f"%{w}%"), PriceItem.code.ilike(f"%{w}%")))
            seen = {o["code"] for o in out}
            for it in db.scalars(pstmt.limit(limit)):
                if it.code not in seen:
                    out.append({"code": it.code, "supplier_id": None, "supplier": it.supplier, "description": it.description, "brand": "",
                                "group": "", "unit": it.uom, "cost": it.cost, "source": "price book"})
    for o in out:
        m = markup_for(db, o["group"])
        o["markup_pct"] = m
        o["sell"] = round(o["cost"] * (1 + m / 100), 2)
    return sorted(out, key=lambda o: o["description"].lower())[:limit]


def price(db: Session, code: str, supplier_id: int | None = None) -> dict | None:
    """Cost, group and sell for one product code (a supplier code; the cheapest supplier unless one is named)."""
    p = None
    if supplier_id:
        p = db.scalar(select(SupplierPrice).where(SupplierPrice.supplier_id == supplier_id, SupplierPrice.code == code,
                                                  SupplierPrice.current.is_(True)))
    if p is None:
        p = db.scalar(select(SupplierPrice).where(SupplierPrice.code == code, SupplierPrice.current.is_(True)))
    if p is not None and p.product_key:
        cheaper = db.scalar(select(SupplierPrice).where(SupplierPrice.product_key == p.product_key, SupplierPrice.current.is_(True))
                            .order_by(SupplierPrice.price))
        if cheaper is not None and not supplier_id:
            p = cheaper
    if p is not None:
        cost, group, desc, unit = p.price, p.group, p.description, p.unit
    else:
        version = db.scalar(select(PriceBookVersion).order_by(PriceBookVersion.id.desc()))
        it = db.scalar(select(PriceItem).where(PriceItem.version_id == version.id, PriceItem.code == code)) if version else None
        if it is None:
            return None
        cost, group, desc, unit = it.cost, "", it.description, it.uom
    m = markup_for(db, group)
    return {"cost": cost, "group": group, "description": desc, "unit": unit, "markup_pct": m, "sell": round(cost * (1 + m / 100), 2)}
