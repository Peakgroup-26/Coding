"""Customers, sites, suppliers, live jobs (the work board) and job budgets."""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .. import ops, sales
from ..access import can_kind, can_sector, can_see_job
from ..audit import record, snapshot
from ..auth import current_user, require_admin
from ..db import get_db
from ..models import AppSetting, BudgetLine, Customer, CustomerContact, Job, Site, Supplier, User
from . import get_or_404

router = APIRouter(prefix="/api", tags=["operations"])


def _row(obj, fields) -> dict:
    out = {"id": obj.id}
    for f in fields:
        v = getattr(obj, f)
        out[f] = v.isoformat() if isinstance(v, date) else v
    return out


# --- customers ---
CUSTOMER_FIELDS = ["name", "kind", "email", "phone", "address", "abn", "terms_days", "notes", "active", "no_marketing", "xero_id"]


class CustomerIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    kind: str = "residential"
    email: str = ""
    phone: str = ""
    address: str = ""
    abn: str = ""
    terms_days: int = Field(default=14, ge=0, le=180)
    notes: str = ""
    active: bool = True
    no_marketing: bool = False


@router.get("/customers")
def list_customers(q: str = "", kind: str = "", db: Session = Depends(get_db), _: User = Depends(current_user)):
    stmt = select(Customer).order_by(Customer.name)
    if q:
        stmt = stmt.where(or_(Customer.name.ilike(f"%{q}%"), Customer.email.ilike(f"%{q}%"), Customer.phone.ilike(f"%{q}%")))
    if kind:
        stmt = stmt.where(Customer.kind == kind)
    counts = dict(db.execute(select(Job.customer_id, func.count()).where(Job.customer_id.is_not(None)).group_by(Job.customer_id)).all())
    return [{**_row(c, CUSTOMER_FIELDS), "jobs": counts.get(c.id, 0)} for c in db.scalars(stmt)]


