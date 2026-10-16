"""The estimating workbook: the CostX / CANDY side of estimating.

- Resources (labour grades, machines, materials, subcontract rates) and rate build-ups made from them. Change a
  resource's rate and every build-up and workbook row that uses it reprices.
- Workbook rows on a job: quantity typed, from a formula using the job's variables (weeks on site, levels...), or
  linked live to a take-off dimension (q), so a revised drawing flows through. Rates typed or built up.
  Rows price into the same estimate as the take-off (pricing.price_job), with the same margins.
- Subcontract and supply packages: quotes in, levelled (plugs for what each left out), compared and awarded into
  the workbook.
- Estimate versions: a saved copy of the priced estimate to compare with another or with now.
- The tender programme and cash flow: the estimate spread over the programme by stage, with claims, retention,
  payment terms and supplier terms, to see the peak funding the job needs.
"""
import math
import re
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .expr import FormulaError, evaluate
from .models import (CivilBoqLine, EstimateLine, EstimateSnapshot, EstimateVariable, Job, OutboundMessage, PackageQuote, RateBuildup,
                     Resource, Service, Stage, TenderProgramme, TradePackage, User)

RESOURCE_KINDS = ["labour", "plant", "material", "subcontract", "other"]
CATS = ["labour", "material", "plant", "subcontract"]
VAR_NAME = re.compile(r"^[a-z_][a-z0-9_]{0,39}$")
RESERVED = {"q", "n", "m", "dn", "fixtures", "ceil", "floor", "round", "min", "max", "abs"}
CURVES = ["s", "linear", "front", "back"]


def r2(x: float) -> float:
    return round(float(x) + 0.0, 2)


# --- resources and build-ups ---
def resource_map(db: Session) -> dict[str, Resource]:
    return {r.code: r for r in db.scalars(select(Resource))}


def buildup_unit(b: RateBuildup, resources: dict[str, Resource]) -> dict:
    """Cost of one unit of a build-up, by category. Labour hours are counted from labour resources measured in hours."""
    out = {"labour_hours": 0.0, "labour": 0.0, "material": 0.0, "plant": 0.0, "subcontract": 0.0, "missing": [], "lines": []}
    for ln in b.lines or []:
        r = resources.get(ln.get("resource", ""))
        qty = float(ln.get("qty") or 0) * (1 + float(ln.get("waste_pct") or 0) / 100)
        if r is None:
            out["missing"].append(ln.get("resource", ""))
            continue
        amount = qty * r.rate
        cat = r.kind if r.kind in CATS else "material"
        out[cat] += amount
        if r.kind == "labour" and r.unit.lower() in ("h", "hr", "hrs", "hour", "hours"):
            out["labour_hours"] += qty
        out["lines"].append({"resource": r.code, "description": r.description, "kind": r.kind, "unit": r.unit, "qty": round(qty, 4),
                             "rate": r.rate, "amount": r2(amount)})
    out["total"] = r2(out["labour"] + out["material"] + out["plant"] + out["subcontract"])
    for k in ("labour", "material", "plant", "subcontract"):
        out[k] = round(out[k], 4)
    out["labour_hours"] = round(out["labour_hours"], 4)
    return out


# --- take-off dimensions ---
def dimensions(db: Session, job: Job) -> dict[str, dict]:
    """Quantities a workbook row can link to: pipe metres by service / material / size, counts, fittings and civil BOQ lines."""
    from .pricing import collect_sources

    services = {s.id: s.code for s in db.scalars(select(Service))}
    out: dict[str, dict] = {}

    def add(key, label, qty, uom):
        row = out.setdefault(key, {"key": key, "label": label, "qty": 0.0, "uom": uom})
        row["qty"] = round(row["qty"] + float(qty), 3)

    for s in collect_sources(db, job.id):
        svc = services.get(s.service_id, "")
        if s.kind == "pipe":
            add(f"pipe:{svc}:{s.material}:{s.dn}", f"{svc} {s.material} DN{s.dn} pipe", s.qty, "m")
            add(f"pipe:{svc}", f"{svc} all pipe", s.qty, "m")
        elif s.kind == "count":
            add(f"count:{svc}:{s.item_type}", f"{svc} {s.item_type}", s.qty, "ea")
            add("count:*", "All fixtures and points", s.qty, "ea")
        else:
            add(f"fit:{svc}:{s.description}", f"{svc} {s.description}", s.qty, s.uom)
    if job.kind == "civil":
        from .civil import line_qty as boq_qty

        for line in db.scalars(select(CivilBoqLine).where(CivilBoqLine.job_id == job.id, CivilBoqLine.status == "confirmed")):
            add(f"boq:{line.id}", f"{line.category} – {line.description}".strip(" –")[:120], boq_qty(line), line.unit or "")
    return out


