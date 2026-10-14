"""Drop the plans in: start a job from a set of PDFs, watch it read, and approve what it found."""
import re

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import autopilot
from ..audit import record, snapshot
from ..auth import current_user
from ..checks import run_checks
from ..db import get_db
from ..models import AiOutcome, CountItem, Job, Run, Sheet, StyleMapping, User
from ..rules import generate
from ..schemas import JobOut
from . import ensure_open, get_or_404
from .jobs import store_upload

router = APIRouter(prefix="/api", tags=["autopilot"])


def _job_name(files: list[UploadFile]) -> str:
    stem = re.sub(r"\.pdf$", "", files[0].filename or "New job", flags=re.IGNORECASE)
    return re.sub(r"[_-]+", " ", stem).strip()[:200] or "New job"


@router.post("/quick-start", response_model=JobOut)
async def quick_start(
    files: list[UploadFile] = File(...),
    kind: str = Form("hydraulic"),
    name: str = Form(""),
    client: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """Make a job from a set of plans and start reading them straight away."""
    if kind not in ("hydraulic", "civil"):
        raise HTTPException(422, "kind must be hydraulic or civil")
    job = Job(name=name.strip() or _job_name(files), client=client.strip(), kind=kind)
    db.add(job)
    db.flush()
    for up in files:
        await store_upload(db, job, up, user, status="queued")
    record(db, user.id, "job", job.id, "create", after=snapshot(job))
    db.commit()
    autopilot.start(job.id, user.id)
    db.refresh(job)
    return job


@router.post("/jobs/{job_id}/add-plans", response_model=JobOut)
async def add_plans(job_id: int, files: list[UploadFile] = File(...), db: Session = Depends(get_db),
                    user: User = Depends(current_user)):
    """Add more drawings (or a new revision) and read them."""
    job = get_or_404(db, Job, job_id)
    ensure_open(db, job.id)
    if autopilot.is_running(job.id):
        raise HTTPException(409, "This job is still being read. Add the plans when it has finished.")
    for up in files:
        await store_upload(db, job, up, user, status="queued")
    db.commit()
    autopilot.start(job.id, user.id)
    db.refresh(job)
    return job


class RunIn(BaseModel):
    reread: bool = False  # read sheets again even if the AI has already read them


@router.post("/jobs/{job_id}/autopilot", response_model=JobOut)
def rerun(job_id: int, body: RunIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    job = get_or_404(db, Job, job_id)
    ensure_open(db, job.id)
    if not autopilot.start(job.id, user.id, body.reread):
        raise HTTPException(409, "This job is already being read")
    db.refresh(job)
    return job


@router.get("/jobs/{job_id}/autopilot")
def status(job_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    job = get_or_404(db, Job, job_id)
    out = dict(job.autopilot or {"state": "never"})
    if job.kind == "civil":
        from ..civil import civil_summary

        out["summary"] = civil_summary(db, job.id)
    else:
        out["summary"] = autopilot.summary(db, job.id)
    out["running"] = autopilot.is_running(job.id)
    return out


@router.post("/jobs/{job_id}/approve-all")
def approve_all(job_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Approve every suggested run and count on the current sheets, then rebuild the estimate.

    The AI's line-colour choices are saved for this client once they're approved, so the next
    job from the same consultant is read the same way.
    """
    job = get_or_404(db, Job, job_id)
    ensure_open(db, job.id)
    if autopilot.is_running(job.id):
        raise HTTPException(409, "Wait for the read to finish before approving")
    current = set(db.scalars(select(Sheet.id).where(Sheet.job_id == job.id, Sheet.is_current.is_(True))))
    approved = {"runs": 0, "counts": 0}
    styles_seen: dict[tuple, tuple] = {}
    for kind, model in (("run", Run), ("count", CountItem)):
        for obj in db.scalars(select(model).where(model.job_id == job.id, model.status == "suggested")):
            if obj.sheet_id not in current:
                continue
            if obj.source == "ai":
                db.add(AiOutcome(job_id=obj.job_id, sheet_id=obj.sheet_id, kind=kind,
                                 outcome="edited" if obj.ai_edited else "accepted"))
            before = snapshot(obj)
            obj.status = "confirmed"
            record(db, user.id, kind, obj.id, "update", before, snapshot(obj))
            approved["runs" if kind == "run" else "counts"] += 1
            if kind == "run":
                styles_seen[(obj.service_id, obj.dn, obj.material)] = (obj.sheet_id, obj.geometry)
    _remember_styles(db, job, styles_seen)
    db.flush()
    gen = generate(db, job.id)
    flags = run_checks(db, job.id)
    record(db, user.id, "job", job.id, "approve_all", after={"job_id": job.id, **approved})
    db.commit()
    return {**approved, "estimate_lines": gen["lines"], "flags": len(flags)}


def _remember_styles(db: Session, job: Job, seen: dict) -> None:
    """Save the line styles behind approved AI runs as this client's mappings."""
    from ..suggest import extract_segments

    client = job.client or ""
    by_sheet: dict[int, list] = {}
    for (service_id, dn, material), (sheet_id, geometry) in seen.items():
        by_sheet.setdefault(sheet_id, []).append((service_id, dn, material, geometry))
    for sheet_id, runs in by_sheet.items():
        sheet = db.get(Sheet, sheet_id)
        styles = extract_segments(sheet)
        for service_id, dn, material, geometry in runs:
            if len(geometry) < 2:
                continue
            a, b = geometry[0], geometry[1]
            key = next((k for k, st in styles.items() if any(_touches(seg, a, b) for seg in st["segments"])), None)
            if key is None:
                continue
            m = db.scalar(select(StyleMapping).where(StyleMapping.client == client, StyleMapping.style_key == key))
            if m is None:
                m = StyleMapping(client=client, style_key=key)
                db.add(m)
            m.service_id, m.dn, m.material = service_id, dn, material


def _touches(seg, a, b, tol: float = 1.5) -> bool:
    """Whether a segment runs under the middle of a run's first leg (from a to b)."""
    import math

    def on(p):
        x1, y1, x2, y2 = seg
        dx, dy = x2 - x1, y2 - y1
        L = math.hypot(dx, dy)
        if L == 0:
            return False
        t = ((p[0] - x1) * dx + (p[1] - y1) * dy) / (L * L)
        if t < -0.01 or t > 1.01:
            return False
        return abs((p[0] - x1) * dy - (p[1] - y1) * dx) / L <= tol

    return on([(a[0] + b[0]) / 2, (a[1] + b[1]) / 2])
