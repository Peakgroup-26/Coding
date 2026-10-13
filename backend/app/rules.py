"""Fittings and sundries rules engine.

Rules are Peak's own allowances, stored as data. Generating applies every active rule to the
job's confirmed quantities on current sheets and writes one GeneratedItem per rule per source
(run, counted item, or the whole job), so every line traces back to its rule and source.
Hand overrides survive regeneration.
"""
import string
from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from .expr import FormulaError, evaluate
from .geometry import RunShape, bends, branch_connections, end_connections
from .models import CatalogueItem, CountItem, CountType, GeneratedItem, Rule, Run, Service, Sheet

TRIGGERS = ("per_fixture", "per_metre", "per_bend", "per_branch", "per_io", "per_job")

DISCLAIMER = ("Fittings and sundries are generated from Peak's own allowance rules. They are an estimate, "
              "not a design. Compliance with AS/NZS 3500 is the plumber's responsibility.")


class _Blank(dict):
    def __missing__(self, key):
        return ""


def describe(template: str, fallback: str, **values) -> str:
    if not template:
        return fallback
    # Only simple {name} fields are allowed; anything else is left as typed.
    try:
        names = {f for _, f, _, _ in string.Formatter().parse(template) if f}
        if any(not n.isidentifier() for n in names):
            return template
        return template.format_map(_Blank({k: ("" if v is None else v) for k, v in values.items()}))
    except (ValueError, IndexError):
        return template


@dataclass
class JobData:
    runs: list[Run]
    counts: list[CountItem]
    services: dict[int, Service]
    count_types: dict[str, CountType]
    shapes_by_sheet: dict[int, list[RunShape]]


def load_job_data(db: Session, job_id: int) -> JobData:
    current = set(db.scalars(select(Sheet.id).where(Sheet.job_id == job_id, Sheet.is_current.is_(True))))
    runs = [r for r in db.scalars(select(Run).where(Run.job_id == job_id).order_by(Run.id))
            if r.sheet_id in current and r.status == "confirmed"]
    counts = [c for c in db.scalars(select(CountItem).where(CountItem.job_id == job_id).order_by(CountItem.id))
              if c.sheet_id in current and c.status == "confirmed"]
    shapes: dict[int, list[RunShape]] = defaultdict(list)
    for r in runs:
        shapes[r.sheet_id].append(RunShape(r.id, r.geometry, r.service_id, r.dn, len(r.geometry) < 2))
    return JobData(
        runs=runs, counts=counts,
        services={s.id: s for s in db.scalars(select(Service))},
        count_types={c.name: c for c in db.scalars(select(CountType))},
        shapes_by_sheet=shapes,
    )


def _run_matches(cond: dict, run: Run, services: dict[int, Service]) -> bool:
    codes = cond.get("service_codes") or []
    mats = cond.get("materials") or []
    if codes and services[run.service_id].code not in codes:
        return False
    if mats and run.material not in mats:
        return False
    if cond.get("dn_min") is not None and run.dn < cond["dn_min"]:
        return False
    if cond.get("dn_max") is not None and run.dn > cond["dn_max"]:
        return False
    return True


def _count_matches(cond: dict, c: CountItem, data: JobData) -> bool:
    types = cond.get("item_types") or []
    if types:
        if c.item_type not in types:
            return False
    else:
        ct = data.count_types.get(c.item_type)
        if not (ct and ct.is_fixture):
            return False
    codes = cond.get("service_codes") or []
    return not codes or data.services[c.service_id].code in codes


@dataclass
class Line:
    rule: Rule
    source_ref: str
    source_qty: float
    qty: float
    description: str
    service_id: int | None
    dn: int | None
    material: str
    stage_id: int | None