def variables(db: Session, job_id: int) -> dict[str, float]:
    return {v.name: v.value for v in db.scalars(select(EstimateVariable).where(EstimateVariable.job_id == job_id))}


def check_name(name: str) -> str:
    n = (name or "").strip().lower()
    if not VAR_NAME.match(n) or n in RESERVED:
        raise ValueError(f"'{name}' can't be a variable name: use letters, numbers and _, starting with a letter "
                         f"(not {', '.join(sorted(RESERVED))})")
    return n


def line_qty(line: EstimateLine, dims: dict, vars_: dict) -> tuple[float, str]:
    """Quantity of a workbook row, and an error to show if its formula or link doesn't work."""
    if line.qty_source == "manual":
        return float(line.qty or 0), ""
    q = 0.0
    if line.qty_source == "takeoff":
        d = dims.get(line.dimension)
        if d is None:
            return 0.0, f"The take-off has nothing for {line.dimension or 'this link'} (yet)"
        q = d["qty"]
        if not line.formula:
            return q, ""
    try:
        return round(evaluate(line.formula or "0", q=q, **vars_), 4), ""
    except FormulaError as e:
        msg = str(e)
        if msg.startswith("Unknown name"):
            msg = msg.split(". Use:")[0] + ". Add it under Variables."
        return 0.0, msg


def line_unit(line: EstimateLine, resources: dict[str, Resource], buildups: dict[str, RateBuildup]) -> tuple[dict, str]:
    if line.rate_source == "buildup":
        b = buildups.get(line.rate_code)
        if b is None:
            return {"labour_hours": 0.0, "labour": 0.0, "material": 0.0, "plant": 0.0, "subcontract": 0.0}, f"No build-up {line.rate_code}"
        u = buildup_unit(b, resources)
        return u, (f"Missing resources: {', '.join(u['missing'])}" if u["missing"] else "")
    if line.rate_source == "resource":
        r = resources.get(line.rate_code)
        if r is None:
            return {"labour_hours": 0.0, "labour": 0.0, "material": 0.0, "plant": 0.0, "subcontract": 0.0}, f"No resource {line.rate_code}"
        cat = r.kind if r.kind in CATS else "material"
        hourly = r.kind == "labour" and r.unit.lower() in ("h", "hr", "hrs", "hour", "hours")
        u = {"labour_hours": 1.0 if hourly else 0.0, "labour": 0.0, "material": 0.0, "plant": 0.0, "subcontract": 0.0}
        u[cat] = r.rate
        return u, ""
    return {"labour_hours": float(line.labour_hours or 0), "labour": float(line.labour_hours or 0) * float(line.labour_rate or 0),
            "material": float(line.material or 0), "plant": float(line.plant or 0), "subcontract": float(line.subcontract or 0)}, ""


