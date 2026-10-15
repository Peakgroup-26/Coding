"""Autopilot: drop the plans in and the app sorts and takes off the set by itself.

For a hydraulic job it:
  1. splits the PDFs into sheets and reads each one (number, title, revision, scale, services),
  2. sets each plan's scale from its title block and confirms it against dimensions on the sheet,
  3. works out which line colours are which pipes and traces them into runs,
  4. counts items that are tagged on the plans (FW, IO, HR ...).

A civil job goes to civil.run_civil instead.

Everything it finds is a suggestion. Nothing reaches a total, a price or an export until a
person approves it ("Approve all" or one at a time), and anything it couldn't do safely (a
scale it couldn't confirm, line colours it couldn't name) goes on a "needs you" list instead
of being guessed.
"""
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import config
from .ai import AIUnavailable, get_reader
from .assist import count_tagged_items, create_suggested_runs, read_and_apply
from .audit import record, snapshot
from .autoscale import check_dimensions
from .db import SessionLocal
from .models import CountItem, DrawingFile, Job, Material, Run, Service, Sheet, StyleMapping, User
from .pdf_processing import process_file
from .suggest import extract_segments, style_summary

log = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=config.AUTOPILOT_WORKERS, thread_name_prefix="autopilot")
_running: set[int] = set()
_lock = threading.Lock()

MIN_STYLE_CONFIDENCE = 0.5
TAKEOFF_TYPES = ("plan",)  # sections, details and schematics would double count plan runs


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def label(sheet: Sheet) -> str:
    return f"{sheet.sheet_no or 'p' + str(sheet.page_no)} {sheet.title or ''}".strip()


def is_running(job_id: int) -> bool:
    return job_id in _running


def start(job_id: int, user_id: int, reread: bool = False) -> bool:
    """Queue the autopilot for a job. False if it's already running."""
    with _lock:
        if job_id in _running:
            return False
        _running.add(job_id)
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        job.autopilot = {"state": "queued", "step": "Waiting to start", "done": 0, "total": 0, "started_at": _now(),
                         "attention": [], "summary": {}}
        db.commit()
    if config.AUTOPILOT_SYNC:
        _run(job_id, user_id, reread)
    else:
        _executor.submit(_run, job_id, user_id, reread)
    return True


class Progress:
    def __init__(self, db: Session, job: Job):
        self.db, self.job = db, job
        self.status = dict(job.autopilot or {})
        self.status.setdefault("attention", [])
        self.status.setdefault("summary", {})
        self.status["state"] = "running"

    def step(self, text: str, done: int = 0, total: int = 0) -> None:
        self.status.update(step=text, done=done, total=total)
        self._save()

    def attention(self, kind: str, message: str, sheet: Sheet | None = None) -> None:
        item = {"kind": kind, "message": message}
        if sheet is not None:
            item.update(sheet_id=sheet.id, sheet=label(sheet))
        self.status["attention"].append(item)

    def _save(self) -> None:
        self.job.autopilot = dict(self.status)  # a new dict, so the JSON column registers the change
        self.db.commit()


def _run(job_id: int, user_id: int, reread: bool) -> None:
    db = SessionLocal()
    try:
        job = db.get(Job, job_id)
        user = db.get(User, user_id)
        p = Progress(db, job)
        p.status["attention"] = []
        queued = list(db.scalars(select(DrawingFile).where(DrawingFile.job_id == job_id, DrawingFile.status == "queued")))
        for i, f in enumerate(queued):
            p.step(f"Splitting {f.filename} into sheets", i, len(queued))
            process_file(db, f)
            if f.status == "failed":
                p.attention("file", f"{f.filename}: {f.error}")
        reader = get_reader()
        # Tender documents first, so what they say can steer the reading of the drawings.
        from .tender import context_for, read_documents

        read_documents(db, job, user, p, reader)
        if reader is not None:
            reader.context = context_for(db, job.id)
        if job.kind == "civil":
            from .civil import run_civil

            run_civil(db, job, user, p, reader, reread)
        else:
            _run_hydraulic(db, job, user, p, reader, reread)
        p.status.update(state="done", step="Finished", finished_at=_now())
        p._save()
    except Exception as e:  # keep the reason on the job so the screen can show it
        log.exception("Autopilot failed for job %s", job_id)
        db.rollback()
        job = db.get(Job, job_id)
        status = dict(job.autopilot or {})
        status.update(state="failed", step="Stopped", error=str(e) or e.__class__.__name__, finished_at=_now())
        job.autopilot = status
        db.commit()
    finally:
        db.close()
        with _lock:
            _running.discard(job_id)


