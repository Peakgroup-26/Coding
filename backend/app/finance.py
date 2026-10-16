"""Money: each job's budget against actuals, the WIP report, month-to-date against forecast, cash flow.

Everything is worked out from the records the rest of the app keeps, so it's always current:
  labour actual     approved / submitted time x the person's cost rate (frozen when approved)
  material actual   billed POs (the bill), received POs not yet billed (the PO value), other job costs
  committed         POs sent but not yet received or billed
  revenue           contract value + approved variations (fixed price), or cost-plus (do-and-charge)
  invoiced          invoices sent or paid
All amounts are ex GST.
"""
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import ops
from .models import BudgetLine, BudgetMonth, Invoice, Job, JobCost, PurchaseOrder, ScheduleEntry, TimeEntry, User, Variation
from .reports import Calendar
from .reports import settings as workforce_settings

COST_CATS = ops.CATEGORIES  # labour, materials, subcontract, plant, other


def _r(x: float) -> float:
    return round(x or 0.0, 2)


def entry_hours(e: TimeEntry, now: datetime | None = None) -> float:
    end = e.end_at or now or datetime.now(timezone.utc)
    start = e.start_at if e.start_at.tzinfo else e.start_at.replace(tzinfo=timezone.utc)
    end = end if end.tzinfo else end.replace(tzinfo=timezone.utc)
    return max(0.0, (end - start).total_seconds() / 3600 - (e.break_minutes or 0) / 60)


def entry_cost(db: Session, e: TimeEntry, rates: dict[int, float]) -> float:
    rate = e.cost_rate if e.cost_rate is not None else rates.get(e.user_id) or float(ops.settings(db)["default_cost_rate"])
    return entry_hours(e) * rate


def _rates(db: Session) -> dict[int, float]:
    return {u.id: u.cost_rate for u in db.scalars(select(User)) if u.cost_rate}


def _plant_rates(db: Session) -> dict[int, float]:
    from .models import Plant

    return {p.id: p.hire_rate for p in db.scalars(select(Plant)) if p.hire_rate}


def po_value(po: PurchaseOrder) -> float:
    return sum(l.qty * l.unit_cost for l in po.lines)


def po_actual(po: PurchaseOrder) -> tuple[float, float]:
    """(actual, committed) for one PO."""
    if po.status == "cancelled":
        return 0.0, 0.0
    if po.status == "billed":
        return (po.bill_amount if po.bill_amount is not None else po_value(po)), 0.0
    if po.status == "received":
        return po_value(po), 0.0
    if po.status == "sent":
        return 0.0, po_value(po)
    return 0.0, 0.0  # draft: not committed yet


def job_actuals(db: Session, job: Job) -> dict:
    rates = _rates(db)
    actual = defaultdict(float)
    committed = defaultdict(float)
    hours = 0.0
    plant_rates = _plant_rates(db)
    for e in db.scalars(select(TimeEntry).where(TimeEntry.job_id == job.id, TimeEntry.status != "rejected")):
        h = entry_hours(e)
        hours += h
        actual["labour"] += entry_cost(db, e, rates)
        if e.plant_id:
            actual["plant"] += h * plant_rates.get(e.plant_id, 0.0)
    for c in db.scalars(select(JobCost).where(JobCost.job_id == job.id)):
        actual[c.category if c.category in COST_CATS else "other"] += c.amount
    for po in db.scalars(select(PurchaseOrder).where(PurchaseOrder.job_id == job.id)):
        a, cm = po_actual(po)
        cat = po.category if po.category in COST_CATS else "materials"
        actual[cat] += a
        committed[cat] += cm
    return {"actual": dict(actual), "committed": dict(committed), "hours": hours}