def priced_lines(db: Session, job: Job) -> list[dict]:
    """Every workbook row with its quantity, unit rates, costs, margin and sell."""
    from decimal import Decimal

    from .pricing import margin_pct, money, sell_price

    lines = list(db.scalars(select(EstimateLine).where(EstimateLine.job_id == job.id).order_by(EstimateLine.section, EstimateLine.position,
                                                                                                EstimateLine.id)))
    if not lines:
        return []
    dims = dimensions(db, job) if any(ln.qty_source == "takeoff" for ln in lines) else {}
    vars_ = variables(db, job.id)
    resources = resource_map(db)
    buildups = {b.code: b for b in db.scalars(select(RateBuildup))}
    services = {s.id: s.code for s in db.scalars(select(Service))}
    stages = {s.id: s.name for s in db.scalars(select(Stage))}
    out = []
    for ln in lines:
        qty, qerr = line_qty(ln, dims, vars_)
        unit, rerr = line_unit(ln, resources, buildups)
        svc = services.get(ln.service_id, "")
        stage = stages.get(ln.stage_id, "Unstaged")
        cost = {c: money(Decimal(str(unit[c])) * Decimal(str(qty))) for c in CATS}
        total = sum(cost.values(), Decimal(0))
        pct = Decimal(str(ln.margin_pct)) if ln.margin_pct is not None else margin_pct(job, svc, stage)
        sell = sell_price(total, pct, job.margin_basis)
        out.append({"id": ln.id, "section": ln.section, "position": ln.position, "ref": ln.ref, "description": ln.description,
                    "qty_source": ln.qty_source, "formula": ln.formula, "dimension": ln.dimension, "qty": qty, "uom": ln.uom,
                    "rate_source": ln.rate_source, "rate_code": ln.rate_code,
                    "labour_hours_unit": round(unit["labour_hours"], 4), "labour_rate": ln.labour_rate,
                    "unit": {c: round(unit[c], 4) for c in CATS}, "unit_total": r2(sum(unit[c] for c in CATS)),
                    "labour_hours": round(unit["labour_hours"] * qty, 2),
                    "material_cost": float(cost["material"]), "labour_cost": float(cost["labour"]), "plant_cost": float(cost["plant"]),
                    "subcontract_cost": float(cost["subcontract"]), "cost": float(total), "margin_pct": float(pct),
                    "margin_override": ln.margin_pct is not None, "sell": float(sell), "service_id": ln.service_id, "service_code": svc,
                    "stage_id": ln.stage_id, "stage": stage, "package_id": ln.package_id, "note": ln.note,
                    "error": qerr or rerr,
                    # typed unit costs, for editing manual rows
                    "material": ln.material, "plant": ln.plant, "subcontract": ln.subcontract, "labour_hours_typed": ln.labour_hours})
    return out


def workbook(db: Session, job: Job) -> dict:
    rows = priced_lines(db, job)
    first = {}
    for r in rows:  # sections in the order they were started (Preliminaries first if it came first), not A-Z
        first[r["section"]] = min(first.get(r["section"], r["id"]), r["id"])
    rows.sort(key=lambda r: (first[r["section"]], r["position"], r["id"]))
    sections: dict[str, dict] = {}
    for r in rows:
        s = sections.setdefault(r["section"], {"name": r["section"], "lines": [], "cost": 0.0, "sell": 0.0, "labour_hours": 0.0})
        s["lines"].append(r)
        s["cost"] = r2(s["cost"] + r["cost"])
        s["sell"] = r2(s["sell"] + r["sell"])
        s["labour_hours"] = round(s["labour_hours"] + r["labour_hours"], 2)
    tot = {k: r2(sum(r[k] for r in rows)) for k in ("material_cost", "labour_cost", "plant_cost", "subcontract_cost", "cost", "sell")}
    tot["labour_hours"] = round(sum(r["labour_hours"] for r in rows), 2)
    return {"variables": [{"id": v.id, "name": v.name, "value": v.value, "note": v.note}
                          for v in db.scalars(select(EstimateVariable).where(EstimateVariable.job_id == job.id).order_by(EstimateVariable.name))],
            "sections": list(sections.values()), "totals": tot, "errors": sum(1 for r in rows if r["error"])}


def copy_lines(db: Session, src: Job, dst: Job, sections: list[str] | None = None) -> int:
    n = 0
    for ln in db.scalars(select(EstimateLine).where(EstimateLine.job_id == src.id)):
        if sections and ln.section not in sections:
            continue
        cols = {c: getattr(ln, c) for c in ("section", "position", "ref", "description", "qty_source", "qty", "formula", "dimension", "uom",
                                             "rate_source", "rate_code", "labour_hours", "labour_rate", "material", "plant", "subcontract",
                                             "margin_pct", "service_id", "stage_id", "note")}
        db.add(EstimateLine(job_id=dst.id, **cols))
        n += 1
    for v in db.scalars(select(EstimateVariable).where(EstimateVariable.job_id == src.id)):
        if not db.scalar(select(EstimateVariable.id).where(EstimateVariable.job_id == dst.id, EstimateVariable.name == v.name)):
            db.add(EstimateVariable(job_id=dst.id, name=v.name, value=v.value, note=v.note))
    db.flush()
    return n


