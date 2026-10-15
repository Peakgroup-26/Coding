"""Reports: material lists, labour hours, crew predictions, programs, cash flow, and the company
dashboard. Everything is worked out from the take-off (or the civil BOQ) each time it's asked for.

Labour hours come from the price book first (prebuild labour hours, through the price mappings),
then from Peak's productivity rates. Nothing is guessed: an item with neither is listed as
"no labour rate" and left out of the hours, so the gap is visible.

Crew and program settings (hours per day, apprentice ratio, supervision, project management,
stock lengths, shutdown) are company settings an admin can change, with per-job overrides.
"""
import math
from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (AiOutcome, AppSetting, CivilBoqLine, Job, JobAllowance, PriceBookVersion, PriceMapping, ProductivityRate,
                     Service, Sheet, Stage)
from .pricing import PriceBook, collect_sources, find_mapping

SETTINGS_KEY = "workforce"
DEFAULTS = {
    "hours_per_day": 8.0,
    "days_per_week": 5,
    "apprentice_ratio": 0.5,  # apprentices per plumber
    "apprentice_productivity": 0.5,  # an apprentice's output compared with a plumber's
    "workers_per_supervisor": 6,  # one supervisor / leading hand per this many on site
    "supervisor_from_crew": 4,  # below this crew size a plumber leads and there's no separate supervisor
    "pm_percent": 10.0,  # project management and admin hours, as % of field hours
    "default_plumbers": 2,
    "stock_lengths": {"PVC DWV": 6, "PVC SWV": 6, "PVC pressure": 6, "Copper": 6, "PEX": 50, "HDPE": 6,
                      "Ductile iron": 6, "Stainless steel": 6, "Galvanised steel": 6.5, "Polypropylene": 6},
    "default_stock_length": 6,
    "shutdown_from": "12-20",  # MM-DD; the Christmas break, across the new year
    "shutdown_to": "01-12",
    "public_holidays": "QLD",
    "headcount": {"plumbers": 0, "apprentices": 0, "supervisors": 0},  # Peak's people, for the workforce forecast
}


def settings(db: Session) -> dict:
    s = db.get(AppSetting, SETTINGS_KEY)
    out = dict(DEFAULTS)
    if s and isinstance(s.value, dict):
        out.update(s.value)
    return out