def job_financials(db: Session, job: Job) -> dict:
    cfg = ops.settings(db)
    budget = defaultdict(float)
    budget_hours = 0.0
    for b in db.scalars(select(BudgetLine).where(BudgetLine.job_id == job.id)):
        budget[b.category] += b.cost
        if b.category == "labour":
            budget_hours += b.hours
    variations = list(db.scalars(select(Variation).where(Variation.job_id == job.id)))
    approved = [v for v in variations if v.status == "approved"]
    pending = [v for v in variations if v.status in ("pending", "submitted")]
    a = job_actuals(db, job)
    rows = []
    for cat in COST_CATS:
        bud, act, com = budget.get(cat, 0.0), a["actual"].get(cat, 0.0), a["committed"].get(cat, 0.0)
        forecast = max(bud, act + com)
        rows.append({"category": cat, "label": ops.CATEGORY_LABELS[cat], "budget": _r(bud), "actual": _r(act), "committed": _r(com),
                     "forecast": _r(forecast), "to_complete": _r(forecast - act - com), "variance": _r(bud - forecast)})
    budget_total = sum(r["budget"] for r in rows)
    cost_to_date = sum(r["actual"] for r in rows)
    committed = sum(r["committed"] for r in rows)
    forecast_cost = sum(r["forecast"] for r in rows)
    invoices = list(db.scalars(select(Invoice).where(Invoice.job_id == job.id, Invoice.status.in_(("sent", "paid")))))
    invoiced = sum(i.amount for i in invoices)
    retention = sum(i.retention for i in invoices)
    received = sum(i.paid_amount for i in invoices)

    if job.billing == "charge":
        # Do-and-charge: what we can bill is the time at charge-out rates plus costs with markup.
        charge = defaultdict(float)
        for e in db.scalars(select(TimeEntry).where(TimeEntry.job_id == job.id, TimeEntry.status != "rejected")):
            u = db.get(User, e.user_id)
            charge["labour"] += entry_hours(e) * ((u.charge_rate if u and u.charge_rate else None) or float(cfg.get("default_charge_rate", 110)))
        markup = 1 + float(cfg.get("charge_materials_markup_pct", 25)) / 100
        itemised = list(db.scalars(select(JobCost).where(JobCost.job_id == job.id, JobCost.sell_unit.is_not(None))))
        sold = sum(c.qty * c.sell_unit for c in itemised)
        earned = charge["labour"] + sold + max(0.0, cost_to_date - a["actual"].get("labour", 0.0) - sum(c.amount for c in itemised)) * markup
        contract = max(job.contract_value or 0.0, earned)  # a quoted not-to-exceed stays the floor for the forecast
        pct = 100.0 if job.work_status in ("complete", "invoiced", "closed") else (min(100.0, 100 * earned / contract) if contract else 0.0)
    else:
        contract = (job.contract_value or 0.0) + sum(v.sell for v in approved)
        if job.work_status in ("complete", "invoiced", "closed"):
            pct = 100.0
        elif job.percent_complete is not None:
            pct = job.percent_complete
            if pct > 0:
                forecast_cost = max(forecast_cost, cost_to_date / (pct / 100), cost_to_date + committed)
        else:  # cost to cost; with no budget yet there's nothing to measure against
            pct = min(100.0, 100 * cost_to_date / forecast_cost) if forecast_cost and budget_total else 0.0
        earned = contract * pct / 100
    margin = contract - forecast_cost
    return {
        "contract": _r(job.contract_value or 0.0), "variations_approved": _r(sum(v.sell for v in approved)),
        "variations_pending": _r(sum(v.sell for v in pending)), "revenue": _r(contract),
        "budget_cost": _r(budget_total), "budget_margin": _r(contract - budget_total),
        "budget_margin_pct": round(100 * (contract - budget_total) / contract, 1) if contract else None,
        "cost_to_date": _r(cost_to_date), "committed": _r(committed), "forecast_cost": _r(forecast_cost),
        "cost_to_complete": _r(max(0.0, forecast_cost - cost_to_date)),
        "forecast_margin": _r(margin), "forecast_margin_pct": round(100 * margin / contract, 1) if contract else None,
        "percent_complete": round(pct, 1), "percent_basis": "manual" if job.percent_complete is not None and job.billing != "charge" else
        ("charge" if job.billing == "charge" else "cost"),
        "earned": _r(earned), "invoiced": _r(invoiced), "received": _r(received), "retention_held": _r(retention),
        "over_under_billed": _r(invoiced - earned),  # + billed ahead of the work, - work not yet billed
        "to_invoice": _r(max(0.0, contract - invoiced)),
        "hours_budget": round(budget_hours, 1), "hours_actual": round(a["hours"], 1),
        "categories": rows,
        "over_budget": forecast_cost > budget_total + 0.5 and budget_total > 0,
    }


