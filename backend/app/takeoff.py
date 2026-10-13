"""Measuring rules and totals. The on-screen totals and the Excel export both come from
`job_totals`, so they always match."""
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import CountItem, Level, Run, Service, Sheet, Stage
from .scale import polyline_length

TWO_DP = Decimal("0.01")


def d2(x: float | Decimal) -> Decimal:
    return Decimal(str(x)).quantize(TWO_DP, rounding=ROUND_HALF_UP)


def _inside(bbox, p) -> bool:
    x0, y0, x1, y1 = bbox
    return min(x0, x1) <= p[0] <= max(x0, x1) and min(y0, y1) <= p[1] <= max(y0, y1)


def resolve_scale(sheet: Sheet, points: list) -> tuple[float, int | None]:
    """The verified scale to measure these points with. Raises 409 if measuring is blocked."""
    for vp in sheet.viewports:
        inside = [_inside(vp.bbox, p) for p in points]
        if all(inside):
            if not (vp.scale_verified and vp.calibrated_scale):
                raise HTTPException(409, f"Detail viewport '{vp.name}' has no verified scale. Calibrate and verify it first.")
            return vp.calibrated_scale, vp.id
        if any(inside):
            raise HTTPException(409, f"This run crosses the edge of detail viewport '{vp.name}', which has its own scale. Split it at the boundary.")
    if not (sheet.scale_verified and sheet.calibrated_scale):
        raise HTTPException(409, "This sheet's scale hasn't been verified. Calibrate it and check it against a second dimension first.")
    return sheet.calibrated_scale, None


def vertical_height_from_levels(levels: list[Level], from_id: int | None, to_id: int | None) -> float:
    """Sum of floor-to-floor heights from the lower level up to (not including) the upper one."""
    by_id = {l.id: l for l in levels}
    if from_id not in by_id or to_id not in by_id:
        raise HTTPException(422, "Choose both levels for a level-based vertical")
    lo, hi = sorted([by_id[from_id], by_id[to_id]], key=lambda l: l.rl)
    ordered = sorted(levels, key=lambda l: l.rl)
    span = [l for l in ordered if lo.rl <= l.rl < hi.rl]
    return sum(l.floor_to_floor_m for l in span)


def recompute_run(db: Session, run: Run) -> None:
    run.length_m = float(d2(polyline_length(run.geometry) * run.m_per_pt)) if len(run.geometry) > 1 else 0.0
    if run.vertical_mode == "manual":
        run.vertical_m = float(d2(max(run.vertical_count, 0) * max(run.vertical_height_m, 0)))
    elif run.vertical_mode == "levels":
        levels = list(db.scalars(select(Level).where(Level.job_id == run.job_id)))
        h = vertical_height_from_levels(levels, run.vertical_from_level_id, run.vertical_to_level_id)
        run.vertical_height_m = h
        run.vertical_m = float(d2(max(run.vertical_count, 0) * h))
    else:
        run.vertical_count = 0
        run.vertical_m = 0.0
    if run.length_m == 0 and run.vertical_m == 0:
        raise HTTPException(422, "A run needs a traced length, a vertical length, or both")


def run_waste_m(run: Run) -> Decimal:
    return d2((d2(run.length_m) + d2(run.vertical_m)) * Decimal(str(run.waste_pct)) / 100)


def job_totals(db: Session, job_id: int, include_suggested: bool = False) -> dict:
    """Totals per service / size / material and per stage, plus counts.

    Only confirmed quantities count unless include_suggested is set; suggested ones are
    reported separately so nothing unconfirmed slips into a total.
    """
    services = {s.id: s for s in db.scalars(select(Service))}
    stages = {s.id: s for s in db.scalars(select(Stage))}
    current_sheet_ids = set(db.scalars(select(Sheet.id).where(Sheet.job_id == job_id, Sheet.is_current.is_(True))))

    runs = list(db.scalars(select(Run).where(Run.job_id == job_id)))
    counts = list(db.scalars(select(CountItem).where(CountItem.job_id == job_id)))

    lines: dict[tuple, dict] = {}
    by_stage: dict[tuple, Decimal] = defaultdict(Decimal)
    suggested_runs = 0
    superseded_runs = 0
    for r in runs:
        if r.sheet_id not in current_sheet_ids:
            superseded_runs += 1
            continue
        if r.status != "confirmed" and not include_suggested:
            suggested_runs += 1
            continue
        svc = services[r.service_id]
        key = (svc.order, svc.code, r.dn, r.material)
        line = lines.setdefault(key, {
            "service_code": svc.code, "service_name": svc.name, "colour": svc.colour,
            "dn": r.dn, "material": r.material,
            "plan_m": Decimal(0), "vertical_m": Decimal(0), "waste_m": Decimal(0), "total_m": Decimal(0), "runs": 0,
        })
        waste = run_waste_m(r)
        total = d2(r.length_m) + d2(r.vertical_m) + waste
        line["plan_m"] += d2(r.length_m)
        line["vertical_m"] += d2(r.vertical_m)
        line["waste_m"] += waste
        line["total_m"] += total
        line["runs"] += 1
        stage = stages.get(r.stage_id)
        by_stage[(stage.order if stage else 999, stage.name if stage else "Unstaged", svc.code)] += total

    count_lines: dict[tuple, dict] = {}
    suggested_counts = 0
    for c in counts:
        if c.sheet_id not in current_sheet_ids:
            continue
        if c.status != "confirmed" and not include_suggested:
            suggested_counts += 1
            continue
        svc = services[c.service_id]
        stage = stages.get(c.stage_id)
        key = (svc.order, svc.code, c.item_type, stage.order if stage else 999)
        cl = count_lines.setdefault(key, {
            "service_code": svc.code, "item_type": c.item_type, "stage": stage.name if stage else "Unstaged", "qty": 0,
        })
        cl["qty"] += 1

    service_lines = [lines[k] for k in sorted(lines)]
    service_totals: dict[str, dict] = {}
    for l in service_lines:
        st = service_totals.setdefault(l["service_code"], {
            "service_code": l["service_code"], "service_name": l["service_name"],
            "plan_m": Decimal(0), "vertical_m": Decimal(0), "waste_m": Decimal(0), "total_m": Decimal(0),
        })
        for f in ("plan_m", "vertical_m", "waste_m", "total_m"):
            st[f] += l[f]

    stage_rows = [
        {"stage": name, "service_code": code, "total_m": total}
        for (_, name, code), total in sorted(by_stage.items())
    ]

    def fmt(rows):
        return [{k: (float(v) if isinstance(v, Decimal) else v) for k, v in row.items()} for row in rows]

    return {
        "lines": fmt(service_lines),
        "services": fmt(list(service_totals.values())),
        "stages": fmt(stage_rows),
        "counts": [count_lines[k] for k in sorted(count_lines)],
        "grand_total_m": float(sum((l["total_m"] for l in service_lines), Decimal(0))),
        "excluded": {"suggested_runs": suggested_runs, "suggested_counts": suggested_counts, "superseded_runs": superseded_runs},
    }
