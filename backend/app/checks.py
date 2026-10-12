"""Check-measure. Every check raises a flag pointing at a location; nothing is fixed silently.

Re-running keeps the status and note of flags that still apply, and removes flags whose
problem has gone.
"""
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import config
from .geometry import FIXTURE_TOLERANCE_PT, RunShape, end_connections, overlap_fraction, runs_near
from .models import Benchmark, CountItem, CountType, Flag, GeneratedItem, Job, Level, Rule, Run, Service, Sheet
from .scale import polyline_length
from .takeoff import d2, job_totals, vertical_height_from_levels

DRAINAGE_KINDS = {"drainage", "stormwater"}
MEASURED_SHEET_TYPES = {"plan", "section", "schematic", "detail", "other"}


@dataclass
class Finding:
    check_type: str
    ref: str
    severity: str
    message: str
    sheet_id: int | None = None
    x: float | None = None
    y: float | None = None


def _sheet_label(s: Sheet) -> str:
    return s.sheet_no or f"page {s.page_no}"


def find_problems(db: Session, job_id: int) -> list[Finding]:
    sheets = {s.id: s for s in db.scalars(select(Sheet).where(Sheet.job_id == job_id, Sheet.is_current.is_(True)))}
    services = {s.id: s for s in db.scalars(select(Service))}
    count_types = {c.name: c for c in db.scalars(select(CountType))}
    all_runs = [r for r in db.scalars(select(Run).where(Run.job_id == job_id).order_by(Run.id)) if r.sheet_id in sheets]
    all_counts = [c for c in db.scalars(select(CountItem).where(CountItem.job_id == job_id).order_by(CountItem.id)) if c.sheet_id in sheets]
    runs = [r for r in all_runs if r.status == "confirmed"]
    counts = [c for c in all_counts if c.status == "confirmed"]
    levels = list(db.scalars(select(Level).where(Level.job_id == job_id)))
    out: list[Finding] = []

    # 1. Hydraulic sheets with nothing measured on them
    measured = {r.sheet_id for r in all_runs} | {c.sheet_id for c in all_counts}
    for s in sheets.values():
        if s.is_hydraulic and s.classification in MEASURED_SHEET_TYPES and s.id not in measured:
            out.append(Finding("no_measurements", f"sheet:{s.id}", "warning",
                               f"{_sheet_label(s)} ({s.title}) is a hydraulic sheet with nothing measured on it.", s.id))

    # Unconfirmed items stay out of totals and pricing
    n_sugg = sum(1 for r in all_runs if r.status != "confirmed") + sum(1 for c in all_counts if c.status != "confirmed")
    if n_sugg:
        out.append(Finding("unconfirmed", "job", "warning",
                           f"{n_sugg} suggested runs or counts are unconfirmed and are not in the totals."))

    by_sheet_runs: dict[int, list[Run]] = defaultdict(list)
    for r in runs:
        by_sheet_runs[r.sheet_id].append(r)
    by_sheet_counts: dict[int, list[CountItem]] = defaultdict(list)
    for c in counts:
        by_sheet_counts[c.sheet_id].append(c)

    for sheet_id in set(by_sheet_runs) | set(by_sheet_counts):
        s = sheets[sheet_id]
        sruns = by_sheet_runs.get(sheet_id, [])
        run_by_id = {r.id: r for r in sruns}
        shapes = [RunShape(r.id, r.geometry, r.service_id, r.dn, len(r.geometry) < 2) for r in sruns]
        cpts = {c.id: (c.x, c.y) for c in by_sheet_counts.get(sheet_id, [])}

        conns = end_connections(shapes, cpts)
        for conn in conns:
            r = run_by_id[conn.run_id]
            p = r.geometry[0] if conn.end == "start" else r.geometry[-1]
            svc = services[r.service_id]
            # 2. Open ends
            if conn.to_kind == "none":
                out.append(Finding("open_end", f"run:{r.id}:{conn.end}", "warning",
                                   f"{svc.code} DN{r.dn} run #{r.id} on {_sheet_label(s)}: {conn.end} doesn't connect to a fixture, pit, riser or another run.",
                                   s.id, p[0], p[1]))
            # 4. Size jumps on drainage: drawn in flow direction, so the run its end flows into is downstream
            if conn.end == "end" and conn.to_kind == "run" and svc.kind in DRAINAGE_KINDS:
                down = run_by_id[conn.to_id]
                if services[down.service_id].kind in DRAINAGE_KINDS and down.dn < r.dn:
                    out.append(Finding("size_jump", f"run:{r.id}>run:{down.id}", "error",
                                       f"DN{r.dn} run #{r.id} flows into smaller DN{down.dn} run #{down.id} on {_sheet_label(s)}. "
                                       "Check the sizes, or reverse the run if it was traced against the flow.",
                                       s.id, p[0], p[1]))

        # 3. Fixtures without their drainage or water connection
        for c in by_sheet_counts.get(sheet_id, []):
            ct = count_types.get(c.item_type)
            if not ct or not (ct.needs_drainage or ct.needs_water):
                continue
            near = runs_near(shapes, (c.x, c.y), FIXTURE_TOLERANCE_PT)
            kinds = {services[run_by_id[r.id].service_id].kind for r in near}
            missing = []
            if ct.needs_drainage and "drainage" not in kinds:
                missing.append("drainage")
            if ct.needs_water and "water" not in kinds:
                missing.append("water")
            if missing:
                out.append(Finding("fixture_unconnected", f"count:{c.id}", "warning",
                                   f"{c.item_type} #{c.id} on {_sheet_label(s)} has no {' or '.join(missing)} run connected.",
                                   s.id, c.x, c.y))

        # 7a. Duplicate runs on the same sheet
        line_shapes = [sh for sh in shapes if not sh.is_point]
        for i, a in enumerate(line_shapes):
            for b in line_shapes[i + 1:]:
                if a.service_id == b.service_id and overlap_fraction(a, b) > 0.8:
                    out.append(Finding("duplicate_run", f"run:{a.id}=run:{b.id}", "error",
                                       f"Runs #{a.id} and #{b.id} ({services[a.service_id].code}) overlap on {_sheet_label(s)}: possible double count.",
                                       s.id, a.points[0][0], a.points[0][1]))

    # 7b. Possible duplicates across sheets that overlap (same service, size, material, level and length)
    seen: dict[tuple, Run] = {}
    for r in runs:
        if r.level_id is None or r.length_m < 2:
            continue
        key = (r.service_id, r.dn, r.material, r.level_id)
        other = seen.get(key)
        if other and other.sheet_id != r.sheet_id and abs(other.length_m - r.length_m) <= 0.01 * max(r.length_m, other.length_m):
            out.append(Finding("duplicate_run", f"run:{other.id}~run:{r.id}", "warning",
                               f"Runs #{other.id} ({_sheet_label(sheets[other.sheet_id])}) and #{r.id} ({_sheet_label(sheets[r.sheet_id])}) "
                               f"are the same service, size, material, level and length ({r.length_m:.2f} m). Check the sheets don't overlap.",
                               r.sheet_id, r.geometry[0][0], r.geometry[0][1]))
        seen.setdefault(key, r)

    # 5. Sheets with the same stated scale and page size whose calibrations disagree
    groups: dict[tuple, list[Sheet]] = defaultdict(list)
    for s in sheets.values():
        if s.scale_verified and s.calibrated_scale and s.stated_scale:
            groups[(s.stated_scale.replace(" ", "").upper(), s.page_size)].append(s)
    for (stated, page), group in groups.items():
        if len(group) < 2:
            continue
        med = statistics.median(s.calibrated_scale for s in group)
        for s in group:
            diff = abs(s.calibrated_scale - med) / med
            if diff > config.SCALE_TOLERANCE:
                out.append(Finding("scale_mismatch", f"sheet:{s.id}", "error",
                                   f"{_sheet_label(s)} states {s.stated_scale} like {len(group) - 1} other {page} sheet(s), "
                                   f"but its calibration differs from theirs by {diff * 100:.1f}%.", s.id))

    # 6. Benchmark ratios
    fixtures = sum(1 for c in counts if (ct := count_types.get(c.item_type)) and ct.is_fixture)
    svc_by_code = {s.code: s for s in services.values()}
    for b in db.scalars(select(Benchmark).where(Benchmark.active.is_(True))):
        if not fixtures:
            continue
        ids = {svc_by_code[c].id for c in b.service_codes if c in svc_by_code}
        metres = sum(r.length_m + r.vertical_m for r in runs if r.service_id in ids)
        ratio = metres / fixtures
        low = b.min_value is not None and ratio < b.min_value
        high = b.max_value is not None and ratio > b.max_value
        if low or high:
            band = f"{b.min_value if b.min_value is not None else '–'} to {b.max_value if b.max_value is not None else '–'}"
            out.append(Finding("benchmark", f"benchmark:{b.id}", "warning",
                               f"{b.name}: {ratio:.2f} m per fixture ({metres:.2f} m / {fixtures} fixtures) is "
                               f"{'below' if low else 'above'} Peak's band of {band}."))

    # 8. Second-pass total: recompute every run from stored geometry and re-add independently
    level_list = levels
    second = Decimal(0)
    for r in runs:
        plan = d2(polyline_length(r.geometry) * r.m_per_pt) if len(r.geometry) > 1 else Decimal(0)
        if r.vertical_mode == "manual":
            vert = d2(max(r.vertical_count, 0) * max(r.vertical_height_m, 0))
        elif r.vertical_mode == "levels":
            try:
                vert = d2(max(r.vertical_count, 0) * vertical_height_from_levels(level_list, r.vertical_from_level_id, r.vertical_to_level_id))
            except Exception:
                vert = Decimal("-1")
        else:
            vert = Decimal(0)
        if plan != d2(r.length_m) or vert != d2(r.vertical_m):
            out.append(Finding("second_pass", f"run:{r.id}", "error",
                               f"Run #{r.id} stored {r.length_m:.2f} + {r.vertical_m:.2f} m but its geometry and levels give "
                               f"{plan} + {vert if vert >= 0 else 'unknown'} m. Re-save the run or check its levels.",
                               r.sheet_id, r.geometry[0][0], r.geometry[0][1]))
        waste = d2((plan + max(vert, Decimal(0))) * Decimal(str(r.waste_pct)) / 100)
        second += plan + max(vert, Decimal(0)) + waste
    shown = Decimal(str(job_totals(db, job_id)["grand_total_m"])).quantize(Decimal("0.01"))
    if second != shown:
        out.append(Finding("second_pass", "job", "error",
                           f"Independent re-sum of all runs gives {second} m but the totals show {shown} m."))

    # Fittings not generated yet, or out of date
    has_rules = db.scalar(select(Rule.id).where(Rule.active.is_(True)).limit(1)) is not None
    has_generated = db.scalar(select(GeneratedItem.id).where(GeneratedItem.job_id == job_id, GeneratedItem.rule_id.is_not(None)).limit(1)) is not None
    if has_rules and runs and not has_generated:
        out.append(Finding("fittings_missing", "job", "warning",
                           "Fittings and sundries haven't been generated for this job yet."))
    return out


def run_checks(db: Session, job_id: int) -> list[Flag]:
    findings = find_problems(db, job_id)
    existing = {(f.check_type, f.ref): f for f in db.scalars(select(Flag).where(Flag.job_id == job_id))}
    keep = set()
    for fd in findings:
        key = (fd.check_type, fd.ref)
        if key in keep:
            continue
        keep.add(key)
        flag = existing.get(key)
        if flag is None:
            flag = Flag(job_id=job_id, check_type=fd.check_type, ref=fd.ref)
            db.add(flag)
        flag.severity, flag.message = fd.severity, fd.message
        flag.sheet_id, flag.x, flag.y = fd.sheet_id, fd.x, fd.y
    for key, flag in existing.items():
        if key not in keep:
            db.delete(flag)
    job = db.get(Job, job_id)
    job.checks_run_at = datetime.now(timezone.utc)
    db.commit()
    return list(db.scalars(select(Flag).where(Flag.job_id == job_id).order_by(Flag.severity, Flag.check_type, Flag.id)))