# --- subcontract / supply packages ---
def levelled(q: PackageQuote) -> float | None:
    if q.amount is None:
        return None
    return r2(q.amount + sum(float(a.get("amount") or 0) for a in q.adjustments or []))


def package_out(db: Session, p: TradePackage) -> dict:
    quotes = list(db.scalars(select(PackageQuote).where(PackageQuote.package_id == p.id).order_by(PackageQuote.id)))
    lev = [levelled(q) for q in quotes]
    priced = [x for x in lev if x is not None]
    low = min(priced) if priced else None
    rows = []
    for q, lv in zip(quotes, lev):
        rows.append({"id": q.id, "company": q.company, "email": q.email, "supplier_id": q.supplier_id, "status": q.status, "amount": q.amount,
                     "adjustments": q.adjustments or [], "levelled": lv, "exclusions": q.exclusions, "notes": q.notes,
                     "valid_until": q.valid_until.isoformat() if q.valid_until else None, "has_file": bool(q.file_key),
                     "file_name": q.file_name, "lowest": lv is not None and lv == low,
                     "over_lowest": r2(lv - low) if lv is not None and low is not None else None,
                     "over_lowest_pct": round(100 * (lv - low) / low, 1) if lv is not None and low else None,
                     "awarded": p.awarded_quote_id == q.id,
                     "invited_at": q.invited_at.isoformat() if q.invited_at else None})
    return {"id": p.id, "job_id": p.job_id, "name": p.name, "kind": p.kind, "scope": p.scope, "due": p.due.isoformat() if p.due else None,
            "status": p.status, "awarded_quote_id": p.awarded_quote_id, "section": p.section, "stage_id": p.stage_id,
            "margin_pct": p.margin_pct, "quotes": rows, "received": sum(1 for q in quotes if q.status == "received"),
            "lowest": low, "spread_pct": round(100 * (max(priced) - low) / low, 1) if len(priced) > 1 and low else None}


def invite(db: Session, p: TradePackage, job: Job, by: User) -> int:
    from . import ops

    n = 0
    company = ops.settings(db)["company_name"]
    for q in db.scalars(select(PackageQuote).where(PackageQuote.package_id == p.id, PackageQuote.status == "invited",
                                                   PackageQuote.invited_at.is_(None))):
        if not q.email:
            continue
        due = f" by {p.due:%d/%m/%Y}" if p.due else ""
        body = (f"Hi {q.company},\n\n{company} is pricing {job.name}{(' at ' + job.address) if job.address else ''} and would like your "
                f"{'price' if p.kind == 'subcontract' else 'supply price'} for {p.name}{due}.\n\nScope:\n{p.scope or '(see attached drawings)'}"
                f"\n\nPlease list anything you've excluded.\n\nThanks,\n{by.name or by.email}\n{company}")
        db.add(OutboundMessage(channel="email", to=q.email, subject=f"Request for quote: {p.name} – {job.name}", body=body,
                               send_at=datetime.now(timezone.utc), job_id=job.id))
        q.invited_at = datetime.now(timezone.utc)
        n += 1
    db.flush()
    return n


def award(db: Session, p: TradePackage, q: PackageQuote) -> EstimateLine:
    amount = levelled(q)
    if amount is None:
        raise ValueError("That quote has no price yet")
    line = db.scalar(select(EstimateLine).where(EstimateLine.package_id == p.id))
    if line is None:
        line = EstimateLine(job_id=p.job_id, package_id=p.id, qty_source="manual", qty=1, uom="item", rate_source="manual")
        db.add(line)
    line.section = p.section or "Subcontract"
    line.description = f"{p.name} – {q.company}"
    line.stage_id = p.stage_id
    line.margin_pct = p.margin_pct
    line.subcontract = amount if p.kind == "subcontract" else 0.0
    line.material = amount if p.kind == "supply" else 0.0
    line.note = (f"Quote {q.amount:,.2f}" + (f" + levelling {amount - q.amount:,.2f}" if amount != q.amount else "")
                 + (f". Excludes: {q.exclusions}" if q.exclusions else ""))
    p.awarded_quote_id, p.status = q.id, "awarded"
    db.flush()
    return line


