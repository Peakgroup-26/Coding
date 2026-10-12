"""CSV export for importing an estimate into Simpro.

The column layout is an admin-editable template, because Simpro import formats vary by
company setup. Each column takes its value from one of FIELDS.
"""
import csv
import io
from collections import defaultdict

from sqlalchemy.orm import Session

from .models import AppSetting

FIELDS = {
    "code": "Prebuild or catalogue code",
    "description": "Prebuild or item description",
    "type": "Prebuild / Catalogue / PC item / Provisional sum",
    "qty": "Quantity",
    "uom": "Unit",
    "unit_cost": "Cost per unit, ex GST",
    "unit_sell": "Sell per unit, ex GST",
    "cost_ex": "Line cost, ex GST",
    "sell_ex": "Line sell, ex GST",
    "labour_hours": "Labour hours",
    "stage": "Stage",
    "service": "Service code",
}

DEFAULT_TEMPLATE = {
    "columns": [
        {"header": "Part Number", "field": "code"},
        {"header": "Description", "field": "description"},
        {"header": "Type", "field": "type"},
        {"header": "Quantity", "field": "qty"},
        {"header": "Unit Sell Price", "field": "unit_sell"},
        {"header": "Cost Centre", "field": "stage"},
        {"header": "Section", "field": "service"},
    ],
    "group_by_stage": True,
    "group_by_service": True,
    "include_allowances": True,
}

KEY = "simpro_template"


def get_template(db: Session) -> dict:
    s = db.get(AppSetting, KEY)
    return {**DEFAULT_TEMPLATE, **(s.value if s and s.value else {})}


def validate_template(t: dict) -> None:
    cols = t.get("columns") or []
    if not cols:
        raise ValueError("The template needs at least one column")
    for c in cols:
        if c.get("field") not in FIELDS:
            raise ValueError(f"Unknown field '{c.get('field')}'. Use one of: {', '.join(FIELDS)}")
        if not (c.get("header") or "").strip():
            raise ValueError("Every column needs a heading")


def build_csv(pricing: dict, template: dict) -> str:
    """One row per prebuild/item code (per stage and service if the template groups them)."""
    by_stage, by_service = template.get("group_by_stage", True), template.get("group_by_service", True)
    groups: dict[tuple, dict] = {}
    for ln in pricing["lines"]:
        key = (ln["target_kind"], ln["target_code"], ln["stage"] if by_stage else "", ln["service_code"] if by_service else "")
        g = groups.setdefault(key, defaultdict(float, {
            "code": ln["target_code"], "description": ln.get("target_description") or ln["description"],
            "type": "Prebuild" if ln["target_kind"] == "prebuild" else "Catalogue",
            "uom": ln["uom"] if ln["factor"] == 1 else "", "stage": key[2], "service": key[3]}))
        g["qty"] += ln.get("target_qty", ln["qty"])
        for f_src, f_dst in (("cost", "cost_ex"), ("sell", "sell_ex"), ("labour_hours", "labour_hours")):
            g[f_dst] += ln.get(f_src, 0) or 0
    rows = list(groups.values())
    if template.get("include_allowances", True):
        for a in pricing["allowances"]:
            if a["kind"] == "exclusion":
                continue
            rows.append({"code": "", "description": a["description"],
                         "type": "PC item" if a["kind"] == "pc" else "Provisional sum", "qty": 1, "uom": "item",
                         "cost_ex": a["amount"], "sell_ex": a["sell"], "labour_hours": 0,
                         "stage": a["stage"] if by_stage else "", "service": a["service_code"] if by_service else ""})
    for r in rows:
        q = r["qty"] or 0
        r["qty"] = round(q, 3)
        r["cost_ex"] = round(r.get("cost_ex", 0), 2)
        r["sell_ex"] = round(r.get("sell_ex", 0), 2)
        r["labour_hours"] = round(r.get("labour_hours", 0), 2)
        r["unit_cost"] = round(r["cost_ex"] / q, 4) if q else 0
        r["unit_sell"] = round(r["sell_ex"] / q, 4) if q else 0
    rows.sort(key=lambda r: (r["stage"], r["service"], r["type"], r["code"]))

    buf = io.StringIO()
    w = csv.writer(buf)
    cols = template["columns"]
    w.writerow([c["header"] for c in cols])
    for r in rows:
        w.writerow([r.get(c["field"], "") for c in cols])
    return buf.getvalue()
