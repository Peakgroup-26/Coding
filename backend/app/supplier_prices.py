"""Supplier price files: load each supplier's monthly price list, keep the history, find the cheapest supplier.

Files come from anywhere: Reece maX (download the price file from maX), Tradelink, Samios, Middys, or any
supplier who emails a CSV / Excel list. Columns are found by their headings (and remembered per supplier
once someone corrects them). Prices that changed are counted up and down on each import, and old prices
stay so a product's price history can be shown.

Matching the same product across suppliers, best evidence first:
  1. someone said these codes are the same product (ProductMatch)
  2. the manufacturer's code (what's printed on the box) – most supplier files carry it
  3. the barcode (EAN / GTIN)
  4. nothing: the item is only compared within its own supplier
"""
import re
from collections import defaultdict
from datetime import date

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .models import PriceImport, ProductMatch, PurchaseOrder, Supplier, SupplierPrice
from .pricebook_import import _norm, _num

FIELDS = {
    "code": ["product code", "item code", "code", "part number", "part no", "sku", "stock code", "reece code", "product number",
             "item number", "item no"],
    "mfr_code": ["manufacturer code", "manufacturer part number", "mfr code", "mfr part no", "manufacturer item code", "supplier code",
                 "supplier part number", "vendor code", "brand code", "model number", "model"],
    "barcode": ["barcode", "ean", "gtin", "apn", "upc", "ean code"],
    "description": ["description", "product description", "item description", "name", "product name", "long description"],
    "brand": ["brand", "manufacturer", "make"],
    "group": ["product group", "group", "category", "product category", "range", "sub category", "family"],
    "unit": ["unit", "uom", "unit of measure", "pack", "sell unit"],
    "price": ["your price", "nett price", "net price", "trade price", "cost price", "account price", "buy price", "price ex gst",
              "unit price", "price", "cost", "nett"],
    "list_price": ["list price", "rrp", "retail price", "recommended retail price", "list"],
}


def detect_columns(headers: list[str], saved: dict | None = None) -> dict[str, str]:
    by_norm = {_norm(h): h for h in headers}
    out = {}
    for f, aliases in FIELDS.items():
        if saved and saved.get(f) in headers:
            out[f] = saved[f]
            continue
        for a in aliases:
            if _norm(a) in by_norm and by_norm[_norm(a)] not in out.values():
                out[f] = by_norm[_norm(a)]
                break
    return out


def norm_code(code: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (code or "").upper())


def product_key(mfr_code: str, barcode: str) -> str:
    if norm_code(mfr_code):
        return "M:" + norm_code(mfr_code)
    if re.fullmatch(r"\d{8,14}", (barcode or "").strip()):
        return "B:" + barcode.strip().lstrip("0")
    return ""


def import_prices(db: Session, supplier: Supplier, rows: list[dict], columns: dict[str, str], *, filename: str = "",
                  effective: date | None = None, source: str = "file", user_id: int | None = None) -> PriceImport:
    if "code" not in columns or "price" not in columns:
        raise ValueError("The file needs a product code column and a price column. Choose them and load it again.")
    effective = effective or date.today()
    imp = PriceImport(supplier_id=supplier.id, filename=filename, effective=effective, source=source, user_id=user_id)
    db.add(imp)
    db.flush()
    current = {p.code: p for p in db.scalars(select(SupplierPrice).where(SupplierPrice.supplier_id == supplier.id,
                                                                        SupplierPrice.current.is_(True)))}
    matches = {m.code: m.product_key for m in db.scalars(select(ProductMatch).where(ProductMatch.supplier_id == supplier.id))}
    seen = set()
    for r in rows:
        code = (r.get(columns["code"]) or "").strip()
        try:
            price = _num(r.get(columns["price"]) or "")
        except ValueError:
            price = None
        if not code or price is None or code in seen:
            continue
        seen.add(code)
        get = lambda f: (r.get(columns[f]) or "").strip() if f in columns else ""  # noqa: E731
        try:
            lp = _num(get("list_price")) if "list_price" in columns else None
        except ValueError:
            lp = None
        old = current.get(code)
        key = matches.get(code) or product_key(get("mfr_code"), get("barcode"))
        if old is not None:
            if abs(old.price - price) < 0.005 and old.description == (get("description") or old.description):
                old.product_key = key or old.product_key
                continue
            imp.price_up += price > old.price + 0.005
            imp.price_down += price < old.price - 0.005
            old.current = False
        else:
            imp.new_items += 1
        db.add(SupplierPrice(supplier_id=supplier.id, code=code, mfr_code=get("mfr_code"), barcode=get("barcode"),
                             description=get("description")[:500], brand=get("brand")[:100], group=get("group")[:100],
                             unit=get("unit")[:20] or "ea", price=price, list_price=lp, effective=effective, current=True,
                             import_id=imp.id, product_key=key))
    imp.rows = len(seen)
    supplier.price_format = columns
    db.flush()
    return imp


def best_price(db: Session, code: str) -> dict | None:
    """The cheapest current price for a code (a supplier code, or a manufacturer code / barcode shared across suppliers)."""
    p = db.scalar(select(SupplierPrice).where(SupplierPrice.current.is_(True), SupplierPrice.code == code))
    key = p.product_key if p else product_key(code, code)
    cands = list(db.scalars(select(SupplierPrice).where(SupplierPrice.current.is_(True), SupplierPrice.product_key == key))) if key else []
    if p and p not in cands:
        cands.append(p)
    if not cands:
        return None
    b = min(cands, key=lambda x: x.price)
    s = db.get(Supplier, b.supplier_id)
    return {"supplier_id": b.supplier_id, "supplier": s.name if s else "", "code": b.code, "price": b.price, "unit": b.unit,
            "description": b.description}