# --- working days ---
def _easter(year: int) -> date:
    """Western Easter Sunday (anonymous Gregorian algorithm)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def _nth_monday(year: int, month: int, n: int) -> date:
    d = date(year, month, 1)
    d += timedelta(days=(7 - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


def holidays(year: int) -> set[date]:
    """Queensland public holidays (the ones that close sites)."""
    e = _easter(year)
    out = {date(year, 1, 1), date(year, 1, 26), date(year, 4, 25), date(year, 12, 25), date(year, 12, 26),
           e - timedelta(days=2), e - timedelta(days=1), e + timedelta(days=1),
           _nth_monday(year, 5, 1),  # Labour Day
           _nth_monday(year, 10, 1)}  # King's Birthday
    for d in list(out):  # a holiday on a weekend moves to the Monday
        if d.weekday() >= 5 and d.month in (1, 12):
            out.add(d + timedelta(days=7 - d.weekday()))
    return out


class Calendar:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self._hol: dict[int, set] = {}

    def _in_shutdown(self, d: date) -> bool:
        f, t = self.cfg.get("shutdown_from"), self.cfg.get("shutdown_to")
        if not f or not t:
            return False
        md = d.strftime("%m-%d")
        if f > t:  # the break runs over the new year
            return md >= f or md <= t
        return f <= md <= t

    def is_workday(self, d: date) -> bool:
        if d.weekday() >= int(self.cfg.get("days_per_week", 5)):
            return False
        if self.cfg.get("public_holidays") and d in self._hol.setdefault(d.year, holidays(d.year)):
            return False
        return not self._in_shutdown(d)

    def first_workday(self, d: date) -> date:
        while not self.is_workday(d):
            d += timedelta(days=1)
        return d

    def finish(self, start: date, workdays: int) -> date:
        """The last day of a task that starts on `start` and takes `workdays` working days."""
        d = self.first_workday(start)
        left = max(1, workdays) - 1
        while left:
            d += timedelta(days=1)
            if self.is_workday(d):
                left -= 1
        return d

    def next_workday(self, d: date) -> date:
        return self.first_workday(d + timedelta(days=1))


# --- labour hours ---
def _rates(db: Session, kind: str) -> list[ProductivityRate]:
    return list(db.scalars(select(ProductivityRate).where(ProductivityRate.kind == kind, ProductivityRate.active.is_(True))))


def _match_hydraulic(rates, kind: str, service_code: str, dn, material: str, item_type: str) -> ProductivityRate | None:
    best, best_score = None, -1
    for r in rates:
        if kind == "count":
            if not r.item_type or r.item_type.lower() != (item_type or "").lower():
                continue
            if r.service_code and r.service_code != service_code:
                continue
            score = 10 + (2 if r.service_code else 0)
        elif kind == "pipe":
            if r.item_type or (r.service_code and r.service_code != service_code):
                continue
            if r.dn_min is not None and (dn is None or dn < r.dn_min):
                continue
            if r.dn_max is not None and (dn is None or dn > r.dn_max):
                continue
            if r.material and r.material.lower() != (material or "").lower():
                continue
            score = (4 if r.service_code else 0) + (2 if r.dn_min is not None or r.dn_max is not None else 0) + (3 if r.material else 0)
        else:
            continue
        if score > best_score:
            best, best_score = r, score
    return best


def _match_civil(rates, category: str, unit: str, description: str) -> ProductivityRate | None:
    from .civil import norm_unit

    best, best_score = None, -1
    desc = (description or "").lower()
    for r in rates:
        if r.civil_category and r.civil_category != category:
            continue
        if r.unit and norm_unit(r.unit) != norm_unit(unit):
            continue
        if r.keyword and r.keyword.lower() not in desc:
            continue
        score = (4 if r.civil_category else 0) + (2 if r.unit else 0) + (5 if r.keyword else 0)
        if score > best_score:
            best, best_score = r, score
    return best


def labour(db: Session, job: Job, include_suggested: bool = False) -> dict:
    """Labour hours per line, by stage, with where each figure came from."""
    stages = {s.id: s for s in db.scalars(select(Stage))}
    order = {s.name: s.order for s in stages.values()}
    rows = []
    if (job.kind or "hydraulic") == "civil":
        from .civil import CATEGORIES, line_qty

        order = {c: i for i, c in enumerate(CATEGORIES)}
        rates = _rates(db, "civil")
        for l in db.scalars(select(CivilBoqLine).where(CivilBoqLine.job_id == job.id)):
            if l.status != "confirmed" and not include_suggested:
                continue
            qty = line_qty(l)
            r = _match_civil(rates, l.category, l.unit, l.description)
            hpu = r.hours_per_unit if r else None
            rows.append({"stage": l.category, "service_code": "", "kind": "boq", "description": l.description, "qty": qty, "uom": l.unit,
                         "hours_per_unit": hpu, "hours": round(qty * hpu, 2) if hpu is not None else 0.0,
                         "source": "productivity rate" if r else "no labour rate"})
    else:
        services = {s.id: s.code for s in db.scalars(select(Service))}
        version = db.get(PriceBookVersion, job.price_book_version_id) if job.price_book_version_id else None
        book = PriceBook(db, version) if version else None
        mappings = list(db.scalars(select(PriceMapping))) if book else []
        rates = _rates(db, "hydraulic")
        for src in collect_sources(db, job.id, include_suggested):
            code = services.get(src.service_id, "")
            stage = stages.get(src.stage_id)
            hpu, source = None, "no labour rate"
            if book:
                m = find_mapping(src, mappings, code)
                target = (m.target_kind, m.target_code, float(m.factor)) if m else (("item", src.catalogue_code, 1.0) if src.catalogue_code else None)
                if target:
                    uc = book.unit_cost(target[0], target[1])
                    if uc.labour_hours and not uc.missing:
                        hpu, source = float(uc.labour_hours) * target[2], "price book"
            if hpu is None:
                r = _match_hydraulic(rates, src.kind, code, src.dn, src.material, src.item_type)
                if r:
                    hpu, source = r.hours_per_unit, "productivity rate"
            qty = float(src.qty)
            rows.append({"stage": stage.name if stage else "Unstaged", "service_code": code, "kind": src.kind,
                         "description": src.description, "qty": round(qty, 2), "uom": src.uom, "hours_per_unit": hpu,
                         "hours": round(qty * hpu, 2) if hpu is not None else 0.0, "source": source})
    rows.sort(key=lambda r: (order.get(r["stage"], 999), r["service_code"], r["kind"], r["description"]))
    by_stage: dict[str, float] = defaultdict(float)
    by_service: dict[str, float] = defaultdict(float)
    for r in rows:
        by_stage[r["stage"]] += r["hours"]
        by_service[r["service_code"] or "-"] += r["hours"]
    missing = [r for r in rows if r["source"] == "no labour rate"]
    return {
        "rows": rows,
        "by_stage": [{"stage": k, "hours": round(v, 1)} for k, v in sorted(by_stage.items(), key=lambda kv: order.get(kv[0], 999))],
        "by_service": [{"service_code": k, "hours": round(v, 1)} for k, v in sorted(by_service.items())],
        "total_hours": round(sum(r["hours"] for r in rows), 1),
        "missing": len(missing),
        "stage_order": [k for k, _ in sorted(order.items(), key=lambda kv: kv[1])],
    }


# --- material list ---
def materials(db: Session, job: Job, include_suggested: bool = False, by_stage: bool = False) -> dict:
    """What to order: pipe in stock lengths, fittings and sundries, and fixtures / items."""
    cfg = settings(db)
    stock = cfg.get("stock_lengths") or {}
    rows = []
    if (job.kind or "hydraulic") == "civil":
        from .civil import line_qty

        for l in sorted(db.scalars(select(CivilBoqLine).where(CivilBoqLine.job_id == job.id)), key=lambda l: l.sort):
            if l.status != "confirmed" and not include_suggested:
                continue
            rows.append({"group": l.category, "stage": l.category, "description": l.description, "qty": line_qty(l), "uom": l.unit,
                         "order_qty": line_qty(l), "order_uom": l.unit, "code": "", "note": "" if l.status == "confirmed" else "not approved yet"})
        return {"rows": rows, "by_stage": by_stage}
    services = {s.id: s for s in db.scalars(select(Service))}
    stages = {s.id: s for s in db.scalars(select(Stage))}
    agg: dict[tuple, dict] = {}
    for src in collect_sources(db, job.id, include_suggested):
        svc = services.get(src.service_id)
        stage = stages.get(src.stage_id)
        stage_name = stage.name if stage else "Unstaged"
        group = {"pipe": "Pipe", "fitting": "Fittings and sundries", "count": "Fixtures and items"}[src.kind]
        key = (stage_name if by_stage else "", group, svc.code if svc else "", src.description, src.uom, src.catalogue_code)
        row = agg.setdefault(key, {"group": group, "stage": stage_name if by_stage else "", "service_code": svc.code if svc else "",
                                   "description": src.description, "qty": 0.0, "uom": src.uom, "code": src.catalogue_code,
                                   "material": src.material, "dn": src.dn, "_stage_order": stage.order if stage and by_stage else 0})
        row["qty"] += float(src.qty)
    for row in agg.values():
        row["qty"] = round(row["qty"], 2)
        if row["group"] == "Pipe":
            length = float(stock.get(row["material"], cfg.get("default_stock_length", 6)) or 6)
            row["order_qty"] = math.ceil(row["qty"] / length - 1e-9)
            row["order_uom"] = f"× {length:g} m lengths"
            row["note"] = "incl. waste"
        else:
            row["order_qty"] = math.ceil(row["qty"] - 1e-9) if row["uom"] in ("ea", "no") else row["qty"]
            row["order_uom"] = row["uom"]
            row["note"] = ""
        rows.append(row)
    group_order = {"Pipe": 0, "Fittings and sundries": 1, "Fixtures and items": 2}
    rows.sort(key=lambda r: (r["_stage_order"], group_order[r["group"]], r["service_code"], r.get("dn") or 0, r["description"]))
    for r in rows:
        r.pop("_stage_order", None)
    return {"rows": rows, "by_stage": by_stage}


# --- crew and program ---
def crew_for(plumbers: int, cfg: dict) -> dict:
    apprentices = math.floor(plumbers * float(cfg["apprentice_ratio"]) + 1e-9)  # whole people, never over the ratio
    crew = plumbers + apprentices
    sup = math.ceil(crew / float(cfg["workers_per_supervisor"])) if crew >= int(cfg["supervisor_from_crew"]) else 0
    return {"plumbers": plumbers, "apprentices": apprentices, "supervisors": sup,
            "effective": plumbers + apprentices * float(cfg["apprentice_productivity"])}


def plumbers_for(hours: float, workdays: int, cfg: dict) -> int:
    """The fewest plumbers (with their apprentices) that get `hours` done in `workdays`."""
    if hours <= 0 or workdays <= 0:
        return 0
    need = hours / (workdays * float(cfg["hours_per_day"]))
    p = 1
    while crew_for(p, cfg)["effective"] < need - 1e-9 and p < 500:
        p += 1
    return p


def program(db: Session, job: Job, include_suggested: bool = False) -> dict:
    """Stage-by-stage program: crew, dates, durations, weekly manpower, management and cash flow."""
    cfg = settings(db)
    cal = Calendar(cfg)
    lab = labour(db, job, include_suggested)
    prog = job.program or {}
    stage_cfg = prog.get("stages") or {}
    hpd = float(cfg["hours_per_day"])
    start = job.start_date or date.today()
    stages = [s for s in lab["by_stage"] if s["hours"] > 0]
    total_hours = sum(s["hours"] for s in stages)

    mode = "target" if job.target_weeks else "crew"
    if mode == "target":
        workdays = max(1, math.floor(float(job.target_weeks) * int(cfg["days_per_week"]) + 1e-9))
        base_plumbers = max(1, plumbers_for(total_hours, workdays, cfg))
        # Each stage takes whole days, so add people until the stages really fit in the target.
        def days_with(p):
            eff = crew_for(p, cfg)["effective"] * hpd
            return sum(max(1, math.ceil(s["hours"] / eff - 1e-9)) for s in stages)
        while days_with(base_plumbers) > workdays and base_plumbers < 200 and days_with(base_plumbers + 1) < days_with(base_plumbers):
            base_plumbers += 1
    else:
        base_plumbers = int(prog.get("plumbers") or cfg["default_plumbers"])

    out_stages, cursor = [], cal.first_workday(start)
    for s in stages:
        sc = stage_cfg.get(s["stage"], {})
        p = int(sc.get("plumbers") or base_plumbers)
        crew = crew_for(p, cfg)
        days = max(1, math.ceil(s["hours"] / (crew["effective"] * hpd) - 1e-9))
        st = date.fromisoformat(sc["start"]) if sc.get("start") else cursor
        st = cal.first_workday(st)
        if sc.get("gap_days"):
            for _ in range(int(sc["gap_days"])):
                st = cal.next_workday(st)
        end = cal.finish(st, days)
        out_stages.append({"stage": s["stage"], "hours": s["hours"], **crew, "workdays": days,
                           "start": st.isoformat(), "end": end.isoformat(), "start_overridden": bool(sc.get("start"))})
        cursor = cal.next_workday(end)

    finish = max((date.fromisoformat(s["end"]) for s in out_stages), default=start)
    first = min((date.fromisoformat(s["start"]) for s in out_stages), default=start)
    field_hours = total_hours
    pm_hours = round(field_hours * float(cfg["pm_percent"]) / 100, 1)
    sup_hours = round(sum(s["supervisors"] * s["workdays"] * hpd for s in out_stages), 1)

    # Weekly manpower: people on site each week (Monday dates), by role.
    weeks: dict[date, dict] = {}
    for s in out_stages:
        d, e = date.fromisoformat(s["start"]), date.fromisoformat(s["end"])
        while d <= e:
            if cal.is_workday(d):
                wk = d - timedelta(days=d.weekday())
                w = weeks.setdefault(wk, {"week": wk.isoformat(), "plumbers": 0, "apprentices": 0, "supervisors": 0, "hours": 0.0, "stages": set()})
                w["plumbers"] = max(w["plumbers"], s["plumbers"])
                w["apprentices"] = max(w["apprentices"], s["apprentices"])
                w["supervisors"] = max(w["supervisors"], s["supervisors"])
                w["hours"] += s["hours"] / s["workdays"]
                w["stages"].add(s["stage"])
            d += timedelta(days=1)
    weekly = []
    for wk in sorted(weeks):
        w = weeks[wk]
        weekly.append({**w, "hours": round(w["hours"], 1), "stages": sorted(w["stages"])})
    working_days = sum(s["workdays"] for s in out_stages)
    working_weeks = round(working_days / int(cfg["days_per_week"]), 1)
    peak = max((w["plumbers"] + w["apprentices"] + w["supervisors"] for w in weekly), default=0)

    return {
        "mode": mode, "target_weeks": job.target_weeks, "start_date": first.isoformat() if out_stages else start.isoformat(),
        "finish_date": finish.isoformat(), "calendar_weeks": round(((finish - first).days + 1) / 7, 1) if out_stages else 0,
        "working_days": working_days, "working_weeks": working_weeks, "weeks_on_site": len(weekly),
        "stages": out_stages, "weekly": weekly, "field_hours": round(field_hours, 1), "supervision_hours": sup_hours,
        "pm_hours": pm_hours, "pm_hours_per_week": round(pm_hours / working_weeks, 1) if working_weeks else 0,
        "peak_people": peak, "base_plumbers": base_plumbers, "missing_labour_rates": lab["missing"],
        "settings": {k: cfg[k] for k in ("hours_per_day", "days_per_week", "apprentice_ratio", "apprentice_productivity",
                                          "workers_per_supervisor", "supervisor_from_crew", "pm_percent")},
        "cashflow": cashflow(db, job, out_stages, cal, include_suggested),
    }


def cashflow(db: Session, job: Job, stages: list[dict], cal: Calendar, include_suggested: bool) -> list[dict]:
    """Value earned each month (for progress claims), spreading each stage's value over its working days."""
    value: dict[str, float] = {}
    if (job.kind or "hydraulic") == "civil":
        from .civil import line_qty, money

        for l in db.scalars(select(CivilBoqLine).where(CivilBoqLine.job_id == job.id)):
            if l.status == "confirmed" or include_suggested:
                value[l.category] = value.get(l.category, 0.0) + float(money(line_qty(l)) * money(l.rate or 0))
    elif job.price_book_version_id:
        from .pricing import price_job

        p = price_job(db, job.id)
        if p["summary"]:
            value = {s["stage"]: float(s["sell"]) for s in p["summary"]["by_stage"]}
    if not value:
        return []
    months: dict[str, float] = defaultdict(float)
    for s in stages:
        v = value.get(s["stage"], 0.0)
        days = [d for d in (date.fromisoformat(s["start"]) + timedelta(days=i)
                            for i in range((date.fromisoformat(s["end"]) - date.fromisoformat(s["start"])).days + 1)) if cal.is_workday(d)]
        for d in days:
            months[d.strftime("%Y-%m")] += v / len(days)
    run = 0.0
    out = []
    for m in sorted(months):
        run += months[m]
        out.append({"month": m, "value": round(months[m], 2), "cumulative": round(run, 2)})
    return out


