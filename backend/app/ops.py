"""Live jobs: turning a won quote into a job, raising maintenance jobs, customers and sites, job budgets.

One job record carries a job from lead to closed: the estimate and sales fields are the quote side,
`work_status` and the tables hanging off the job (schedule, time, POs, costs, variations, invoices,
documents, project items) are the delivery side. A job with an empty work_status is still a quote.
"""
from datetime import date, datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import AppSetting, BudgetLine, CivilBoqLine, Counter, Customer, Job, Site, User

WORK_STATUSES = ["scheduled", "in_progress", "on_hold", "complete", "invoiced", "closed"]
WORK_LABELS = {"scheduled": "Scheduled", "in_progress": "In progress", "on_hold": "On hold", "complete": "Complete",
               "invoiced": "Invoiced", "closed": "Closed"}
ACTIVE = ("scheduled", "in_progress", "on_hold", "complete")  # still costing / to be invoiced
CATEGORIES = ["labour", "materials", "subcontract", "plant", "other"]
CATEGORY_LABELS = {"labour": "Labour", "materials": "Materials", "subcontract": "Subcontractors", "plant": "Plant & equipment",
                   "other": "Other"}
TRADES = ["plumber", "apprentice", "labourer", "supervisor", "project manager", "office", "manager"]
PRIORITIES = ["low", "normal", "high", "urgent"]

DEFAULTS = {
    "job_prefix": "J",
    "invoice_prefix": "INV-",
    "default_terms_days": 14,  # customer payment terms when the customer has none
    "default_cost_rate": 65.0,  # $/h for staff with no cost rate set
    "default_charge_rate": 110.0,  # $/h charged on do-and-charge jobs
    "charge_materials_markup_pct": 25.0,  # do-and-charge: materials and other costs marked up by this
    "stock_markup_pct": 30.0,  # materials used from stock: price-file cost plus this
    "markup_by_group": {},  # {"Hot water": 15, "Tapware": 35}: product groups with their own margin
    "civil_budget_margin_pct": 15.0,  # civil BOQs are priced at sell rates: budget = BOQ x (1 - this)
    "company_name": "Peak Plumbing & Gas Services",
    "google_review_url": "",
    "overtime_daily_hours": 0,  # 0 = no daily overtime
    "overtime_weekly_hours": 38,
    "tolerance_pct": 5,  # dashboard: how far over the pro-rata forecast before it goes red
    "opening_bank_balance": 0.0,
    "opening_balance_date": "",
}


def settings(db: Session) -> dict:
    s = db.get(AppSetting, "ops")
    return {**DEFAULTS, **((s.value or {}) if s else {})}


def next_number(db: Session, name: str) -> int:
    """Running numbers that never repeat, even after deletes."""
    c = db.get(Counter, name)
    if c is None:
        c = Counter(name=name, value=0)
        db.add(c)
    c.value += 1
    db.flush()
    return c.value


def new_job_no(db: Session) -> str:
    yy = date.today().year % 100
    return f"{settings(db)['job_prefix']}{yy}-{next_number(db, f'job-{yy}'):04d}"


def find_or_make_customer(db: Session, name: str, kind: str = "", **extra) -> Customer | None:
    name = (name or "").strip()
    if not name:
        return None
    c = db.scalar(select(Customer).where(func.lower(Customer.name) == name.lower()))
    if c is None:
        c = Customer(name=name, kind=kind or "residential", **{k: v for k, v in extra.items() if v})
        db.add(c)
        db.flush()
    return c


def client_type_for(job: Job) -> str:
    if job.kind == "civil":
        return "civil"
    return {"residential": "residential", "maintenance": "maintenance", "commercial": "builder"}.get(job.sector or "", "residential")


def department(job: Job | None) -> str:
    """Residential / commercial / maintenance / civil: how feedback, NPS and reports are split."""
    if job is None:
        return ""
    return "civil" if job.kind == "civil" else (job.sector or "commercial")


def start_job(db: Session, job: Job, user: User | None) -> None:
    """Make a job live: job number, customer and site records, contract value, budget from the estimate."""
    if job.work_status:
        return
    job.job_no = job.job_no or new_job_no(db)
    job.work_status = "scheduled"
    cust = find_or_make_customer(db, job.client, client_type_for(job))
    if cust and not job.customer_id:
        job.customer_id = cust.id
    if job.address and not job.site_id:
        site = db.scalar(select(Site).where(Site.address == job.address, Site.customer_id == (cust.id if cust else None)))
        if site is None:
            site = Site(customer_id=cust.id if cust else None, name=job.name, address=job.address)
            db.add(site)
            db.flush()
        job.site_id = site.id
    if job.contract_value is None:
        job.contract_value = job.tender_value
    if not job.start_date:
        job.start_date = date.today()
    if not db.scalar(select(BudgetLine.id).where(BudgetLine.job_id == job.id).limit(1)):
        for line in budget_from_estimate(db, job):
            db.add(line)
    db.flush()


def budget_from_estimate(db: Session, job: Job) -> list[BudgetLine]:
    """Budget lines from the take-off: labour hours and cost and materials by stage (plumbing), or the BOQ (civil)."""
    out: list[BudgetLine] = []
    if job.kind == "civil":
        from .civil import line_qty

        keep = 1 - settings(db)["civil_budget_margin_pct"] / 100
        by_cat: dict[str, float] = {}
        for l in db.scalars(select(CivilBoqLine).where(CivilBoqLine.job_id == job.id, CivilBoqLine.status == "confirmed")):
            by_cat[l.category] = by_cat.get(l.category, 0.0) + line_qty(l) * (l.rate or 0)
        for cat, total in by_cat.items():
            if total:
                out.append(BudgetLine(job_id=job.id, category="other", description=f"{cat} (BOQ less margin)", stage=cat,
                                      cost=round(total * keep, 2), source="estimate"))
        return out
    if not job.price_book_version_id:
        return out
    from .pricing import price_job

    summary = price_job(db, job.id).get("summary")
    if not summary:
        return out
    for st in summary["by_stage"]:
        if st.get("labour_hours") or st.get("labour_cost"):
            out.append(BudgetLine(job_id=job.id, category="labour", description=f"Labour – {st['stage']}", stage=st["stage"],
                                  hours=round(st.get("labour_hours", 0), 1), cost=round(st.get("labour_cost", 0), 2), source="estimate"))
        if st.get("material_cost"):
            out.append(BudgetLine(job_id=job.id, category="materials", description=f"Materials – {st['stage']}", stage=st["stage"],
                                  cost=round(st["material_cost"], 2), source="estimate"))
        if st.get("allowances_cost"):
            out.append(BudgetLine(job_id=job.id, category="other", description=f"Allowances – {st['stage']}", stage=st["stage"],
                                  cost=round(st["allowances_cost"], 2), source="estimate"))
    return out


def set_status(job: Job, status: str) -> None:
    job.work_status = status
    if status == "complete" and not job.completed_at:
        job.completed_at = datetime.now(timezone.utc)
    if status in ("scheduled", "in_progress", "on_hold"):
        job.completed_at = None


def cost_rate(db: Session, user: User | None) -> float:
    return (user.cost_rate if user and user.cost_rate else None) or float(settings(db)["default_cost_rate"])