def quick(db: Session, job: Job) -> dict:
    f = job_financials(db, job)
    keep = ("revenue", "cost_to_date", "forecast_margin_pct", "percent_complete", "invoiced", "hours_budget", "hours_actual",
            "over_budget", "over_under_billed", "budget_margin_pct")
    return {k: f[k] for k in keep}


def wip(db: Session, jobs: list[Job]) -> dict:
    rows, totals = [], defaultdict(float)
    for j in jobs:
        f = job_financials(db, j)
        rows.append({"job_id": j.id, "job_no": j.job_no, "name": j.name, "customer": j.client, "sector": j.sector, "kind": j.kind,
                     "status": j.work_status, **{k: f[k] for k in ("revenue", "budget_cost", "cost_to_date", "committed", "forecast_cost",
                                                                  "cost_to_complete", "forecast_margin", "forecast_margin_pct",
                                                                  "budget_margin_pct", "percent_complete", "earned", "invoiced",
                                                                  "over_under_billed", "retention_held", "over_budget")}})
        for k in ("revenue", "budget_cost", "cost_to_date", "committed", "forecast_cost", "cost_to_complete", "forecast_margin", "earned",
                  "invoiced", "over_under_billed", "retention_held"):
            totals[k] += f[k]
    totals = {k: _r(v) for k, v in totals.items()}
    totals["forecast_margin_pct"] = round(100 * totals["forecast_margin"] / totals["revenue"], 1) if totals.get("revenue") else None
    totals["under_billed"] = _r(-sum(r["over_under_billed"] for r in rows if r["over_under_billed"] < 0))
    totals["over_billed"] = _r(sum(r["over_under_billed"] for r in rows if r["over_under_billed"] > 0))
    return {"rows": sorted(rows, key=lambda r: r["job_no"]), "totals": totals}


# --- monthly forecast (company budget) ---
def _month_bounds(month: str) -> tuple[date, date]:
    y, m = map(int, month.split("-"))
    start = date(y, m, 1)
    end = (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1))
    return start, end


def calendar(db: Session) -> Calendar:
    return Calendar(workforce_settings(db))


def workdays(cal: Calendar, a: date, b: date) -> int:
    n, d = 0, a
    while d <= b:
        n += cal.is_workday(d)
        d += timedelta(days=1)
    return n


def jobs_forecast(db: Session, jobs: list[Job], months: list[str], today: date | None = None) -> dict[str, dict]:
    """What the live jobs say each month will bring: their remaining revenue and cost spread over working days to the finish date."""
    today = today or date.today()
    cal = calendar(db)
    out = {m: defaultdict(float) for m in months}
    for j in jobs:
        if j.work_status not in ops.ACTIVE:
            continue
        f = job_financials(db, j)
        start = max(j.start_date or today, today)
        finish = j.finish_date or (start + timedelta(days=28))
        if finish < start:
            finish = start
        total_days = max(1, workdays(cal, start, finish))
        remaining = {"revenue": max(0.0, f["revenue"] - f["earned"])}
        for row in f["categories"]:
            remaining[row["category"]] = max(0.0, row["forecast"] - row["actual"])
        for m in months:
            ms, me = _month_bounds(m)
            days = workdays(cal, max(ms, start), min(me, finish)) if max(ms, start) <= min(me, finish) else 0
            if not days:
                continue
            share = days / total_days
            for k, v in remaining.items():
                out[m][k] += v * share
    return {m: {k: _r(v) for k, v in d.items()} for m, d in out.items()}


def budget_for(db: Session, month: str) -> dict | None:
    b = db.scalar(select(BudgetMonth).where(BudgetMonth.month == month))
    if b is None:
        return None
    return {"revenue": b.revenue, "labour": b.labour, "materials": b.materials, "subcontract": b.subcontract, "overheads": b.overheads,
            "notes": b.notes}