# --- versions ---
def _compact(priced: dict) -> tuple[dict, list[dict]]:
    s = priced.get("summary") or {}
    summ = {k: s.get(k) for k in ("material_cost", "labour_cost", "plant_cost", "subcontract_cost", "allowances_cost", "labour_hours",
                                   "cost", "margin", "sell_ex_gst")}
    summ["by_stage"] = {r["stage"]: {"cost": r.get("cost", 0), "sell": r.get("sell", 0)} for r in s.get("by_stage", [])}
    lines = []
    for ln in priced.get("lines", []):
        lines.append({"key": f"{ln['kind']}|{ln['stage']}|{ln['service_code']}|{ln['description']}", "kind": ln["kind"], "stage": ln["stage"],
                      "service_code": ln["service_code"], "description": ln["description"], "qty": ln.get("qty", 0), "uom": ln.get("uom", ""),
                      "cost": ln.get("cost", 0) or 0, "sell": ln.get("sell", 0) or 0})
    for a in priced.get("allowances", []):
        if a["kind"] != "exclusion":
            lines.append({"key": f"allowance|{a['stage']}|{a['service_code']}|{a['description']}", "kind": a["kind"], "stage": a["stage"],
                          "service_code": a["service_code"], "description": a["description"], "qty": 1, "uom": "item",
                          "cost": a["amount"], "sell": a.get("sell", 0)})
    return summ, lines


def snapshot(db: Session, job: Job, label: str, user: User | None) -> EstimateSnapshot:
    from .pricing import price_job

    summ, lines = _compact(price_job(db, job.id))
    s = EstimateSnapshot(job_id=job.id, label=label, summary=summ, lines=lines, created_by=user.id if user else None)
    db.add(s)
    db.flush()
    return s


def current_version(db: Session, job: Job) -> dict:
    from .pricing import price_job

    summ, lines = _compact(price_job(db, job.id))
    return {"id": "current", "label": "Now", "summary": summ, "lines": lines}


def compare(a: dict, b: dict) -> dict:
    """What changed from version a to version b: totals, by stage, and line by line (biggest change in sell first)."""
    def num(x):
        return float(x or 0)

    tot = {k: {"a": num(a["summary"].get(k)), "b": num(b["summary"].get(k)), "change": r2(num(b["summary"].get(k)) - num(a["summary"].get(k)))}
           for k in ("cost", "sell_ex_gst", "margin", "labour_hours", "material_cost", "labour_cost", "subcontract_cost")}
    stages = sorted(set(a["summary"].get("by_stage", {})) | set(b["summary"].get("by_stage", {})))
    by_stage = []
    for st in stages:
        sa, sb = a["summary"].get("by_stage", {}).get(st, {}), b["summary"].get("by_stage", {}).get(st, {})
        by_stage.append({"stage": st, "a": num(sa.get("sell")), "b": num(sb.get("sell")), "change": r2(num(sb.get("sell")) - num(sa.get("sell")))})
    la, lb = defaultdict(lambda: {"qty": 0.0, "cost": 0.0, "sell": 0.0}), defaultdict(lambda: {"qty": 0.0, "cost": 0.0, "sell": 0.0})
    meta = {}
    for src, dst in ((a["lines"], la), (b["lines"], lb)):
        for ln in src:
            d = dst[ln["key"]]
            d["qty"] += num(ln["qty"])
            d["cost"] += num(ln["cost"])
            d["sell"] += num(ln["sell"])
            meta[ln["key"]] = ln
    changes = []
    for k in set(la) | set(lb):
        x, y = la.get(k), lb.get(k)
        kind = "added" if x is None else "removed" if y is None else "changed"
        x = x or {"qty": 0.0, "cost": 0.0, "sell": 0.0}
        y = y or {"qty": 0.0, "cost": 0.0, "sell": 0.0}
        if kind == "changed" and abs(x["qty"] - y["qty"]) < 1e-6 and abs(x["sell"] - y["sell"]) < 0.005:
            continue
        m = meta[k]
        changes.append({"kind": kind, "description": m["description"], "stage": m["stage"], "service_code": m["service_code"], "uom": m["uom"],
                        "qty_a": round(x["qty"], 3), "qty_b": round(y["qty"], 3), "sell_a": r2(x["sell"]), "sell_b": r2(y["sell"]),
                        "change": r2(y["sell"] - x["sell"])})
    changes.sort(key=lambda c: -abs(c["change"]))
    return {"a": {"id": a["id"], "label": a["label"]}, "b": {"id": b["id"], "label": b["label"]}, "totals": tot, "by_stage": by_stage,
            "lines": changes}


