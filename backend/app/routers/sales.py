"""Leads, the sales pipeline and the sales dashboard."""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import sales
from ..access import can_kind, can_sector, can_see_job
from ..audit import record, snapshot
from ..auth import current_user, require_admin
from ..db import get_db
from ..models import AppSetting, Job, User
from ..schemas import JobOut
from . import get_or_404

router = APIRouter(prefix="/api", tags=["sales"])


class LeadIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    sector: str = "residential"
    kind: str = "hydraulic"
    client: str = ""
    contact: str = ""
    lead_source: str = ""
    lead_date: date | None = None
    due_date: date | None = None
    tender_value: float | None = Field(default=None, ge=0)  # rough value, if known
    address: str = ""
    work_type: str = Field(default="", max_length=100)
    value_band: str = ""


def _check_band(band: str | None) -> None:
    if band and band not in sales.BAND_LABELS:
        raise HTTPException(422, "Pick a job size from the list")


@router.post("/leads", response_model=JobOut)
def add_lead(body: LeadIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """A new enquiry, before any plans arrive. Drop the plans on it later."""
    if body.sector not in sales.SECTORS or body.kind not in ("hydraulic", "civil"):
        raise HTTPException(422, "Choose a sector and a job type")
    if not can_sector(user, body.sector) or not can_kind(user, body.kind):
        raise HTTPException(403, "You don't have access to that kind of job")
    _check_band(body.value_band)
    job = Job(**body.model_dump(), created_by=user.id)
    sales.prepare_new(db, job)
    db.add(job)
    db.flush()
    record(db, user.id, "job", job.id, "create", after=snapshot(job))
    db.commit()
    return job


class SalesIn(BaseModel):
    sector: str | None = None
    lead_date: date | None = None
    quote_sent_date: date | None = None
    mark_quote_sent: bool = False  # sets the quote date to today
    clear_quote_sent: bool = False
    decided_date: date | None = None
    tender_result: str | None = None  # pending | won | lost | withdrawn
    tender_value: float | None = Field(default=None, ge=0)
    lead_source: str | None = None
    contact: str | None = None
    due_date: date | None = None
    work_type: str | None = Field(default=None, max_length=100)
    value_band: str | None = None
    outcome_reason: str | None = Field(default=None, max_length=100)
    client: str | None = Field(default=None, max_length=255)


def apply_sales(db: Session, job: Job, body: SalesIn, user: User) -> None:
    """Update a job's sales details. Dates fill themselves in when the event happens; any can be corrected."""
    before = snapshot(job)
    data = body.model_dump(exclude_unset=True)
    if body.sector is not None:
        if body.sector not in sales.SECTORS:
            raise HTTPException(422, "sector must be residential, commercial or maintenance")
        if not can_sector(user, body.sector):
            raise HTTPException(403, f"You don't have access to {body.sector} jobs")
        job.sector = body.sector
    _check_band(body.value_band)
    for k in ("lead_date", "lead_source", "contact", "due_date", "tender_value", "work_type", "value_band", "client"):
        if k in data and (data[k] is not None or k in ("due_date", "tender_value", "lead_date")):
            setattr(job, k, data[k])
    if body.mark_quote_sent and not job.quote_sent_date:
        job.quote_sent_date = date.today()
    if "quote_sent_date" in data and data["quote_sent_date"]:
        job.quote_sent_date = data["quote_sent_date"]
    if body.clear_quote_sent:
        job.quote_sent_date = None
    if body.tender_result is not None:
        if body.tender_result not in ("pending", "won", "lost", "withdrawn"):
            raise HTTPException(422, "Result must be pending, won, lost or withdrawn")
        if body.tender_result != job.tender_result:
            job.decided_date = None if body.tender_result == "pending" else (body.decided_date or date.today())
        job.tender_result = body.tender_result
        if body.tender_result not in ("lost", "withdrawn"):
            job.outcome_reason = ""
    if body.outcome_reason is not None and job.tender_result in ("lost", "withdrawn"):
        job.outcome_reason = body.outcome_reason
    if body.decided_date and job.tender_result != "pending":
        job.decided_date = body.decided_date
    ld = job.lead_date or (job.created_at.date() if job.created_at else None)
    if job.quote_sent_date and ld and job.quote_sent_date < ld:
        raise HTTPException(422, "The quote can't be sent before the lead came in")
    if job.decided_date and job.quote_sent_date and job.decided_date < job.quote_sent_date:
        raise HTTPException(422, "The result can't come before the quote was sent")
    record(db, user.id, "job", job.id, "sales", before, snapshot(job))


@router.put("/jobs/{job_id}/sales", response_model=JobOut)
def update_sales(job_id: int, body: SalesIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    job = get_or_404(db, Job, job_id)
    apply_sales(db, job, body, user)
    db.commit()
    return job


@router.get("/sales/dashboard")
def dashboard(sector: str = "", months: int = 12, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if sector and sector not in sales.SECTORS:
        raise HTTPException(422, "Unknown sector")
    jobs = [j for j in db.scalars(select(Job)) if can_see_job(user, j) and (not sector or j.sector == sector)]
    return sales.dashboard(db, jobs, max(1, min(months, 36)))


@router.get("/sales/settings")
def get_settings(db: Session = Depends(get_db), user: User = Depends(current_user)):
    visible = [s for s in sales.SECTORS if can_sector(user, s)]
    jobs = [j for j in db.scalars(select(Job)) if can_see_job(user, j)]
    return {"lead_sources": sales.sources(db), "lost_reasons": sales.lost_reasons(db), "work_types": sales.work_types(db),
            "value_bands": [{"key": k, "label": lbl} for k, lbl in sales.VALUE_BANDS], "sectors": [{"key": k, "label": sales.SECTORS[k][0]} for k in visible],
            "stages": sales.STAGE_LABELS, "counts": sales.count_by_sector(db, jobs)}


class ListsIn(BaseModel):
    lead_sources: list[str] | None = None
    lost_reasons: list[str] | None = None
    work_types: dict[str, list[str]] | None = None


def _clean(items: list[str]) -> list[str]:
    out: list[str] = []
    for i in items:
        i = i.strip()[:100]
        if i and i.lower() not in (o.lower() for o in out):
            out.append(i)
    return out


@router.put("/sales/settings")
def put_settings(body: ListsIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    """The choices offered in the drop-downs. Send only the lists being changed."""
    clean: dict = {}
    if body.lead_sources is not None:
        clean["lead_sources"] = _clean(body.lead_sources)
    if body.lost_reasons is not None:
        clean["lost_reasons"] = _clean(body.lost_reasons)
    if body.work_types is not None:
        if set(body.work_types) - set(sales.SECTORS):
            raise HTTPException(422, "Unknown sector in work types")
        clean["work_types"] = {k: _clean(v) for k, v in body.work_types.items()}
    s = db.get(AppSetting, "sales") or AppSetting(key="sales", value={})
    value = {**(s.value or {}), **clean}
    if "work_types" in clean:
        value["work_types"] = {**((s.value or {}).get("work_types") or {}), **clean["work_types"]}
    s.value = value
    db.merge(s)
    record(db, admin.id, "setting", 0, "update", after={"key": "sales", **clean})
    db.commit()
    return {"lead_sources": sales.sources(db), "lost_reasons": sales.lost_reasons(db), "work_types": sales.work_types(db)}


@router.get("/sales/clients")
def clients(db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Clients (and their contacts) from the jobs this person can see, for the pick lists."""
    return sales.clients([j for j in db.scalars(select(Job)) if can_see_job(user, j)])