def month_actuals(db: Session, jobs: list[Job], start: date, end: date) -> dict:
    """Labour, materials, subcontract, other and revenue that actually happened between two dates, with the jobs behind them."""
    ids = {j.id for j in jobs}
    rates = _rates(db)
    plant_rates = _plant_rates(db)
    tot = defaultdict(float)
    per_job: dict[int, dict] = defaultdict(lambda: defaultdict(float))
    lo = datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)
    hi = datetime.combine(end + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)
    for e in db.scalars(select(TimeEntry).where(TimeEntry.start_at >= lo, TimeEntry.start_at < hi, TimeEntry.status != "rejected")):
        if e.job_id is not None and e.job_id not in ids:
            continue
        c = entry_cost(db, e, rates)
        tot["labour"] += c
        tot["hours"] += entry_hours(e)
        if e.job_id:
            per_job[e.job_id]["labour"] += c
        if e.plant_id and plant_rates.get(e.plant_id):
            pc = entry_hours(e) * plant_rates[e.plant_id]
            tot["plant"] += pc
            if e.job_id:
                per_job[e.job_id]["plant"] += pc
    for c in db.scalars(select(JobCost).where(JobCost.day >= start, JobCost.day <= end)):
        if c.job_id not in ids:
            continue
        cat = c.category if c.category in COST_CATS else "other"
        tot[cat] += c.amount
        per_job[c.job_id][cat] += c.amount
    for po in db.scalars(select(PurchaseOrder).where(PurchaseOrder.status.in_(("received", "billed")))):
        if po.job_id is not None and po.job_id not in ids:
            continue
        when = po.bill_date if po.status == "billed" and po.bill_date else (po.required_date or po.order_date or po.created_at.date())
        if not (start <= when <= end):
            continue
        a, _ = po_actual(po)
        cat = po.category if po.category in COST_CATS else "materials"
        tot[cat] += a
        if po.job_id:
            per_job[po.job_id][cat] += a
    for inv in db.scalars(select(Invoice).where(Invoice.issue_date >= start, Invoice.issue_date <= end, Invoice.status.in_(("sent", "paid")))):
        if inv.job_id is not None and inv.job_id not in ids:
            continue
        tot["revenue"] += inv.amount
        if inv.job_id:
            per_job[inv.job_id]["revenue"] += inv.amount
    return {"totals": {k: _r(v) for k, v in tot.items()}, "per_job": {k: {kk: _r(vv) for kk, vv in v.items()} for k, v in per_job.items()}}


def month_to_date(db: Session, jobs: list[Job], today: date | None = None) -> dict:
    """This month so far against the forecast pro-rated to today (by working days), for revenue, labour and materials."""
    today = today or date.today()
    month = today.strftime("%Y-%m")
    ms, me = _month_bounds(month)
    cal = calendar(db)
    total_days = max(1, workdays(cal, ms, me))
    elapsed = workdays(cal, ms, today)
    frac = elapsed / total_days
    budget = budget_for(db, month)
    derived = jobs_forecast(db, jobs, [month], today=ms)[month]
    source = "budget" if budget else "jobs"
    fc = budget or {"revenue": derived.get("revenue", 0.0), "labour": derived.get("labour", 0.0),
                    "materials": derived.get("materials", 0.0), "subcontract": derived.get("subcontract", 0.0), "overheads": 0.0}
    act = month_actuals(db, jobs, ms, today)
    tol = float(ops.settings(db)["tolerance_pct"]) / 100
    lines = []
    for key, label, is_cost in (("revenue", "Revenue (invoiced)", False), ("labour", "Labour", True), ("materials", "Materials", True),
                                ("subcontract", "Subcontractors", True)):
        forecast = float(fc.get(key) or 0.0)
        pro = forecast * frac
        actual = act["totals"].get(key, 0.0)
        if is_cost and key == "materials":
            actual += act["totals"].get("plant", 0.0) + act["totals"].get("other", 0.0)
        var = actual - pro
        if not forecast:
            state = "none"
        elif is_cost:
            state = "over" if actual > pro * (1 + tol) else ("under" if actual < pro * (1 - tol) else "on")
        else:
            state = "behind" if actual < pro * (1 - tol) else ("ahead" if actual > pro * (1 + tol) else "on")
        lines.append({"key": key, "label": label, "forecast": _r(forecast), "prorated": _r(pro), "actual": _r(actual), "variance": _r(var),
                      "pct_of_prorated": round(100 * actual / pro, 1) if pro else None, "state": state, "is_cost": is_cost,
                      "projected": _r(actual / frac) if frac else None})
    names = {j.id: (j.job_no, j.name) for j in jobs}
    drivers = sorted(({"job_id": k, "job_no": names.get(k, ("", ""))[0], "name": names.get(k, ("", ""))[1], **v}
                      for k, v in act["per_job"].items()), key=lambda r: -(r.get("labour", 0) + r.get("materials", 0)))
    return {"month": month, "today": today.isoformat(), "workdays_total": total_days, "workdays_elapsed": elapsed,
            "fraction": round(frac, 3), "forecast_source": source, "lines": lines, "hours": act["totals"].get("hours", 0.0),
            "drivers": drivers[:20], "tolerance_pct": tol * 100}