def apply_rule(rule: Rule, data: JobData, catalogue: dict[int, CatalogueItem]) -> list[Line]:
    cond = rule.condition or {}
    fallback = catalogue[rule.output_item_id].description if rule.output_item_id in catalogue else rule.name
    lines: list[Line] = []

    def add(source_ref, source_qty, variables: dict, service_id, dn, material, stage_id, **extra):
        qty = round(evaluate(rule.formula, **variables), 3)
        if qty <= 0:
            return
        svc = data.services.get(service_id)
        desc = describe(rule.output_description, fallback, dn=dn or "", material=material,
                        service=svc.code if svc else "", **extra)
        lines.append(Line(rule, source_ref, source_qty, qty, desc, service_id, dn, material,
                          rule.stage_id or stage_id))

    t = rule.trigger_type
    if t == "per_fixture":
        for c in data.counts:
            if _count_matches(cond, c, data):
                add(f"count:{c.id}", 1, {"n": 1}, c.service_id, None, "", c.stage_id, item_type=c.item_type)

    elif t == "per_metre":
        for r in data.runs:
            if _run_matches(cond, r, data.services):
                m = r.length_m + r.vertical_m
                add(f"run:{r.id}", m, {"m": m, "dn": r.dn}, r.service_id, r.dn, r.material, r.stage_id)

    elif t == "per_bend":
        lo, hi = cond.get("angle_min", 0), cond.get("angle_max", 180)
        for r in data.runs:
            if len(r.geometry) > 2 and _run_matches(cond, r, data.services):
                n = len(bends(r.geometry, lo, hi))
                if n:
                    add(f"run:{r.id}", n, {"n": n, "dn": r.dn}, r.service_id, r.dn, r.material, r.stage_id)

    elif t == "per_branch":
        by_id = {r.id: r for r in data.runs}
        per_run: dict[int, list[int]] = defaultdict(list)
        for shapes in data.shapes_by_sheet.values():
            for branch_id, main_id, _ in branch_connections(shapes):
                per_run[branch_id].append(main_id)
        for branch_id, mains in per_run.items():
            r = by_id[branch_id]
            if _run_matches(cond, r, data.services):
                main_dn = max(by_id[m].dn for m in mains)
                add(f"run:{r.id}", len(mains), {"n": len(mains), "dn": r.dn}, r.service_id, r.dn, r.material,
                    r.stage_id, main_dn=main_dn, branch_dn=r.dn)

    elif t == "per_io":
        at_ends, at_bends = cond.get("io_at_ends", False), cond.get("io_at_bends", False)
        interval = cond.get("io_interval_m") or 0
        lo, hi = cond.get("angle_min", 0), cond.get("angle_max", 180)
        ends_free: dict[int, int] = defaultdict(int)
        if at_ends:
            for shapes in data.shapes_by_sheet.values():
                for conn in end_connections(shapes, {}):
                    if conn.to_kind != "run":
                        ends_free[conn.run_id] += 1
        for r in data.runs:
            if len(r.geometry) < 2 or not _run_matches(cond, r, data.services):
                continue
            n = ends_free[r.id] if at_ends else 0
            if at_bends:
                n += len(bends(r.geometry, lo, hi))
            if interval > 0:
                n += int(r.length_m // interval)
            if n:
                add(f"run:{r.id}", n, {"n": n, "dn": r.dn}, r.service_id, r.dn, r.material, r.stage_id)

    elif t == "per_job":
        m = sum(r.length_m + r.vertical_m for r in data.runs if _run_matches(cond, r, data.services))
        fixtures = sum(1 for c in data.counts if (ct := data.count_types.get(c.item_type)) and ct.is_fixture)
        codes = cond.get("service_codes") or []
        svc_id = next((s.id for s in data.services.values() if len(codes) == 1 and s.code == codes[0]), None)
        add("job", m, {"m": m, "fixtures": fixtures, "n": 1}, svc_id, None, "", None)

    return lines


def generate(db: Session, job_id: int) -> dict:
    """Regenerate all rule-based items for a job, keeping hand overrides and notes."""
    data = load_job_data(db, job_id)
    catalogue = {c.id: c for c in db.scalars(select(CatalogueItem))}
    rules = list(db.scalars(select(Rule).where(Rule.active.is_(True)).order_by(Rule.id)))

    existing = list(db.scalars(select(GeneratedItem).where(GeneratedItem.job_id == job_id, GeneratedItem.rule_id.is_not(None))))
    kept = {(g.rule_id, g.source_ref, g.description): g for g in existing}

    errors = []
    new_lines: list[Line] = []
    for rule in rules:
        try:
            new_lines.extend(apply_rule(rule, data, catalogue))
        except (FormulaError, TypeError, ValueError) as e:
            errors.append({"rule_id": rule.id, "rule": rule.name, "error": str(e)})

    seen = set()
    for ln in new_lines:
        key = (ln.rule.id, ln.source_ref, ln.description)
        seen.add(key)
        g = kept.get(key)
        if g is None:
            g = GeneratedItem(job_id=job_id, rule_id=ln.rule.id, source_ref=ln.source_ref, description=ln.description)
            db.add(g)
        g.rule_version = ln.rule.version
        g.source_qty = ln.source_qty
        g.item_id = ln.rule.output_item_id
        g.uom = ln.rule.uom
        g.service_id = ln.service_id
        g.dn = ln.dn
        g.material = ln.material
        g.qty = ln.qty
        if not g.stage_overridden:
            g.stage_id = ln.stage_id

    dropped_overrides = 0
    for key, g in kept.items():
        if key not in seen:
            if g.overridden_qty is not None or g.note:
                dropped_overrides += 1
            db.delete(g)
    db.commit()
    return {"lines": len(new_lines), "rules": len(rules), "errors": errors, "dropped_overrides": dropped_overrides}


def effective_qty(g: GeneratedItem) -> float:
    return g.overridden_qty if g.overridden_qty is not None else g.qty