def read_sheets(db: Session, job: Job, user: User, p: Progress, reader, reread: bool) -> bool:
    """AI-read every current sheet. Returns False if the AI isn't available."""
    sheets = list(db.scalars(select(Sheet).where(Sheet.job_id == job.id, Sheet.is_duplicate.is_(False)).order_by(Sheet.file_id, Sheet.page_no)))
    if reader is None:
        p.attention("ai", "AI reading is switched off on the server, so sheets were sorted by keywords only and line "
                          "colours can't be named automatically. Ask your administrator to add the AI key.")
        return False
    for i, sheet in enumerate(sheets):
        if sheet.ai_reading and not reread:
            continue
        p.step(f"Reading sheet {i + 1} of {len(sheets)}: {label(sheet)}", i, len(sheets))
        try:
            read_and_apply(db, reader, sheet, user)
            db.commit()
        except AIUnavailable as e:
            db.rollback()
            p.attention("ai", f"The AI couldn't read this sheet: {e}", sheet)
            if "credentials" in str(e) or "reach" in str(e):
                return False  # no point trying the rest
        except Exception as e:  # one bad sheet shouldn't stop the whole set
            log.exception("AI read failed for sheet %s", sheet.id)
            db.rollback()
            p.attention("ai", f"The AI couldn't read this sheet ({e.__class__.__name__}).", sheet)
    return True


def _run_hydraulic(db: Session, job: Job, user: User, p: Progress, reader, reread: bool) -> None:
    ai_ok = read_sheets(db, job, user, p, reader, reread)
    sheets = list(db.scalars(select(Sheet).where(Sheet.job_id == job.id, Sheet.is_current.is_(True), Sheet.is_duplicate.is_(False),
                                                 Sheet.is_hydraulic.is_(True)).order_by(Sheet.file_id, Sheet.page_no)))
    plans = [s for s in sheets if s.classification in TAKEOFF_TYPES]
    if not plans:
        p.attention("sheets", "No hydraulic plans were found in this set. Check the sheet list: if a plan was sorted "
                              "as something else, change it and run the autopilot again.")
    for i, sheet in enumerate(plans):
        p.step(f"Taking off sheet {i + 1} of {len(plans)}: {label(sheet)}", i, len(plans))
        scaled, reason = auto_scale(db, sheet, user)
        if not scaled:
            p.attention("scale", f"Scale not confirmed: {reason}. Open the sheet and check one dimension (two clicks).", sheet)
        elif sheet.has_vectors:
            _suggest_runs(db, job, sheet, user, p, reader if ai_ok else None)
        else:
            p.attention("scanned", "This sheet is a scan (no line work in the PDF), so pipes can't be traced automatically. "
                                   "Trace them by hand on the sheet.", sheet)
        tags = (sheet.ai_reading or {}).get("count_tags") or []
        if tags:
            count_tagged_items(db, sheet, tags, user, excluded=set(job.excluded_services or []))
        db.commit()
    p.status["summary"] = summary(db, job.id)


def auto_scale(db: Session, sheet: Sheet, user: User) -> tuple[bool, str]:
    """Set the scale from the title block and confirm it against dimensions on the sheet."""
    if sheet.scale_verified:
        return True, ""
    if db.scalar(select(Run.id).where(Run.sheet_id == sheet.id).limit(1)):
        return False, "the sheet already has runs at an unverified scale"
    if not sheet.calibrated_scale:
        if not sheet.stated_m_per_pt:
            return False, "no scale is written on the sheet"
        before = snapshot(sheet)
        sheet.calibrated_scale = sheet.stated_m_per_pt
        sheet.calibration_method = "stated"
        sheet.calibration_data = {"method": "stated", "auto": True, "text": sheet.stated_scale}
        record(db, user.id, "sheet", sheet.id, "calibrate", before, snapshot(sheet))
    res = check_dimensions(sheet, sheet.calibrated_scale)
    if not res["ok"]:
        before = snapshot(sheet)
        sheet.verification_data = {"method": "auto_dimensions", "ok": False, "reason": res["reason"],
                                   "matches": res["matches"], "conflicts": res["conflicts"]}
        record(db, user.id, "sheet", sheet.id, "verify", before, snapshot(sheet))
        return False, res["reason"].lower()
    m = res["matches"][0]
    before = snapshot(sheet)
    sheet.scale_verified = True
    sheet.verification_data = {"p1": m["p1"], "p2": m["p2"], "known_m": m["known_m"], "measured_m": m["measured_m"],
                               "error_pct": m["error_pct"], "ok": True, "method": "auto_dimensions", "matches": res["matches"]}
    record(db, user.id, "sheet", sheet.id, "verify", before, snapshot(sheet))
    return True, ""