@router.post("/customers")
def add_customer(body: CustomerIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if db.scalar(select(Customer).where(func.lower(Customer.name) == body.name.strip().lower())):
        raise HTTPException(409, "There's already a customer with that name")
    c = Customer(**body.model_dump())
    db.add(c)
    db.flush()
    record(db, user.id, "customer", c.id, "create", after=snapshot(c))
    db.commit()
    return _row(c, CUSTOMER_FIELDS)


@router.put("/customers/{customer_id}")
def update_customer(customer_id: int, body: CustomerIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    c = get_or_404(db, Customer, customer_id)
    before = snapshot(c)
    for k, v in body.model_dump().items():
        setattr(c, k, v)
    record(db, user.id, "customer", c.id, "update", before, snapshot(c))
    db.commit()
    return _row(c, CUSTOMER_FIELDS)


@router.get("/customers/{customer_id}")
def customer_detail(customer_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    from .. import crm

    c = get_or_404(db, Customer, customer_id)
    jobs = [j for j in db.scalars(select(Job).where(Job.customer_id == c.id).order_by(Job.id.desc())) if can_see_job(user, j)]
    return {**_row(c, CUSTOMER_FIELDS),
            "contacts": [_row(x, ["name", "position", "phone", "email"]) for x in
                         db.scalars(select(CustomerContact).where(CustomerContact.customer_id == c.id))],
            "sites": [_row(s, ["name", "address", "access_notes", "contact", "lat", "lng"]) for s in
                      db.scalars(select(Site).where(Site.customer_id == c.id).order_by(Site.name))],
            "jobs": [work_row(db, j) for j in jobs],
            **crm.customer_summary(db, c)}


class ContactIn(BaseModel):
    name: str = Field(min_length=1)
    position: str = ""
    phone: str = ""
    email: str = ""


@router.post("/customers/{customer_id}/contacts")
def add_contact(customer_id: int, body: ContactIn, db: Session = Depends(get_db), _: User = Depends(current_user)):
    get_or_404(db, Customer, customer_id)
    x = CustomerContact(customer_id=customer_id, **body.model_dump())
    db.add(x)
    db.commit()
    return _row(x, ["name", "position", "phone", "email"])


@router.delete("/customers/{customer_id}/contacts/{contact_id}", status_code=204)
def delete_contact(customer_id: int, contact_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    x = get_or_404(db, CustomerContact, contact_id)
    if x.customer_id != customer_id:
        raise HTTPException(404, "Contact not found")
    db.delete(x)
    db.commit()


class SiteIn(BaseModel):
    customer_id: int | None = None
    name: str = Field(min_length=1)
    address: str = ""
    access_notes: str = ""
    contact: str = ""
    lat: float | None = None
    lng: float | None = None


SITE_FIELDS = ["customer_id", "name", "address", "access_notes", "contact", "lat", "lng"]


@router.get("/sites")
def list_sites(customer_id: int | None = None, q: str = "", db: Session = Depends(get_db), _: User = Depends(current_user)):
    stmt = select(Site).order_by(Site.name)
    if customer_id:
        stmt = stmt.where(Site.customer_id == customer_id)
    if q:
        stmt = stmt.where(or_(Site.name.ilike(f"%{q}%"), Site.address.ilike(f"%{q}%")))
    return [_row(s, SITE_FIELDS) for s in db.scalars(stmt.limit(500))]


@router.post("/sites")
def add_site(body: SiteIn, db: Session = Depends(get_db), _: User = Depends(current_user)):
    s = Site(**body.model_dump())
    db.add(s)
    db.commit()
    return _row(s, SITE_FIELDS)


@router.put("/sites/{site_id}")
def update_site(site_id: int, body: SiteIn, db: Session = Depends(get_db), _: User = Depends(current_user)):
    s = get_or_404(db, Site, site_id)
    for k, v in body.model_dump().items():
        setattr(s, k, v)
    db.commit()
    return _row(s, SITE_FIELDS)


# --- suppliers ---
SUPPLIER_FIELDS = ["name", "email", "phone", "account_no", "terms_days", "kind", "active", "xero_id"]


class SupplierIn(BaseModel):
    name: str = Field(min_length=1)
    email: str = ""
    phone: str = ""
    account_no: str = ""
    terms_days: int = Field(default=30, ge=0, le=180)
    kind: str = "materials"
    active: bool = True


@router.get("/suppliers")
def list_suppliers(db: Session = Depends(get_db), _: User = Depends(current_user)):
    return [_row(s, SUPPLIER_FIELDS) for s in db.scalars(select(Supplier).order_by(Supplier.name))]


@router.post("/suppliers")
def add_supplier(body: SupplierIn, db: Session = Depends(get_db), _: User = Depends(current_user)):
    if db.scalar(select(Supplier).where(func.lower(Supplier.name) == body.name.strip().lower())):
        raise HTTPException(409, "There's already a supplier with that name")
    s = Supplier(**body.model_dump())
    db.add(s)
    db.commit()
    return _row(s, SUPPLIER_FIELDS)


@router.put("/suppliers/{supplier_id}")
def update_supplier(supplier_id: int, body: SupplierIn, db: Session = Depends(get_db), _: User = Depends(current_user)):
    s = get_or_404(db, Supplier, supplier_id)
    for k, v in body.model_dump().items():
        setattr(s, k, v)
    db.commit()
    return _row(s, SUPPLIER_FIELDS)


# --- staff (for pickers; details are edited in the admin portal) ---
@router.get("/staff")
def staff(db: Session = Depends(get_db), _: User = Depends(current_user)):
    return [{"id": u.id, "name": u.name or u.email, "role": u.role, "trade": u.trade, "phone": u.phone, "colour": u.colour}
            for u in db.scalars(select(User).where(User.active.is_(True)).order_by(User.name, User.email))]


# --- live jobs ---
def work_row(db: Session, j: Job, fin: dict | None = None) -> dict:
    cust = db.get(Customer, j.customer_id) if j.customer_id else None
    site = db.get(Site, j.site_id) if j.site_id else None
    return {"id": j.id, "job_no": j.job_no, "quote_no": j.quote_no, "name": j.name, "kind": j.kind, "sector": j.sector,
            "work_status": j.work_status, "priority": j.priority, "customer_id": j.customer_id,
            "customer": cust.name if cust else j.client, "site_id": j.site_id, "site": site.name if site else "",
            "address": site.address if site and site.address else j.address, "order_no": j.order_no, "work_type": j.work_type,
            "description": j.description, "billing": j.billing, "contract_value": j.contract_value,
            "start_date": j.start_date.isoformat() if j.start_date else None,
            "finish_date": j.finish_date.isoformat() if j.finish_date else None,
            "due_date": j.due_date.isoformat() if j.due_date else None, "supervisor_id": j.supervisor_id,
            "percent_complete": j.percent_complete, "retention_pct": j.retention_pct, "contact": j.contact,
            "completed_at": j.completed_at.isoformat() if j.completed_at else None, "signed_by_name": j.signed_by_name,
            **({"fin": fin} if fin is not None else {})}


@router.get("/work")
def work_list(status: str = "active", sector: str = "", q: str = "", db: Session = Depends(get_db), user: User = Depends(current_user)):
    from .. import finance

    stmt = select(Job).where(Job.work_status != "").order_by(Job.id.desc())
    if status == "active":
        stmt = stmt.where(Job.work_status.in_(ops.ACTIVE))
    elif status:
        stmt = stmt.where(Job.work_status == status)
    if sector:
        stmt = stmt.where(Job.sector == sector)
    out = []
    for j in db.scalars(stmt):
        if not can_see_job(user, j):
            continue
        if q and q.lower() not in f"{j.job_no} {j.name} {j.client} {j.address} {j.order_no}".lower():
            continue
        out.append(work_row(db, j, finance.quick(db, j)))
    return out


class WorkIn(BaseModel):
    name: str = ""
    sector: str = "maintenance"
    kind: str = "hydraulic"
    customer_id: int | None = None
    customer_name: str = ""  # makes a new customer if there's no customer_id
    customer_kind: str = ""
    site_id: int | None = None
    address: str = ""
    contact: str = ""
    order_no: str = ""
    work_type: str = ""
    priority: str = "normal"
    description: str = ""
    billing: str = "charge"
    contract_value: float | None = Field(default=None, ge=0)
    start_date: date | None = None
    finish_date: date | None = None
    due_date: date | None = None
    supervisor_id: int | None = None
    lead_source: str = ""


def _check_work(body: WorkIn, user: User) -> None:
    if body.sector not in sales.SECTORS or body.kind not in ("hydraulic", "civil"):
        raise HTTPException(422, "Choose a sector and a job type")
    if not can_sector(user, body.sector) or not can_kind(user, body.kind):
        raise HTTPException(403, "You don't have access to that kind of job")
    if body.priority not in ops.PRIORITIES or body.billing not in ("fixed", "charge"):
        raise HTTPException(422, "Unknown priority or billing")


@router.post("/work")
def new_work(body: WorkIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Raise a job straight away (a maintenance call-out, a do-and-charge, a small job with no tender)."""
    _check_work(body, user)
    cust = db.get(Customer, body.customer_id) if body.customer_id else ops.find_or_make_customer(
        db, body.customer_name, body.customer_kind or {"maintenance": "maintenance", "residential": "residential"}.get(body.sector, "builder"))
    site = db.get(Site, body.site_id) if body.site_id else None
    if site is None and body.address:
        site = Site(customer_id=cust.id if cust else None, name=body.name or body.address, address=body.address)
        db.add(site)
        db.flush()
    name = body.name.strip() or " – ".join(x for x in (body.work_type, cust.name if cust else "", ) if x) or "New job"
    job = Job(name=name, sector=body.sector, kind=body.kind, client=cust.name if cust else "", customer_id=cust.id if cust else None,
              site_id=site.id if site else None, address=site.address if site else body.address, contact=body.contact,
              order_no=body.order_no, work_type=body.work_type, priority=body.priority, description=body.description,
              billing=body.billing, contract_value=body.contract_value, tender_value=body.contract_value,
              start_date=body.start_date or date.today(), finish_date=body.finish_date, due_date=body.due_date,
              supervisor_id=body.supervisor_id, lead_source=body.lead_source, created_by=user.id,
              tender_result="won", decided_date=date.today(), quote_sent_date=date.today(), status="draft")
    sales.prepare_new(db, job)
    db.add(job)
    db.flush()
    ops.start_job(db, job, user)
    record(db, user.id, "job", job.id, "create", after=snapshot(job))
    db.commit()
    return work_row(db, job)


@router.post("/jobs/{job_id}/start-work")
def convert(job_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """A won quote becomes a live job: job number, customer and site, budget from the estimate."""
    job = get_or_404(db, Job, job_id)
    if job.work_status:
        return work_row(db, job)
    before = snapshot(job)
    if job.tender_result != "won":
        from .sales import SalesIn, apply_sales

        apply_sales(db, job, SalesIn(tender_result="won"), user)
    ops.start_job(db, job, user)
    record(db, user.id, "job", job.id, "start_work", before, snapshot(job))
    db.commit()
    return work_row(db, job)


class WorkPatch(BaseModel):
    work_status: str | None = None
    name: str | None = None
    customer_id: int | None = None
    site_id: int | None = None
    contact: str | None = None
    order_no: str | None = None
    priority: str | None = None
    description: str | None = None
    billing: str | None = None
    contract_value: float | None = Field(default=None, ge=0)
    percent_complete: float | None = Field(default=None, ge=0, le=100)
    clear_percent: bool = False
    start_date: date | None = None
    finish_date: date | None = None
    due_date: date | None = None
    supervisor_id: int | None = None
    retention_pct: float | None = Field(default=None, ge=0, le=20)
    payment_terms_days: int | None = Field(default=None, ge=0, le=180)


@router.put("/jobs/{job_id}/work")
def update_work(job_id: int, body: WorkPatch, db: Session = Depends(get_db), user: User = Depends(current_user)):
    job = get_or_404(db, Job, job_id)
    if not job.work_status:
        raise HTTPException(409, "Start the job first")
    before = snapshot(job)
    data = body.model_dump(exclude_unset=True)
    if "work_status" in data:
        if data["work_status"] not in ops.WORK_STATUSES:
            raise HTTPException(422, "Unknown status")
        ops.set_status(job, data.pop("work_status"))
    if data.get("priority") and data["priority"] not in ops.PRIORITIES:
        raise HTTPException(422, "Unknown priority")
    if data.pop("clear_percent", False):
        job.percent_complete = None
    for k, v in data.items():
        setattr(job, k, v)
    if "customer_id" in data and job.customer_id:
        job.client = db.get(Customer, job.customer_id).name if db.get(Customer, job.customer_id) else job.client
    if "site_id" in data and job.site_id and db.get(Site, job.site_id):
        job.address = db.get(Site, job.site_id).address
    record(db, user.id, "job", job.id, "work", before, snapshot(job))
    db.commit()
    return work_row(db, job)


@router.get("/jobs/{job_id}/work")
def work_detail(job_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    from .. import finance

    job = get_or_404(db, Job, job_id)
    return {**work_row(db, job), "financials": finance.job_financials(db, job) if job.work_status else None}


# --- budget lines ---
BUDGET_FIELDS = ["category", "description", "stage", "hours", "cost", "source"]


class BudgetIn(BaseModel):
    category: str
    description: str = ""
    stage: str = ""
    hours: float = Field(default=0.0, ge=0)
    cost: float = Field(default=0.0, ge=0)


@router.get("/jobs/{job_id}/budget")
def list_budget(job_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    get_or_404(db, Job, job_id)
    return [_row(b, BUDGET_FIELDS) for b in db.scalars(select(BudgetLine).where(BudgetLine.job_id == job_id).order_by(BudgetLine.id))]


@router.post("/jobs/{job_id}/budget")
def add_budget(job_id: int, body: BudgetIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    get_or_404(db, Job, job_id)
    if body.category not in ops.CATEGORIES:
        raise HTTPException(422, "Unknown category")
    b = BudgetLine(job_id=job_id, **body.model_dump())
    db.add(b)
    db.flush()
    record(db, user.id, "budget_line", b.id, "create", after={"job_id": job_id, **body.model_dump()})
    db.commit()
    return _row(b, BUDGET_FIELDS)


@router.put("/budget/{budget_id}")
def update_budget(budget_id: int, body: BudgetIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    b = get_or_404(db, BudgetLine, budget_id)
    if body.category not in ops.CATEGORIES:
        raise HTTPException(422, "Unknown category")
    before = _row(b, BUDGET_FIELDS)
    for k, v in body.model_dump().items():
        setattr(b, k, v)
    record(db, user.id, "budget_line", b.id, "update", {"job_id": b.job_id, **before}, _row(b, BUDGET_FIELDS))
    db.commit()
    return _row(b, BUDGET_FIELDS)


@router.delete("/budget/{budget_id}", status_code=204)
def delete_budget(budget_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    b = get_or_404(db, BudgetLine, budget_id)
    record(db, user.id, "budget_line", b.id, "delete", before={"job_id": b.job_id, **_row(b, BUDGET_FIELDS)})
    db.delete(b)
    db.commit()


@router.post("/jobs/{job_id}/budget/from-estimate")
def rebuild_budget(job_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Replace the estimate-sourced lines with fresh ones from the current take-off (manual lines stay)."""
    job = get_or_404(db, Job, job_id)
    for b in db.scalars(select(BudgetLine).where(BudgetLine.job_id == job_id, BudgetLine.source == "estimate")):
        db.delete(b)
    new = ops.budget_from_estimate(db, job)
    for b in new:
        db.add(b)
    record(db, user.id, "job", job.id, "budget_from_estimate", after={"lines": len(new)})
    db.commit()
    return list_budget(job_id, db, user)


# --- operations settings ---
@router.get("/ops-settings")
def get_ops_settings(db: Session = Depends(get_db), _: User = Depends(current_user)):
    return {**ops.settings(db), "work_statuses": ops.WORK_LABELS, "categories": ops.CATEGORY_LABELS, "trades": ops.TRADES,
            "priorities": ops.PRIORITIES}


@router.put("/ops-settings")
def put_ops_settings(body: dict, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    clean = {k: v for k, v in body.items() if k in ops.DEFAULTS}
    for k, v in clean.items():
        if isinstance(ops.DEFAULTS[k], (int, float)) and not isinstance(ops.DEFAULTS[k], bool):
            if not isinstance(v, (int, float)):
                raise HTTPException(422, f"{k.replace('_', ' ')} must be a number")
    s = db.get(AppSetting, "ops") or AppSetting(key="ops", value={})
    s.value = {**(s.value or {}), **clean}
    db.merge(s)
    record(db, admin.id, "setting", 0, "update", after={"key": "ops", **clean})
    db.commit()
    return ops.settings(db)