def version_dict(s: EstimateSnapshot) -> dict:
    return {"id": s.id, "label": s.label, "summary": s.summary, "lines": s.lines}


# --- tender programme and cash flow ---
def default_programme(db: Session, job: Job) -> dict:
    from .pricing import price_job

    s = price_job(db, job.id).get("summary") or {}
    stages = [r["stage"] for r in s.get("by_stage", []) if r.get("sell")]
    acts, week = [], 0
    for st in stages or ["Works"]:
        acts.append({"name": st, "stages": [st] if stages else [], "start_week": week, "weeks": 4, "curve": "s"})
        week += 3  # stages overlap by a week
    start = job.due_date + timedelta(days=28) if getattr(job, "due_date", None) else date.today() + timedelta(days=28)
    return {"start": start.isoformat(), "retention_pct": 5.0, "retention_cap_pct": 5.0, "terms_days": 30, "pay_suppliers_days": 30,
            "activities": acts, "saved": False}


def programme_dict(p: TenderProgramme) -> dict:
    return {"start": p.start.isoformat(), "retention_pct": p.retention_pct, "retention_cap_pct": p.retention_cap_pct,
            "terms_days": p.terms_days, "pay_suppliers_days": p.pay_suppliers_days, "activities": p.activities or [], "saved": True}


def _weights(n: int, curve: str) -> list[float]:
    if n <= 0:
        return []
    if curve == "linear":
        w = [1.0] * n
    elif curve == "front":
        w = [float(n - i) for i in range(n)]
    elif curve == "back":
        w = [float(i + 1) for i in range(n)]
    else:  # s-curve: slow start, busy middle, slow finish
        w = [math.sin(math.pi * (i + 0.5) / n) for i in range(n)]
    t = sum(w)
    return [x / t for x in w]


def _month(d: date) -> str:
    return f"{d.year}-{d.month:02d}"


def _add_months(key: str, n: int) -> str:
    y, m = int(key[:4]), int(key[5:])
    m += n
    y += (m - 1) // 12
    m = (m - 1) % 12 + 1
    return f"{y}-{m:02d}"