# --- cash flow forecast ---
def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _supplier_due(d: date, terms_days: int) -> date:
    """Trade accounts: due `terms` days after the end of the month of the bill (30 days EOM)."""
    eom = (date(d.year + (d.month == 12), d.month % 12 + 1, 1) - timedelta(days=1))
    return eom + timedelta(days=terms_days)


def cashflow(db: Session, jobs: list[Job], weeks: int = 13, today: date | None = None, opening: float | None = None) -> dict:
    """Week-by-week money in and out, with the running bank balance. Ex GST."""
    from .models import Customer, Supplier

    today = today or date.today()
    cfg = ops.settings(db)
    w0 = _monday(today)
    buckets = [{"week": (w0 + timedelta(weeks=i)).isoformat(), "in_invoices": 0.0, "in_forecast": 0.0, "out_wages": 0.0,
                "out_suppliers": 0.0, "out_forecast": 0.0, "out_overheads": 0.0} for i in range(weeks)]
    end = w0 + timedelta(weeks=weeks)

    def put(d: date, key: str, amount: float):
        if not amount:
            return
        i = max(0, (_monday(d) - w0).days // 7)
        if i < weeks:
            buckets[i][key] += amount

    customers = {c.id: c for c in db.scalars(select(Customer))}
    suppliers = {s.id: s for s in db.scalars(select(Supplier))}
    default_terms = int(cfg["default_terms_days"])
    ids = {j.id for j in jobs}
    # Money owed to us
    for inv in db.scalars(select(Invoice).where(Invoice.status == "sent")):
        if inv.job_id is not None and inv.job_id not in ids:
            continue
        put(max(inv.due_date, today), "in_invoices", inv.amount - inv.retention - (inv.paid_amount or 0))
    # Work still to be billed: the remaining contract claimed evenly to the finish date, paid after terms
    for j in jobs:
        if j.work_status not in ops.ACTIVE:
            continue
        f = job_financials(db, j)
        cust = customers.get(j.customer_id) if j.customer_id else None
        terms = j.payment_terms_days if j.payment_terms_days is not None else (cust.terms_days if cust else default_terms)
        left = f["revenue"] - f["invoiced"]
        if left <= 0:
            continue
        retention = left * (j.retention_pct or 0) / 100
        left -= retention
        start = max(j.start_date or today, today)
        finish = max(j.finish_date or (start + timedelta(days=28)), start)
        n = max(1, (finish - start).days // 7 + 1)
        for k in range(n):
            put(start + timedelta(weeks=k) + timedelta(days=terms), "in_forecast", left / n)
        # remaining cost to spend
        for row in f["categories"]:
            rem = max(0.0, row["forecast"] - row["actual"] - row["committed"])
            if row["category"] == "labour":
                continue  # wages come from the schedule / labour forecast below
            for k in range(n):
                put(start + timedelta(weeks=k) + timedelta(days=30), "out_forecast", rem / n)
    # Wages: the schedule where there is one, else each job's remaining labour
    rates = _rates(db)
    sched_weeks = set()
    for s in db.scalars(select(ScheduleEntry).where(ScheduleEntry.day >= w0, ScheduleEntry.day < end, ScheduleEntry.kind == "work")):
        h = _hours_between(s.start, s.end) - 0.5
        put(s.day + timedelta(days=7), "out_wages", max(0.0, h) * (rates.get(s.user_id) or float(cfg["default_cost_rate"])))
        sched_weeks.add(_monday(s.day))
    for j in jobs:
        if j.work_status not in ops.ACTIVE:
            continue
        f = job_financials(db, j)
        lab = next(r for r in f["categories"] if r["category"] == "labour")
        rem = max(0.0, lab["forecast"] - lab["actual"])
        start = max(j.start_date or today, today)
        finish = max(j.finish_date or (start + timedelta(days=28)), start)
        weeks_list = [start + timedelta(weeks=k) for k in range((finish - start).days // 7 + 1)]
        free = [w for w in weeks_list if _monday(w) not in sched_weeks] or []
        for w in free:
            put(w + timedelta(days=7), "out_wages", rem / max(1, len(weeks_list)))
    # Money we owe suppliers
    for po in db.scalars(select(PurchaseOrder).where(PurchaseOrder.status.in_(("sent", "received", "billed")), PurchaseOrder.bill_paid.is_(None))):
        if po.job_id is not None and po.job_id not in ids:
            continue
        sup = suppliers.get(po.supplier_id) if po.supplier_id else None
        terms = sup.terms_days if sup else 30
        if po.status == "billed":
            due = po.bill_due or _supplier_due(po.bill_date or today, terms)
            put(max(due, today), "out_suppliers", po.bill_amount if po.bill_amount is not None else po_value(po))
        else:
            put(max(_supplier_due(po.required_date or po.order_date or today, terms), today), "out_suppliers", po_value(po))
    for c in db.scalars(select(JobCost).where(JobCost.paid_date.is_(None), JobCost.due_date.is_not(None))):
        if c.job_id in ids:
            put(max(c.due_date, today), "out_suppliers", c.amount)
    # Overheads from the monthly budget
    for i in range(weeks):
        wk = w0 + timedelta(weeks=i)
        b = budget_for(db, wk.strftime("%Y-%m"))
        if b and b["overheads"]:
            ms, me = _month_bounds(wk.strftime("%Y-%m"))
            buckets[i]["out_overheads"] += b["overheads"] * 7 / ((me - ms).days + 1)
    bal = float(opening if opening is not None else cfg.get("opening_bank_balance") or 0.0)
    low = None
    for b in buckets:
        b["in_total"] = _r(b["in_invoices"] + b["in_forecast"])
        b["out_total"] = _r(b["out_wages"] + b["out_suppliers"] + b["out_forecast"] + b["out_overheads"])
        b["net"] = _r(b["in_total"] - b["out_total"])
        bal += b["net"]
        b["balance"] = _r(bal)
        for k in ("in_invoices", "in_forecast", "out_wages", "out_suppliers", "out_forecast", "out_overheads"):
            b[k] = _r(b[k])
        if low is None or b["balance"] < low["balance"]:
            low = {"week": b["week"], "balance": b["balance"]}
    return {"opening": _r(float(opening if opening is not None else cfg.get("opening_bank_balance") or 0.0)),
            "opening_date": cfg.get("opening_balance_date") or "", "weeks": buckets, "lowest": low,
            "in_total": _r(sum(b["in_total"] for b in buckets)), "out_total": _r(sum(b["out_total"] for b in buckets))}


def _hours_between(a: str, b: str) -> float:
    try:
        ha, ma = map(int, a.split(":"))
        hb, mb = map(int, b.split(":"))
    except ValueError:
        return 0.0
    return max(0.0, (hb * 60 + mb - ha * 60 - ma) / 60)
