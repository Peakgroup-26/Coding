"""Reports, programs, tender results, the company dashboard, productivity rates and workforce settings."""
import csv
import io
import re
from datetime import date

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import reports
from ..access import can_see_job
from ..audit import record
from ..auth import current_user, require_admin
from ..db import get_db
from ..models import AppSetting, Job, ProductivityRate, User
from ..reports_export import workbook
from . import get_or_404

router = APIRouter(prefix="/api", tags=["reports"])


@router.get("/jobs/{job_id}/reports/materials")
def material_list(job_id: int, include_suggested: bool = False, by_stage: bool = False, db: Session = Depends(get_db),
                  _: User = Depends(current_user)):
    return reports.materials(db, get_or_404(db, Job, job_id), include_suggested, by_stage)


@router.get("/jobs/{job_id}/reports/labour")
def labour(job_id: int, include_suggested: bool = False, db: Session = Depends(get_db), _: User = Depends(current_user)):
    return reports.labour(db, get_or_404(db, Job, job_id), include_suggested)


@router.get("/jobs/{job_id}/reports/program")
def program(job_id: int, include_suggested: bool = False, db: Session = Depends(get_db), _: User = Depends(current_user)):
    return reports.program(db, get_or_404(db, Job, job_id), include_suggested)


@router.get("/jobs/{job_id}/reports.xlsx")
def export(job_id: int, include_suggested: bool = False, db: Session = Depends(get_db), _: User = Depends(current_user)):
    job = get_or_404(db, Job, job_id)
    data = workbook(db, job, include_suggested)
    fname = re.sub(r"[^A-Za-z0-9_-]+", "_", f"{job.quote_no or job.id}_{job.name}")[:80] + "_Reports.xlsx"
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{fname}"'})


class StagePlan(BaseModel):
    plumbers: int | None = Field(default=None, ge=1, le=200)
    start: date | None = None
    gap_days: int | None = Field(default=None, ge=0, le=365)


class ProgramIn(BaseModel):
    start_date: date | None = None
    target_weeks: float | None = Field(default=None, gt=0, le=520)
    plumbers: int | None = Field(default=None, ge=1, le=200)  # crew size when there's no target
    stages: dict[str, StagePlan] = {}


@router.put("/jobs/{job_id}/program")
def set_program(job_id: int, body: ProgramIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Start date, target duration or crew size, and per-stage overrides. Allowed on final estimates too:
    planning carries on after the price is locked."""
    job = get_or_404(db, Job, job_id)
    before = {"start_date": str(job.start_date), "target_weeks": job.target_weeks, "program": job.program}
    job.start_date, job.target_weeks = body.start_date, body.target_weeks
    job.program = {"plumbers": body.plumbers,
                   "stages": {k: {kk: (str(vv) if isinstance(vv, date) else vv) for kk, vv in v.model_dump().items() if vv is not None}
                              for k, v in body.stages.items()}}
    record(db, user.id, "job", job.id, "program", before, {"start_date": str(job.start_date), "target_weeks": job.target_weeks,
                                                             "program": job.program})
    db.commit()
    return reports.program(db, job)


class ResultIn(BaseModel):
    tender_result: str
    tender_value: float | None = Field(default=None, ge=0)


@router.put("/jobs/{job_id}/tender-result")
def set_result(job_id: int, body: ResultIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    from .sales import SalesIn, apply_sales

    job = get_or_404(db, Job, job_id)
    apply_sales(db, job, SalesIn(tender_result=body.tender_result, tender_value=body.tender_value), user)
    db.commit()
    return {"tender_result": job.tender_result, "tender_value": job.tender_value}


@router.get("/reports/dashboard")
def dashboard(include_pending: bool = False, weeks: int = 26, db: Session = Depends(get_db), user: User = Depends(current_user)):
    jobs = [j for j in db.scalars(select(Job)) if can_see_job(user, j)]
    return reports.dashboard(db, jobs, max(4, min(weeks, 104)), include_pending)


# --- workforce settings ---
@router.get("/settings/workforce")
def get_workforce(db: Session = Depends(get_db), _: User = Depends(current_user)):
    return reports.settings(db)


@router.put("/settings/workforce")
def put_workforce(body: dict, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    clean = {k: v for k, v in body.items() if k in reports.DEFAULTS}
    for k in ("hours_per_day", "apprentice_ratio", "apprentice_productivity", "workers_per_supervisor", "pm_percent"):
        if k in clean and (not isinstance(clean[k], (int, float)) or clean[k] < 0):
            raise HTTPException(422, f"{k.replace('_', ' ')} must be a number, 0 or more")
    if clean.get("hours_per_day") == 0 or clean.get("workers_per_supervisor") == 0:
        raise HTTPException(422, "Hours per day and workers per supervisor can't be 0")
    s = db.get(AppSetting, reports.SETTINGS_KEY) or AppSetting(key=reports.SETTINGS_KEY, value={})
    s.value = {**(s.value or {}), **clean}
    db.merge(s)
    record(db, admin.id, "setting", 0, "update", after={"key": reports.SETTINGS_KEY, **clean})
    db.commit()
    return reports.settings(db)


# --- productivity rates ---
FIELDS = ["kind", "service_code", "dn_min", "dn_max", "material", "item_type", "civil_category", "keyword", "unit",
          "hours_per_unit", "note", "active"]


class RateIn(BaseModel):
    kind: str = "hydraulic"
    service_code: str = ""
    dn_min: int | None = None
    dn_max: int | None = None
    material: str = ""
    item_type: str = ""
    civil_category: str = ""
    keyword: str = ""
    unit: str = ""
    hours_per_unit: float = Field(ge=0)
    note: str = ""
    active: bool = True


def _rate_out(r: ProductivityRate) -> dict:
    return {"id": r.id, **{f: getattr(r, f) for f in FIELDS}}


@router.get("/productivity")
def list_rates(db: Session = Depends(get_db), _: User = Depends(current_user)):
    return [_rate_out(r) for r in db.scalars(select(ProductivityRate).order_by(ProductivityRate.kind, ProductivityRate.service_code,
                                                                                   ProductivityRate.item_type, ProductivityRate.civil_category,
                                                                                   ProductivityRate.dn_min))]


def _check(body: RateIn) -> None:
    if body.kind not in ("hydraulic", "civil"):
        raise HTTPException(422, "kind must be hydraulic or civil")
    if body.kind == "hydraulic" and not (body.service_code or body.item_type):
        raise HTTPException(422, "A plumbing rate needs a service (for pipe) or an item type")
    if body.dn_min is not None and body.dn_max is not None and body.dn_min > body.dn_max:
        raise HTTPException(422, "DN from is bigger than DN to")


@router.post("/productivity")
def add_rate(body: RateIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    _check(body)
    r = ProductivityRate(**body.model_dump())
    r.service_code = r.service_code.upper()
    db.add(r)
    db.flush()
    record(db, user.id, "productivity_rate", r.id, "create", after=_rate_out(r))
    db.commit()
    return _rate_out(r)


@router.put("/productivity/{rate_id}")
def update_rate(rate_id: int, body: RateIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    _check(body)
    r = get_or_404(db, ProductivityRate, rate_id)
    before = _rate_out(r)
    for k, v in body.model_dump().items():
        setattr(r, k, v)
    r.service_code = r.service_code.upper()
    record(db, user.id, "productivity_rate", r.id, "update", before, _rate_out(r))
    db.commit()
    return _rate_out(r)


@router.delete("/productivity/{rate_id}", status_code=204)
def delete_rate(rate_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    r = get_or_404(db, ProductivityRate, rate_id)
    record(db, user.id, "productivity_rate", r.id, "delete", before=_rate_out(r))
    db.delete(r)
    db.commit()


@router.get("/productivity.csv")
def export_rates(db: Session = Depends(get_db), _: User = Depends(current_user)):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(FIELDS)
    for r in db.scalars(select(ProductivityRate).order_by(ProductivityRate.id)):
        w.writerow(["" if getattr(r, f) is None else getattr(r, f) for f in FIELDS])
    return Response(buf.getvalue(), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="productivity-rates.csv"'})


@router.post("/productivity/import")
async def import_rates(file: UploadFile = File(...), replace: bool = False, db: Session = Depends(get_db),
                       user: User = Depends(current_user)):
    """CSV with the columns of productivity.csv. Rows marked EXAMPLE in the note come in switched off."""
    text = (await file.read(5_000_000)).decode("utf-8-sig", errors="replace")
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows or "hours_per_unit" not in rows[0]:
        raise HTTPException(422, "The CSV needs a header row including hours_per_unit (download the current rates for the layout)")
    made, errors = [], []
    for n, row in enumerate(rows, start=2):
        try:
            data = {f: (row.get(f) or "").strip() for f in FIELDS}
            body = RateIn(kind=data["kind"] or "hydraulic", service_code=data["service_code"],
                          dn_min=int(data["dn_min"]) if data["dn_min"] else None, dn_max=int(data["dn_max"]) if data["dn_max"] else None,
                          material=data["material"], item_type=data["item_type"], civil_category=data["civil_category"],
                          keyword=data["keyword"], unit=data["unit"], hours_per_unit=float(data["hours_per_unit"]), note=data["note"],
                          active=data["active"].lower() not in ("false", "0", "no") and "EXAMPLE" not in data["note"].upper())
            _check(body)
            made.append(body)
        except (ValueError, HTTPException) as e:
            errors.append(f"Row {n}: {getattr(e, 'detail', e)}")
    if errors:
        raise HTTPException(422, "; ".join(errors[:10]))
    if replace:
        for r in db.scalars(select(ProductivityRate)):
            db.delete(r)
    for b in made:
        db.add(ProductivityRate(**{**b.model_dump(), "service_code": b.service_code.upper()}))
    record(db, user.id, "productivity_rate", 0, "import", after={"rows": len(made), "replace": replace})
    db.commit()
    return {"imported": len(made)}