def search(db: Session, q: str, limit: int = 50) -> list[dict]:
    like = f"%{q}%"
    rows = db.scalars(select(SupplierPrice).where(SupplierPrice.current.is_(True), (SupplierPrice.code.ilike(like)) |
                                                  (SupplierPrice.description.ilike(like)) | (SupplierPrice.mfr_code.ilike(like)))
                      .limit(limit))
    sups = {s.id: s.name for s in db.scalars(select(Supplier))}
    return [{"id": p.id, "supplier_id": p.supplier_id, "supplier": sups.get(p.supplier_id, ""), "code": p.code, "mfr_code": p.mfr_code,
             "description": p.description, "brand": p.brand, "group": p.group, "unit": p.unit, "price": p.price,
             "effective": p.effective.isoformat(), "product_key": p.product_key} for p in rows]


def history(db: Session, supplier_id: int, code: str) -> list[dict]:
    return [{"price": p.price, "effective": p.effective.isoformat(), "current": p.current}
            for p in db.scalars(select(SupplierPrice).where(SupplierPrice.supplier_id == supplier_id, SupplierPrice.code == code)
                                .order_by(SupplierPrice.effective))]


def spend_by_code(db: Session, since: date) -> dict[tuple[int | None, str], float]:
    """Quantity bought per (supplier, code) on POs since a date: what the savings are weighted by."""
    out: dict = defaultdict(float)
    for po in db.scalars(select(PurchaseOrder).where(PurchaseOrder.order_date >= since, PurchaseOrder.status != "cancelled")):
        for l in po.lines:
            if l.code:
                out[(po.supplier_id, l.code)] += l.qty
    return out


def comparison(db: Session, group: str = "", only_multi: bool = True, since: date | None = None, limit: int = 2000) -> dict:
    """Every product two or more suppliers sell: who's cheapest, by how much, and what switching would have saved on what we bought."""
    sups = {s.id: s.name for s in db.scalars(select(Supplier))}
    by_key: dict[str, list[SupplierPrice]] = defaultdict(list)
    stmt = select(SupplierPrice).where(SupplierPrice.current.is_(True), SupplierPrice.product_key != "")
    if group:
        stmt = stmt.where(SupplierPrice.group == group)
    for p in db.scalars(stmt):
        by_key[p.product_key].append(p)
    bought = spend_by_code(db, since or date(date.today().year - 1, date.today().month, 1))
    rows, groups = [], defaultdict(lambda: {"products": 0, "wins": defaultdict(int), "saving": 0.0})
    for key, items in by_key.items():
        per_sup = {}
        for p in items:  # one price per supplier: the lowest if a supplier lists it twice
            if p.supplier_id not in per_sup or p.price < per_sup[p.supplier_id].price:
                per_sup[p.supplier_id] = p
        if only_multi and len(per_sup) < 2:
            continue
        ranked = sorted(per_sup.values(), key=lambda p: p.price)
        best, worst = ranked[0], ranked[-1]
        qty = sum(bought.get((p.supplier_id, p.code), 0.0) for p in ranked)
        spent = sum(bought.get((p.supplier_id, p.code), 0.0) * p.price for p in ranked)
        saving = max(0.0, spent - qty * best.price)
        g = next((p.group for p in ranked if p.group), "") or "(no group)"
        groups[g]["products"] += 1
        groups[g]["wins"][sups.get(best.supplier_id, "")] += 1
        groups[g]["saving"] += saving
        rows.append({"product_key": key, "description": best.description or ranked[-1].description,
                     "brand": next((p.brand for p in ranked if p.brand), ""), "group": g,
                     "unit": best.unit, "cheapest_supplier": sups.get(best.supplier_id, ""), "cheapest_supplier_id": best.supplier_id,
                     "cheapest_price": best.price, "highest_price": worst.price,
                     "spread_pct": round(100 * (worst.price - best.price) / worst.price, 1) if worst.price else 0.0,
                     "prices": [{"supplier_id": p.supplier_id, "supplier": sups.get(p.supplier_id, ""), "code": p.code, "price": p.price,
                                 "effective": p.effective.isoformat()} for p in ranked],
                     "qty_bought": round(qty, 2), "saving": round(saving, 2)})
    rows.sort(key=lambda r: (-r["saving"], -r["spread_pct"]))
    group_rows = sorted(({"group": g, "products": v["products"], "saving": round(v["saving"], 2),
                          "cheapest_most_often": max(v["wins"].items(), key=lambda kv: kv[1])[0] if v["wins"] else "",
                          "wins": dict(v["wins"])} for g, v in groups.items()), key=lambda r: (-r["saving"], -r["products"]))
    wins = defaultdict(int)
    for r in rows:
        wins[r["cheapest_supplier"]] += 1
    return {"products": len(rows), "rows": rows[:limit], "groups": group_rows, "supplier_wins": dict(wins),
            "saving_total": round(sum(r["saving"] for r in rows), 2),
            "suppliers": [{"id": s.id, "name": s.name,
                           "items": db.scalar(select(SupplierPrice.id).where(SupplierPrice.supplier_id == s.id).limit(1)) is not None}
                          for s in db.scalars(select(Supplier).order_by(Supplier.name))]}


def link(db: Session, supplier_id: int, code: str, key: str) -> None:
    """Say a supplier's code is the same product as `key` (or give it a key of its own)."""
    m = db.scalar(select(ProductMatch).where(ProductMatch.supplier_id == supplier_id, ProductMatch.code == code))
    if m is None:
        db.add(ProductMatch(supplier_id=supplier_id, code=code, product_key=key))
    else:
        m.product_key = key
    db.execute(update(SupplierPrice).where(SupplierPrice.supplier_id == supplier_id, SupplierPrice.code == code).values(product_key=key))

