import re
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import config, storage
from ..audit import record, snapshot
from ..auth import current_user
from ..db import get_db
from ..export import build_workbook
from ..models import DrawingFile, Job, Level, Run, User
from ..pdf_processing import process_file
from ..schemas import FileOut, JobIn, JobOut, JobPatch, LevelIn, LevelOut, SheetOut
from ..takeoff import job_totals, recompute_run
from . import get_or_404

router = APIRouter(prefix="/api", tags=["jobs"])


@router.get("/jobs", response_model=list[JobOut])
def list_jobs(db: Session = Depends(get_db), _: User = Depends(current_user)):
    return db.scalars(select(Job).order_by(Job.id.desc())).all()


@router.post("/jobs", response_model=JobOut)
def create_job(body: JobIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    job = Job(**body.model_dump())
    db.add(job)
    db.flush()
    record(db, user.id, "job", job.id, "create", after=snapshot(job))
    db.commit()
    return job


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    return get_or_404(db, Job, job_id)


@router.patch("/jobs/{job_id}", response_model=JobOut)
def update_job(job_id: int, body: JobPatch, db: Session = Depends(get_db), user: User = Depends(current_user)):
    job = get_or_404(db, Job, job_id)
    before = snapshot(job)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(job, k, v)
    record(db, user.id, "job", job.id, "update", before, snapshot(job))
    db.commit()
    return job


# --- drawings ---
@router.get("/jobs/{job_id}/files", response_model=list[FileOut])
def list_files(job_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    return db.scalars(select(DrawingFile).where(DrawingFile.job_id == job_id).order_by(DrawingFile.id)).all()


@router.post("/jobs/{job_id}/files", response_model=list[SheetOut])
async def upload_files(
    job_id: int,
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """Upload one combined PDF or many single-page PDFs. Each is split into sheets."""
    job = get_or_404(db, Job, job_id)
    created = []
    for up in files:
        name = up.filename or "drawing.pdf"
        if not name.lower().endswith(".pdf"):
            raise HTTPException(422, f"{name} is not a PDF")
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", name)[-120:]
        key = f"jobs/{job.id}/originals/{uuid.uuid4().hex}-{safe}"
        size = 0
        with open(storage.local_path(key), "wb") as out:
            while chunk := await up.read(1024 * 1024):
                size += len(chunk)
                if size > config.MAX_UPLOAD_BYTES:
                    out.close()
                    storage.local_path(key).unlink(missing_ok=True)
                    raise HTTPException(413, f"{name} is larger than {config.MAX_UPLOAD_BYTES // (1024 * 1024)} MB")
                out.write(chunk)
        with open(storage.local_path(key), "rb") as f:
            if f.read(5) != b"%PDF-":
                storage.local_path(key).unlink(missing_ok=True)
                raise HTTPException(422, f"{name} is not a valid PDF")
        drawing = DrawingFile(job_id=job.id, filename=name, storage_key=key, uploaded_by=user.id)
        db.add(drawing)
        db.flush()
        created.extend(process_file(db, drawing))
        if drawing.status == "failed":
            raise HTTPException(422, drawing.error)
    return created


# --- levels ---
@router.get("/jobs/{job_id}/levels", response_model=list[LevelOut])
def list_levels(job_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    return db.scalars(select(Level).where(Level.job_id == job_id).order_by(Level.rl)).all()


@router.post("/jobs/{job_id}/levels", response_model=LevelOut)
def create_level(job_id: int, body: LevelIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    get_or_404(db, Job, job_id)
    level = Level(job_id=job_id, **body.model_dump())
    db.add(level)
    db.flush()
    record(db, user.id, "level", level.id, "create", after=snapshot(level))
    db.commit()
    return level


def _refresh_level_verticals(db: Session, job_id: int):
    for run in db.scalars(select(Run).where(Run.job_id == job_id, Run.vertical_mode == "levels")):
        try:
            recompute_run(db, run)
        except HTTPException:
            # The level it pointed at is gone; keep the old figure and flag it in the note.
            run.note = (run.note + " [level changed: check vertical]").strip()


@router.put("/levels/{level_id}", response_model=LevelOut)
def update_level(level_id: int, body: LevelIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    level = get_or_404(db, Level, level_id)
    before = snapshot(level)
    for k, v in body.model_dump().items():
        setattr(level, k, v)
    db.flush()
    _refresh_level_verticals(db, level.job_id)
    record(db, user.id, "level", level.id, "update", before, snapshot(level))
    db.commit()
    return level


@router.delete("/levels/{level_id}", status_code=204)
def delete_level(level_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    level = get_or_404(db, Level, level_id)
    job_id = level.job_id
    record(db, user.id, "level", level.id, "delete", before=snapshot(level))
    db.delete(level)
    db.flush()
    _refresh_level_verticals(db, job_id)
    db.commit()


# --- totals and export ---
@router.get("/jobs/{job_id}/totals")
def totals(job_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    get_or_404(db, Job, job_id)
    return job_totals(db, job_id)


@router.get("/jobs/{job_id}/export.xlsx")
def export_xlsx(job_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    job = get_or_404(db, Job, job_id)
    data = build_workbook(db, job_id)
    fname = re.sub(r"[^A-Za-z0-9_-]+", "_", f"{job.quote_no or job.id}_{job.name}")[:80] + "_BOQ.xlsx"
    return Response(
        data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )
