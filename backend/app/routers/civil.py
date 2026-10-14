"""Civil BOQ: previous jobs' rates, the BOQ lines read from civil plans, approval and export."""
import re

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import autopilot, civil
from ..ai import get_reader
from ..audit import record, snapshot
from ..auth import current_user
from ..db import get_db
from ..models import CivilBoqLine, CivilRate, CivilRateSet, CivilTakeoffItem, Job, Sheet, User
from . import ensure_open, get_or_404

router = APIRouter(prefix="/api", tags=["civil"])

MAX_RATE_FILE = 20 * 1024 * 1024


# --- previous jobs' rates ---
def _set_out(s: CivilRateSet, n: int) -> dict:
    return {"id": s.id, "name": s.name, "source_file": s.source_file, "job_date": s.job_date, "notes": s.notes,
            "active": s.active, "created_at": s.created_at, "rates": n}


@router.get("/civil/rate-sets")
def list_rate_sets(db: Session = Depends(get_db), _: User = Depends(current_user)):
    out = []
    for s in db.scalars(select(CivilRateSet).order_by(CivilRateSet.id.desc())):
        out.append(_set_out(s, len(s.rates)))
    return out


@router.post("/civil/rate-sets")
async def import_rate_set(file: UploadFile = File(...), name: str = Form(""), notes: str = Form(""),
                          db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Load a previous job's priced BOQ (Excel or CSV). Any layout with Description and Rate columns works."""
    data = await file.read(MAX_RATE_FILE + 1)
    if len(data) > MAX_RATE_FILE:
        raise HTTPException(413, "That file is larger than 20 MB")
    try:
        rows = civil.read_rate_file(file.filename or "", data)
    except ValueError as e:
        raise HTTPException(422, str(e))
    except Exception as e:  # a corrupt or password-protected workbook
        raise HTTPException(422, f"Couldn't read {file.filename}: {e}")
    if not rows:
        raise HTTPException(422, "No rates found. The file needs a header row with Description and Rate columns "
                                 "(Unit and Qty are used too if they're there).")
    label = name.strip() or re.sub(r"\.(xlsx|xlsm|csv)$", "", file.filename or "Previous job", flags=re.IGNORECASE)
    s = CivilRateSet(name=label[:255], source_file=file.filename or "", notes=notes)
    db.add(s)
    db.flush()
    for r in rows:
        db.add(CivilRate(set_id=s.id, **r))
    record(db, user.id, "civil_rate_set", s.id, "create", after={"name": s.name, "rates": len(rows)})
    db.commit()
    return _set_out(s, len(rows))


class RateSetPatch(BaseModel):
    name: str | None = None
    notes: str | None = None
    active: bool | None = None


@router.patch("/civil/rate-sets/{set_id}")
def update_rate_set(set_id: int, body: RateSetPatch, db: Session = Depends(get_db), user: User = Depends(current_user)):
    s = get_or_404(db, CivilRateSet, set_id)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(s, k, v)
    record(db, user.id, "civil_rate_set", s.id, "update", after=body.model_dump(exclude_unset=True))
    db.commit()
    return _set_out(s, len(s.rates))


@router.delete("/civil/rate-sets/{set_id}", status_code=204)
def delete_rate_set(set_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    s = get_or_404(db, CivilRateSet, set_id)
    record(db, user.id, "civil_rate_set", s.id, "delete", before={"name": s.name})
    civil.delete_rate_set(db, set_id)
    db.commit()


@router.get("/civil/rate-sets/{set_id}/rates")
def list_rates(set_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    get_or_404(db, CivilRateSet, set_id)
    return [{"id": r.id, "code": r.code, "category": r.category, "description": r.description, "unit": r.unit,
             "rate": r.rate, "qty": r.qty} for r in db.scalars(select(CivilRate).where(CivilRate.set_id == set_id).order_by(CivilRate.id))]


@router.get("/civil/rates/search")
def search_rates(q: str, unit: str = "", db: Session = Depends(get_db), _: User = Depends(current_user)):
    """Past rates that look like this description, best first."""
    probe = CivilBoqLine(description=q, unit=unit)
    rates = list(db.scalars(select(CivilRate).join(CivilRateSet).where(CivilRateSet.active.is_(True))))
    sets = {s.id: s.name for s in db.scalars(select(CivilRateSet))}
    return [{"id": r.id, "job": sets.get(r.set_id, ""), "description": r.description, "unit": r.unit, "rate": r.rate,
             "match": round(score, 2)} for score, r in civil.candidates(probe, rates, n=15)]


# --- the BOQ ---
def _line_out(l: CivilBoqLine, items: list[CivilTakeoffItem], sheets: dict) -> dict:
    qty = civil.line_qty(l)
    return {
        "id": l.id, "sort": l.sort, "category": l.category, "description": l.description, "unit": l.unit,
        "qty": l.qty, "overridden_qty": l.overridden_qty, "effective_qty": qty, "combine": l.combine,
        "rate": l.rate, "rate_overridden": l.rate_overridden, "rate_sources": l.rate_sources or [], "rate_note": l.rate_note,
        "amount": float(civil.money(qty) * civil.money(l.rate or 0)), "needs_measuring": l.needs_measuring,
        "status": l.status, "source": l.source, "note": l.note,
        "items": [{"id": i.id, "sheet_id": i.sheet_id,
                   "sheet": (sheets[i.sheet_id].sheet_no or f"p{sheets[i.sheet_id].page_no}") if i.sheet_id in sheets else "",
                   "description": i.description, "unit": i.unit, "qty": i.qty, "basis": i.basis,
                   "confidence": i.confidence} for i in items if i.line_id == l.id],
    }


@router.get("/jobs/{job_id}/civil/boq")
def get_boq(job_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    get_or_404(db, Job, job_id)
    lines = sorted(db.scalars(select(CivilBoqLine).where(CivilBoqLine.job_id == job_id)), key=lambda l: l.sort)
    items = list(db.scalars(select(CivilTakeoffItem).where(CivilTakeoffItem.job_id == job_id)))
    sheets = {s.id: s for s in db.scalars(select(Sheet).where(Sheet.job_id == job_id))}
    return {"lines": [_line_out(l, items, sheets) for l in lines], "summary": civil.civil_summary(db, job_id),
            "categories": civil.CATEGORIES, "units": ["m", "m2", "m3", "ea", "t", "item"]}


class LineIn(BaseModel):
    category: str = "Other"
    description: str
    unit: str = "item"
    qty: float = 0.0
    rate: float | None = None
    note: str = ""


class LinePatch(BaseModel):
    category: str | None = None
    description: str | None = None
    unit: str | None = None
    overridden_qty: float | None = None
    clear_qty_override: bool = False
    rate: float | None = None
    clear_rate: bool = False  # go back to the suggested rate from previous jobs
    status: str | None = None
    note: str | None = None


def _require_civil(job: Job) -> None:
    if job.kind != "civil":
        raise HTTPException(409, "This isn't a civil job")


@router.post("/jobs/{job_id}/civil/lines")
def add_line(job_id: int, body: LineIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    job = get_or_404(db, Job, job_id)
    _require_civil(job)
    ensure_open(db, job_id)
    last = max([l.sort for l in db.scalars(select(CivilBoqLine).where(CivilBoqLine.job_id == job_id))], default=0)
    l = CivilBoqLine(job_id=job_id, sort=last + 1, category=body.category, description=body.description,
                     unit=civil.norm_unit(body.unit), qty=body.qty, rate=body.rate, rate_overridden=body.rate is not None,
                     note=body.note, status="confirmed", source="manual", needs_measuring=False)
    db.add(l)
    db.flush()
    record(db, user.id, "civil_line", l.id, "create", after=snapshot(l))
    if body.rate is None:
        civil.reprice(db, job_id)
    db.commit()
    return _line_out(l, [], {})


@router.patch("/civil/lines/{line_id}")
def update_line(line_id: int, body: LinePatch, db: Session = Depends(get_db), user: User = Depends(current_user)):
    l = get_or_404(db, CivilBoqLine, line_id)
    ensure_open(db, l.job_id)
    before = snapshot(l)
    data = body.model_dump(exclude_unset=True)
    for k in ("category", "description", "note"):
        if k in data and data[k] is not None:
            setattr(l, k, data[k])
    if data.get("unit"):
        l.unit = civil.norm_unit(data["unit"])
    if "overridden_qty" in data:
        l.overridden_qty = data["overridden_qty"]
        if l.overridden_qty is not None and l.overridden_qty > 0:
            l.needs_measuring = False
    if body.clear_qty_override:
        l.overridden_qty = None
    if "rate" in data and data["rate"] is not None:
        l.rate, l.rate_overridden, l.rate_note = data["rate"], True, "Entered by hand"
    if body.clear_rate:
        l.rate_overridden = False
        db.flush()
        civil.reprice(db, l.job_id)
    if body.status is not None:
        if body.status not in ("suggested", "confirmed"):
            raise HTTPException(422, "status must be suggested or confirmed")
        l.status = body.status
    record(db, user.id, "civil_line", l.id, "update", before, snapshot(l))
    db.commit()
    items = list(db.scalars(select(CivilTakeoffItem).where(CivilTakeoffItem.line_id == l.id)))
    sheets = {s.id: s for s in db.scalars(select(Sheet).where(Sheet.job_id == l.job_id))}
    return _line_out(l, items, sheets)


@router.delete("/civil/lines/{line_id}", status_code=204)
def delete_line(line_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    l = get_or_404(db, CivilBoqLine, line_id)
    ensure_open(db, l.job_id)
    record(db, user.id, "civil_line", l.id, "delete", before=snapshot(l))
    # Its sheet quantities go too, so running the autopilot again doesn't bring the line straight back.
    for i in db.scalars(select(CivilTakeoffItem).where(CivilTakeoffItem.line_id == l.id)):
        db.delete(i)
    db.delete(l)
    db.commit()


@router.post("/jobs/{job_id}/civil/approve-all")
def approve_all(job_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Approve every suggested line that has a quantity. Lines still needing measuring stay as they are."""
    job = get_or_404(db, Job, job_id)
    _require_civil(job)
    ensure_open(db, job_id)
    if autopilot.is_running(job_id):
        raise HTTPException(409, "Wait for the read to finish before approving")
    n, skipped = 0, 0
    for l in db.scalars(select(CivilBoqLine).where(CivilBoqLine.job_id == job_id, CivilBoqLine.status == "suggested")):
        if l.needs_measuring and not civil.line_qty(l):
            skipped += 1
            continue
        before = snapshot(l)
        l.status = "confirmed"
        record(db, user.id, "civil_line", l.id, "update", before, snapshot(l))
        n += 1
    db.commit()
    return {"approved": n, "skipped_need_measuring": skipped, "summary": civil.civil_summary(db, job_id)}


@router.post("/jobs/{job_id}/civil/reprice")
def reprice(job_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Look the rates up again (e.g. after loading more previous jobs). Hand-typed rates are kept."""
    job = get_or_404(db, Job, job_id)
    _require_civil(job)
    ensure_open(db, job_id)
    n = civil.reprice(db, job_id, get_reader())
    record(db, user.id, "job", job_id, "civil_reprice", after={"job_id": job_id, "priced": n})
    db.commit()
    return {"priced": n, "summary": civil.civil_summary(db, job_id)}


@router.get("/jobs/{job_id}/civil/boq.xlsx")
def export(job_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    job = get_or_404(db, Job, job_id)
    _require_civil(job)
    data = civil.export_boq(db, job)
    fname = re.sub(r"[^A-Za-z0-9_-]+", "_", f"{job.quote_no or job.id}_{job.name}")[:80] + "_Civil_BOQ.xlsx"
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{fname}"'})