# --- the company view ---
def dashboard(db: Session, jobs: list[Job], horizon_weeks: int = 26, include_pending: bool = False) -> dict:
    cfg = settings(db)
    today = date.today()
    by_result: dict[str, dict] = defaultdict(lambda: {"count": 0, "value": 0.0})
    by_month: dict[str, dict] = defaultdict(lambda: {"submitted": 0.0, "won": 0.0, "count": 0})
    for j in jobs:
        r = j.tender_result or "pending"
        by_result[r]["count"] += 1
        by_result[r]["value"] += j.tender_value or 0.0
        if j.created_at:
            m = j.created_at.strftime("%Y-%m")
            by_month[m]["count"] += 1
            by_month[m]["submitted"] += j.tender_value or 0.0
            if r == "won":
                by_month[m]["won"] += j.tender_value or 0.0
    decided = by_result["won"]["count"] + by_result["lost"]["count"]
    win_rate = round(100 * by_result["won"]["count"] / decided, 1) if decided else None
    due = sorted(({"job_id": j.id, "name": j.name, "kind": j.kind, "due_date": j.due_date.isoformat(), "status": j.status}
                  for j in jobs if j.due_date and today <= j.due_date <= today + timedelta(days=14) and (j.tender_result or "pending") == "pending"),
                 key=lambda x: x["due_date"])

    # Workforce: people needed each week across won (and optionally pending) jobs with a start date.
    start_week = today - timedelta(days=today.weekday())
    weeks = [start_week + timedelta(weeks=i) for i in range(horizon_weeks)]
    load = {w: {"plumbers": 0, "apprentices": 0, "supervisors": 0, "jobs": []} for w in weeks}
    planned = []
    for j in jobs:
        if not j.start_date or (j.tender_result or "pending") not in (("won", "pending") if include_pending else ("won",)):
            continue
        p = program(db, j)
        planned.append({"job_id": j.id, "name": j.name, "result": j.tender_result, "start": p["start_date"], "finish": p["finish_date"],
                        "peak_people": p["peak_people"]})
        for w in p["weekly"]:
            wk = date.fromisoformat(w["week"])
            if wk in load:
                for role in ("plumbers", "apprentices", "supervisors"):
                    load[wk][role] += w[role]
                load[wk]["jobs"].append(j.name)
    head = cfg.get("headcount") or {}
    workforce = [{"week": w.isoformat(), **load[w],
                  "short": {r: max(0, load[w][r] - int(head.get(r) or 0)) for r in ("plumbers", "apprentices", "supervisors")}
                  if any(head.values()) else None} for w in weeks]

    outcomes: dict[str, int] = defaultdict(int)
    for o in db.scalars(select(AiOutcome).where(AiOutcome.job_id.in_([j.id for j in jobs]))):
        outcomes[o.outcome] += 1
    plans = list(db.scalars(select(Sheet).where(Sheet.job_id.in_([j.id for j in jobs]), Sheet.classification == "plan",
                                                Sheet.is_hydraulic.is_(True), Sheet.is_current.is_(True))))
    auto = sum(1 for s in plans if (s.verification_data or {}).get("method") == "auto_dimensions" and s.scale_verified)
    judged = sum(outcomes.values())
    exclusions = defaultdict(int)
    for a in db.scalars(select(JobAllowance).where(JobAllowance.kind == "exclusion", JobAllowance.job_id.in_([j.id for j in jobs]))):
        exclusions[a.description] += 1
    return {
        "jobs": len(jobs),
        "by_result": dict(by_result), "win_rate_pct": win_rate,
        "by_month": [{"month": m, **v} for m, v in sorted(by_month.items())][-12:],
        "due_soon": due,
        "workforce": workforce, "planned_jobs": planned, "headcount": head,
        "ai": {"suggestions_accepted": outcomes["accepted"], "suggestions_edited": outcomes["edited"],
               "suggestions_rejected": outcomes["rejected"],
               "accepted_pct": round(100 * (outcomes["accepted"] + outcomes["edited"]) / judged, 1) if judged else None,
               "plans": len(plans), "scales_auto_confirmed": auto,
               "auto_scale_pct": round(100 * auto / len(plans), 1) if plans else None},
        "common_exclusions": sorted(({"description": k, "jobs": v} for k, v in exclusions.items()), key=lambda x: -x["jobs"])[:10],
    }