def _suggest_runs(db: Session, job: Job, sheet: Sheet, user: User, p: Progress, reader) -> None:
    styles = extract_segments(sheet)
    if not styles:
        return
    client = job.client or ""
    saved = {m.style_key: m for m in db.scalars(select(StyleMapping).where(StyleMapping.client == client))}
    assigns = [{"key": k, "service_id": m.service_id, "dn": m.dn, "material": m.material} for k, m in saved.items() if k in styles]
    if not assigns and reader is not None and hasattr(reader, "map_styles"):
        services = {s.code: s.id for s in db.scalars(select(Service).where(Service.active.is_(True)))}
        materials = [m.name for m in db.scalars(select(Material).where(Material.active.is_(True)))]
        summ = [{k: v for k, v in s.items() if k in ("key", "colour", "dashes", "width", "layer", "segments", "length_m")}
                for s in style_summary(styles, sheet.calibrated_scale)[:40]]
        try:
            from . import storage

            png = storage.local_path(sheet.image_key).read_bytes()
            found = reader.map_styles(png, (sheet.ai_reading or {}).get("legend", []), summ, list(services), materials)
        except AIUnavailable as e:
            p.attention("ai", f"The AI couldn't name the line colours: {e}", sheet)
            return
        assigns = [{"key": a.key, "service_id": services[a.service_code], "dn": a.dn, "material": a.material}
                   for a in found if a.confidence >= MIN_STYLE_CONFIDENCE and a.key in styles]
    if not assigns:
        p.attention("styles", "Couldn't tell which line colours are which pipes. Open the sheet's AI assist and pick them once; "
                              "the app remembers them for this client.", sheet)
        return
    # Accepted tender requirements: excluded services aren't taken off, and specified materials win.
    codes = {s.id: s.code for s in db.scalars(select(Service))}
    excluded = set(job.excluded_services or [])
    spec = job.spec_materials or {}
    assigns = [{**a, "material": spec.get(codes.get(a["service_id"]), a["material"])}
               for a in assigns if codes.get(a["service_id"]) not in excluded]
    if not assigns:
        return
    # Remember what the AI decided only once a person approves it (approve_all saves the mappings).
    create_suggested_runs(db, sheet, assigns, user, client=client, remember=False)


def summary(db: Session, job_id: int) -> dict:
    def n(model, status):
        return db.scalar(select(func.count(model.id)).where(model.job_id == job_id, model.status == status)) or 0

    metres = db.scalar(select(func.coalesce(func.sum(Run.length_m + Run.vertical_m), 0.0)).where(Run.job_id == job_id)) or 0.0
    sheets = db.scalar(select(func.count(Sheet.id)).where(Sheet.job_id == job_id, Sheet.is_duplicate.is_(False))) or 0
    hyd = db.scalar(select(func.count(Sheet.id)).where(Sheet.job_id == job_id, Sheet.is_duplicate.is_(False),
                                                      Sheet.is_current.is_(True), Sheet.is_hydraulic.is_(True))) or 0
    verified = db.scalar(select(func.count(Sheet.id)).where(Sheet.job_id == job_id, Sheet.scale_verified.is_(True))) or 0
    return {"sheets": sheets, "hydraulic_sheets": hyd, "scales_confirmed": verified,
            "runs_suggested": n(Run, "suggested"), "runs_confirmed": n(Run, "confirmed"),
            "counts_suggested": n(CountItem, "suggested"), "counts_confirmed": n(CountItem, "confirmed"),
            "metres": round(float(metres), 1)}


def recover_interrupted() -> None:
    """On startup: anything marked running was cut off by a restart."""
    with SessionLocal() as db:
        for job in db.scalars(select(Job).where(Job.autopilot.is_not(None))):
            if (job.autopilot or {}).get("state") in ("queued", "running"):
                job.autopilot = {**job.autopilot, "state": "interrupted", "step": "Stopped by a server restart. Run it again."}
        db.commit()
