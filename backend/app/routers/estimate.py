"""Per-job Phase 2 endpoints: generated fittings and sundries, check-measure flags, sign-off, audit."""
from collections import defaultdict
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import record, snapshot
from ..auth import current_user
from ..checks import run_checks
from ..db import get_db
from ..models import AuditLog, Flag, GeneratedItem, Job, Service, Stage, User
from ..rules import DISCLAIMER, effective_qty, generate
from ..schemas import AuditOut, FlagOut, FlagPatch, GeneratedItemOut, GeneratedItemPatch, JobOut, ManualItemIn
from ..takeoff import job_totals
from . import get_or_404

router = APIRouter(prefix="/api", tags=["estimate"])

FLAG_STATUSES = ("open", "resolved", "accepted")


def ensure_job_open(job: Job):
    if job.status == "final":
        raise HTTPException(409, "This estimate is final. A reviewer must reopen it before anything changes.")


def require_reviewer(user: User = Depends(current_user)) -> User:
    if user.role not in ("reviewer", "admin"):
        raise HTTPException(403, "Only a reviewer or admin can do this")
    return user


# --- fittings and sundries ---
@router.post("/jobs/{job_id}/generate")
def generate_items(job_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    job = get_or_404(db, Job, job_id)
    ensure_job_open(job)
    result = generate(db, job_id)
    record(db, user.id, "job", job_id, "generate", after=result)
    db.commit()
    return result


@router.get("/jobs/{job_id}/generated", response_model=list[GeneratedItemOut])
def list_generated(job_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    return db.scalars(select(GeneratedItem).where(GeneratedItem.job_id == job_id).order_by(GeneratedItem.id)).all()


@router.post("/jobs/{job_id}/generated", response_model=GeneratedItemOut)
def add_manual_item(job_id: int, body: ManualItemIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    job = get_or_404(db, Job, job_id)
    ensure_job_open(job)
    if body.service_id is not None:
        get_or_404(db, Service, body.service_id)
    if body.stage_id is not None:
        get_or_404(db, Stage, body.stage_id)
    g = GeneratedItem(job_id=job_id, source_ref="manual", stage_overridden=True, **body.model_dump())
    db.add(g)
    db.flush()
    record(db, user.id, "generated_item", g.id, "create", after=snapshot(g))
    db.commit()
    return g


@router.patch("/generated/{item_id}", response_model=GeneratedItemOut)
def update_generated(item_id: int, body: GeneratedItemPatch, db: Session = Depends(get_db), user: User = Depends(current_user)):
    g = get_or_404(db, GeneratedItem, item_id)
    ensure_job_open(db.get(Job, g.job_id))
    before = snapshot(g)
    data = body.model_dump(exclude_unset=True)
    if data.get("clear_override"):
        g.overridden_qty = None
    elif "overridden_qty" in data:
        if g.rule_id is None:
            g.qty = data["overridden_qty"] or 0  # manual lines: just change the quantity
        else:
            g.overridden_qty = data["overridden_qty"]
    if "stage_id" in data:
        if data["stage_id"] is not None:
            get_or_404(db, Stage, data["stage_id"])
        g.stage_id = data["stage_id"]
        g.stage_overridden = True
    if "note" in data:
        g.note = data["note"] or ""
    record(db, user.id, "generated_item", g.id, "update", before, snapshot(g))
    db.commit()
    return g


@router.delete("/generated/{item_id}", status_code=204)
def delete_generated(item_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    g = get_or_404(db, GeneratedItem, item_id)
    ensure_job_open(db.get(Job, g.job_id))
    if g.rule_id is not None:
        raise HTTPException(409, "Rule-generated lines come back on regenerate. Set the quantity to 0 instead, with a note.")
    record(db, user.id, "generated_item", g.id, "delete", before=snapshot(g))
    db.delete(g)
    db.commit()


def fittings_summary(db: Session, job_id: int) -> list[dict]:
    """Generated items added up by service, description, unit and stage."""
    services = {s.id: s for s in db.scalars(select(Service))}
    stages = {s.id: s for s in db.scalars(select(Stage))}
    rows: dict[tuple, dict] = {}
    for g in db.scalars(select(GeneratedItem).where(GeneratedItem.job_id == job_id)):
        q = effective_qty(g)
        if q <= 0:
            continue
        svc = services.get(g.service_id)
        st = stages.get(g.stage_id)
        key = (st.order if st else 999, svc.order if svc else 999, g.description, g.uom)
        row = rows.setdefault(key, {"stage": st.name if st else "Unstaged", "service_code": svc.code if svc else "",
                                    "description": g.description, "uom": g.uom, "qty": 0.0, "lines": 0})
        row["qty"] = round(row["qty"] + q, 3)
        row["lines"] += 1
    return [rows[k] for k in sorted(rows)]


@router.get("/jobs/{job_id}/fittings-summary")
def get_fittings_summary(job_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    return {"rows": fittings_summary(db, job_id), "disclaimer": DISCLAIMER}


@router.get("/jobs/{job_id}/stage-matrix")
def stage_matrix(job_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    """Pipe metres by stage (rows) and service (columns), with row and column totals that reconcile."""
    t = job_totals(db, job_id)
    stages = [s.name for s in db.scalars(select(Stage).order_by(Stage.order))] + ["Unstaged"]
    cells: dict[str, dict[str, float]] = defaultdict(dict)
    for row in t["stages"]:
        cells[row["stage"]][row["service_code"]] = row["total_m"]
    services = [s["service_code"] for s in t["services"]]
    rows = [{"stage": st, "cells": cells.get(st, {}), "total_m": round(sum(cells.get(st, {}).values()), 2)}
            for st in stages if st in cells]
    col_totals = {code: next(s["total_m"] for s in t["services"] if s["service_code"] == code) for code in services}
    return {"services": services, "rows": rows, "service_totals": col_totals, "grand_total_m": t["grand_total_m"]}


# --- check-measure ---
@router.post("/jobs/{job_id}/checks", response_model=list[FlagOut])
def check_measure(job_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    get_or_404(db, Job, job_id)
    flags = run_checks(db, job_id)
    record(db, user.id, "job", job_id, "check_measure", after={"flags": len(flags), "open": sum(f.status == "open" for f in flags)})
    db.commit()
    return flags


@router.get("/jobs/{job_id}/flags", response_model=list[FlagOut])
def list_flags(job_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    return db.scalars(select(Flag).where(Flag.job_id == job_id).order_by(Flag.severity, Flag.check_type, Flag.id)).all()


@router.patch("/flags/{flag_id}", response_model=FlagOut)
def update_flag(flag_id: int, body: FlagPatch, db: Session = Depends(get_db), user: User = Depends(current_user)):
    flag = get_or_404(db, Flag, flag_id)
    if body.status not in FLAG_STATUSES:
        raise HTTPException(422, "Status must be open, resolved or accepted")
    if body.status != "open" and not body.note.strip():
        raise HTTPException(422, "Add a note saying how this was resolved or why it's accepted")
    before = snapshot(flag)
    flag.status = body.status
    flag.note = body.note.strip()
    flag.resolved_by = None if body.status == "open" else user.id
    record(db, user.id, "flag", flag.id, "update", before, snapshot(flag))
    db.commit()
    return flag


@router.post("/jobs/{job_id}/finalise", response_model=JobOut)
def finalise(job_id: int, db: Session = Depends(get_db), user: User = Depends(require_reviewer)):
    """Reviewer sign-off. Re-runs check-measure first; any open flag blocks it."""
    job = get_or_404(db, Job, job_id)
    ensure_job_open(job)
    flags = run_checks(db, job_id)
    open_flags = [f for f in flags if f.status == "open"]
    if open_flags:
        raise HTTPException(409, f"{len(open_flags)} check-measure flag(s) are still open. Resolve or accept each with a note first.")
    before = snapshot(job)
    job.status = "final"
    job.signed_off_by = user.id
    job.signed_off_at = datetime.now(timezone.utc)
    record(db, user.id, "job", job.id, "finalise", before, snapshot(job))
    db.commit()
    return job


@router.post("/jobs/{job_id}/reopen", response_model=JobOut)
def reopen(job_id: int, db: Session = Depends(get_db), user: User = Depends(require_reviewer)):
    job = get_or_404(db, Job, job_id)
    before = snapshot(job)
    job.status = "draft"
    job.signed_off_by = None
    job.signed_off_at = None
    record(db, user.id, "job", job.id, "reopen", before, snapshot(job))
    db.commit()
    return job


# --- audit log ---
@router.get("/jobs/{job_id}/audit", response_model=list[AuditOut])
def job_audit(job_id: int, limit: int = 200, db: Session = Depends(get_db), _: User = Depends(current_user)):
    """Changes to this job and everything in it, deleted items included."""
    q = select(AuditLog).where(AuditLog.job_id == job_id).order_by(AuditLog.id.desc()).limit(min(limit, 1000))
    names = {u.id: u.name or u.email for u in db.scalars(select(User))}
    return [AuditOut.model_validate(e).model_copy(update={"user_name": names.get(e.user_id, "")}) for e in db.scalars(q)]