def cashflow(db: Session, job: Job, prog: dict) -> dict:
    """Spread each stage's sell and cost over the activities it belongs to, then month by month: work done (claimed at
    month end), retention held, money in after the payment terms, labour paid the same month and the rest after supplier
    terms. Retention: half back at practical completion, half after the 12-month defects period."""
    from .pricing import price_job

    s = price_job(db, job.id).get("summary") or {}
    by_stage = {r["stage"]: r for r in s.get("by_stage", [])}
    start = date.fromisoformat(prog["start"])
    acts = prog.get("activities") or []
    weekly_sell: dict[int, float] = defaultdict(float)
    weekly_cost: dict[int, float] = defaultdict(float)
    weekly_labour: dict[int, float] = defaultdict(float)
    placed = set()
    for a in acts:
        sts = [st for st in a.get("stages") or [] if st in by_stage]
        weeks = max(1, int(a.get("weeks") or 1))
        w = _weights(weeks, a.get("curve", "s"))
        for st in sts:
            # a stage in several activities is split evenly between them
            share = 1 / sum(1 for b in acts if st in (b.get("stages") or []))
            placed.add(st)
            for i in range(weeks):
                wk = int(a.get("start_week") or 0) + i
                weekly_sell[wk] += by_stage[st].get("sell", 0) * w[i] * share
                weekly_cost[wk] += by_stage[st].get("cost", 0) * w[i] * share
                weekly_labour[wk] += by_stage[st].get("labour_cost", 0) * w[i] * share
    last_week = max([int(a.get("start_week") or 0) + max(1, int(a.get("weeks") or 1)) for a in acts] or [1])
    unplaced = [st for st in by_stage if st not in placed]
    if unplaced:  # anything not on the programme is spread evenly over it
        for st in unplaced:
            for wk in range(last_week):
                weekly_sell[wk] += by_stage[st].get("sell", 0) / last_week
                weekly_cost[wk] += by_stage[st].get("cost", 0) / last_week
                weekly_labour[wk] += by_stage[st].get("labour_cost", 0) / last_week
    months: dict[str, dict] = {}

    def row(k):
        return months.setdefault(k, {"month": k, "value": 0.0, "cost": 0.0, "claim": 0.0, "retention_held": 0.0, "retention_released": 0.0,
                                     "receipts": 0.0, "payments": 0.0})
    for wk in sorted(set(weekly_sell) | set(weekly_cost)):
        k = _month(start + timedelta(days=7 * wk + 3))
        row(k)["value"] += weekly_sell[wk]
        row(k)["cost"] += weekly_cost[wk]
    contract = sum(r.get("sell", 0) for r in by_stage.values())
    cap = contract * prog.get("retention_cap_pct", 5.0) / 100
    held = 0.0
    recv_lag = max(0, math.ceil((prog.get("terms_days") or 0) / 30))
    pay_lag = max(0, math.ceil((prog.get("pay_suppliers_days") or 0) / 30))
    work_months = sorted(months)
    labour_by_month: dict[str, float] = defaultdict(float)
    for wk, v in weekly_labour.items():
        labour_by_month[_month(start + timedelta(days=7 * wk + 3))] += v
    for k in work_months:
        m = months[k]
        m["claim"] = m["value"]
        ret = min(m["claim"] * prog.get("retention_pct", 5.0) / 100, max(0.0, cap - held))
        held += ret
        m["retention_held"] = ret
        row(_add_months(k, recv_lag))["receipts"] += m["claim"] - ret
        lab = min(labour_by_month.get(k, 0.0), m["cost"])
        m["payments"] += lab
        row(_add_months(k, pay_lag))["payments"] += m["cost"] - lab
    if work_months:
        pc = _add_months(work_months[-1], 1)
        row(_add_months(pc, recv_lag))["receipts"] += held / 2
        row(_add_months(pc, recv_lag))["retention_released"] += held / 2
        row(_add_months(pc, 12))["receipts"] += held / 2
        row(_add_months(pc, 12))["retention_released"] += held / 2
    cum = 0.0
    peak = 0.0
    out = []
    for k in sorted(months):
        m = months[k]
        m["net"] = m["receipts"] - m["payments"]
        cum += m["net"]
        m["cumulative"] = cum
        peak = min(peak, cum)
        out.append({kk: (r2(v) if isinstance(v, float) else v) for kk, v in m.items()})
    gantt = [{"name": a.get("name"), "start": (start + timedelta(days=7 * int(a.get("start_week") or 0))).isoformat(),
              "finish": (start + timedelta(days=7 * (int(a.get("start_week") or 0) + max(1, int(a.get("weeks") or 1))) - 3)).isoformat(),
              "sell": r2(sum(by_stage[st].get("sell", 0) / sum(1 for b in acts if st in (b.get("stages") or []))
                             for st in a.get("stages") or [] if st in by_stage))} for a in acts]
    return {"months": out, "contract": r2(contract), "cost": r2(sum(r.get("cost", 0) for r in by_stage.values())),
            "peak_funding": r2(-peak), "retention_held": r2(held), "unplaced_stages": unplaced, "gantt": gantt,
            "finish": (start + timedelta(days=7 * last_week)).isoformat()}
