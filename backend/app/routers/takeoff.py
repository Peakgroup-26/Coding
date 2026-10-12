"""Runs (traced pipe) and counts."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import record, snapshot
from ..auth import current_user
from ..db import get_db
from ..models import CountItem, CountType, Level, Material, Run, Service, Sheet, Stage, User
from ..schemas import CountIn, CountOut, CountPatch, RunIn, RunOut, RunPatch
from ..takeoff import recompute_run, resolve_scale
from . import ensure_open, get_or_404

router = APIRouter(prefix="/api", tags=["takeoff"])

STATUSES = ("suggested", "confirmed")
VERTICAL_MODES = ("none", "manual", "levels")


def _check_refs(db: Session, job_id: int, data: dict) -> None:
    if "service_id" in data and data["service_id"] is not None:
        get_or_404(db, Service, data["service_id"])
    if data.get("stage_id") is not None:
        get_or_404(db, Stage, data["stage_id"])
    for k in ("level_id", "vertical_from_level_id", "vertical_to_level_id"):
        if data.get(k) is not None:
            lvl = get_or_404(db, Level, data[k])
            if lvl.job_id != job_id:
                raise HTTPException(422, "That level belongs to another job")
    if data.get("status") is not None and data["status"] not in STATUSES:
        raise HTTPException(422, "Status must be suggested or confirmed")
    if data.get("vertical_mode") is not None and data["vertical_mode"] not in VERTICAL_MODES:
        raise HTTPException(422, "Vertical mode must be none, manual or levels")


def _waste_for(db: Session, material: str) -> float:
    m = db.scalar(select(Material).where(Material.name == material))
    return m.waste_pct if m else 0.0


def _ensure_editable(sheet: Sheet, db: Session):
    ensure_open(db, sheet.job_id)
    if not sheet.is_current:
        raise HTTPException(409, "This sheet has been superseded by a later revision. Measure on the current one.")


# --- runs ---
@router.get("/sheets/{sheet_id}/runs", response_model=list[RunOut])
def sheet_runs(sheet_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    return db.scalars(select(Run).where(Run.sheet_id == sheet_id).order_by(Run.id)).all()


@router.get("/jobs/{job_id}/runs", response_model=list[RunOut])
def job_runs(job_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    return db.scalars(select(Run).where(Run.job_id == job_id).order_by(Run.id)).all()


@router.post("/sheets/{sheet_id}/runs", response_model=RunOut)
def create_run(sheet_id: int, body: RunIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    sheet = get_or_404(db, Sheet, sheet_id)
    _ensure_editable(sheet, db)
    data = body.model_dump()
    _check_refs(db, sheet.job_id, data)
    m_per_pt, viewport_id = resolve_scale(sheet, data["geometry"])
    if data["stage_id"] is None:
        data["stage_id"] = db.get(Service, data["service_id"]).default_stage_id
    if data["waste_pct"] is None:
        data["waste_pct"] = _waste_for(db, data["material"])
    data["geometry"] = [list(p) for p in data["geometry"]]
    run = Run(job_id=sheet.job_id, sheet_id=sheet.id, viewport_id=viewport_id, m_per_pt=m_per_pt,
              source="manual", created_by=user.id, **data)
    recompute_run(db, run)
    db.add(run)
    db.flush()
    record(db, user.id, "run", run.id, "create", after=snapshot(run))
    db.commit()
    return run


@router.patch("/runs/{run_id}", response_model=RunOut)
def update_run(run_id: int, body: RunPatch, db: Session = Depends(get_db), user: User = Depends(current_user)):
    run = get_or_404(db, Run, run_id)
    sheet = db.get(Sheet, run.sheet_id)
    _ensure_editable(sheet, db)
    data = body.model_dump(exclude_unset=True)
    _check_refs(db, run.job_id, data)
    before = snapshot(run)
    if "geometry" in data:
        run.m_per_pt, run.viewport_id = resolve_scale(sheet, data["geometry"])
        data["geometry"] = [list(p) for p in data["geometry"]]
    if "material" in data and "waste_pct" not in data:
        data["waste_pct"] = _waste_for(db, data["material"])
    for k, v in data.items():
        setattr(run, k, v)
    recompute_run(db, run)
    record(db, user.id, "run", run.id, "update", before, snapshot(run))
    db.commit()
    return run


@router.delete("/runs/{run_id}", status_code=204)
def delete_run(run_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    run = get_or_404(db, Run, run_id)
    ensure_open(db, run.job_id)
    record(db, user.id, "run", run.id, "delete", before=snapshot(run))
    db.delete(run)
    db.commit()


# --- counts ---
@router.get("/sheets/{sheet_id}/counts", response_model=list[CountOut])
def sheet_counts(sheet_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    return db.scalars(select(CountItem).where(CountItem.sheet_id == sheet_id).order_by(CountItem.id)).all()


@router.post("/sheets/{sheet_id}/counts", response_model=CountOut)
def create_count(sheet_id: int, body: CountIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    sheet = get_or_404(db, Sheet, sheet_id)
    _ensure_editable(sheet, db)
    data = body.model_dump()
    _check_refs(db, sheet.job_id, data)
    if not (0 <= data["x"] <= sheet.width_pt and 0 <= data["y"] <= sheet.height_pt):
        raise HTTPException(422, "Point is outside the sheet")
    if data["stage_id"] is None:
        ct = db.scalar(select(CountType).where(CountType.name == data["item_type"]))
        data["stage_id"] = (ct.default_stage_id if ct else None) or db.get(Service, data["service_id"]).default_stage_id
    item = CountItem(job_id=sheet.job_id, sheet_id=sheet.id, source="manual", created_by=user.id, **data)
    db.add(item)
    db.flush()
    record(db, user.id, "count", item.id, "create", after=snapshot(item))
    db.commit()
    return item


@router.patch("/counts/{count_id}", response_model=CountOut)
def update_count(count_id: int, body: CountPatch, db: Session = Depends(get_db), user: User = Depends(current_user)):
    item = get_or_404(db, CountItem, count_id)
    _ensure_editable(db.get(Sheet, item.sheet_id), db)
    data = body.model_dump(exclude_unset=True)
    _check_refs(db, item.job_id, data)
    before = snapshot(item)
    for k, v in data.items():
        setattr(item, k, v)
    record(db, user.id, "count", item.id, "update", before, snapshot(item))
    db.commit()
    return item


@router.delete("/counts/{count_id}", status_code=204)
def delete_count(count_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    item = get_or_404(db, CountItem, count_id)
    ensure_open(db, item.job_id)
    record(db, user.id, "count", item.id, "delete", before=snapshot(item))
    db.delete(item)
    db.commit()
