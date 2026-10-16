"""Project tools: document storage, numbered project items (RFIs, defects...), site diary, forms, assets and maintenance."""
import mimetypes
import re
import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import config, ops, storage
from .models import Asset, Document, FormTemplate, Job, ProjectItem, Site

ITEM_KINDS = {
    "rfi": "RFI", "defect": "Defect", "site_instruction": "Site instruction", "incident": "Incident", "inspection": "Inspection",
    "observation": "Observation", "submittal": "Submittal", "note": "Job note",
}
JOB_FOLDERS = ["Drawings", "Contract", "Specifications", "Photos", "Certificates", "Variations", "Correspondence", "Safety", "General"]
COMPANY_FOLDERS = ["Policies", "SWMS", "Licences & insurance", "Templates", "Manuals", "General"]
ASSET_KINDS = ["Backflow prevention device", "Thermostatic mixing valve", "Hot water unit", "Grease trap", "Pump", "Rainwater tank",
               "Gas appliance", "Fire hose reel", "Water meter", "Other"]


def safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name)[:120] or "file"


async def store(db: Session, upload: UploadFile, *, job_id: int | None, folder: str, user_id: int | None, title: str = "",
                linked_type: str = "", linked_id: int | None = None, field_visible: bool = True) -> Document:
    """Save an upload. A file with the same name in the same folder becomes a new version of it."""
    name = upload.filename or "file"
    data = await upload.read(config.MAX_UPLOAD_BYTES + 1)
    if len(data) > config.MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"{name} is larger than {config.MAX_UPLOAD_BYTES // (1024 * 1024)} MB")
    if not data:
        raise HTTPException(422, f"{name} is empty")
    key = f"{'jobs/' + str(job_id) if job_id else 'company'}/files/{uuid.uuid4().hex}-{safe_name(name)}"
    storage.save_bytes(key, data)
    prev = None
    if not linked_type:
        prev = db.scalar(select(Document).where(Document.job_id == job_id if job_id else Document.job_id.is_(None), Document.folder == folder,
                                                Document.filename == name, Document.current.is_(True), Document.linked_type == ""))
    doc = Document(job_id=job_id, folder=folder, filename=name, path=key, size=len(data),
                   mime=upload.content_type or mimetypes.guess_type(name)[0] or "application/octet-stream", title=title or name,
                   version=(prev.version + 1) if prev else 1, supersedes_id=prev.id if prev else None, linked_type=linked_type,
                   linked_id=linked_id, field_visible=field_visible, uploaded_by=user_id)
    if prev:
        prev.current = False
    db.add(doc)
    db.flush()
    return doc


def doc_out(d: Document) -> dict:
    return {"id": d.id, "job_id": d.job_id, "folder": d.folder, "filename": d.filename, "title": d.title, "size": d.size, "mime": d.mime,
            "version": d.version, "current": d.current, "linked_type": d.linked_type, "linked_id": d.linked_id,
            "field_visible": d.field_visible, "uploaded_by": d.uploaded_by, "created_at": d.created_at.isoformat() if d.created_at else None,
            "is_image": d.mime.startswith("image/")}


def next_item_no(db: Session, job_id: int, kind: str) -> int:
    return (db.scalar(select(func.max(ProjectItem.number)).where(ProjectItem.job_id == job_id, ProjectItem.kind == kind)) or 0) + 1


def item_out(db: Session, p: ProjectItem, users: dict | None = None) -> dict:
    users = users or {}
    return {"id": p.id, "job_id": p.job_id, "kind": p.kind, "kind_label": ITEM_KINDS.get(p.kind, p.kind),
            "ref": f"{ITEM_KINDS.get(p.kind, p.kind)} {p.number}" if p.kind != "note" else "Note", "number": p.number, "title": p.title,
            "body": p.body, "status": p.status, "priority": p.priority, "location": p.location, "assignee_id": p.assignee_id,
            "assignee": users.get(p.assignee_id, "") or p.assignee_name, "assignee_name": p.assignee_name,
            "due_date": p.due_date.isoformat() if p.due_date else None, "response": p.response, "cost_impact": p.cost_impact,
            "variation_id": p.variation_id, "created_by": users.get(p.created_by, ""),
            "created_at": p.created_at.isoformat() if p.created_at else None,
            "closed_at": p.closed_at.isoformat() if p.closed_at else None,
            "overdue": bool(p.due_date and p.status != "closed" and p.due_date < date.today())}


# --- forms ---
FIELD_TYPES = ("check", "yesno", "text", "number", "choice", "signature", "photo", "heading")

DEFAULT_FORMS = [
    {"name": "Daily pre-start", "kind": "prestart", "fields": [
        {"key": "ppe", "label": "Everyone has the right PPE", "type": "yesno"},
        {"key": "hazards", "label": "Hazards on site today", "type": "text"},
        {"key": "permits", "label": "Permits needed (hot work, confined space, excavation)", "type": "choice",
         "options": ["None", "Hot work", "Confined space", "Excavation", "Working at heights"]},
        {"key": "services", "label": "Underground services located (DBYD)", "type": "yesno"},
        {"key": "sign", "label": "Supervisor signature", "type": "signature"}]},
    {"name": "SWMS sign-on", "kind": "swms", "fields": [
        {"key": "task", "label": "Task", "type": "text"},
        {"key": "read", "label": "I have read and understood the SWMS", "type": "check"},
        {"key": "controls", "label": "Controls are in place", "type": "yesno"},
        {"key": "sign", "label": "Worker signature", "type": "signature"}]},
    {"name": "Job completion", "kind": "completion", "required_on_completion": False, "fields": [
        {"key": "tested", "label": "Work tested and operating", "type": "yesno"},
        {"key": "clean", "label": "Site left clean", "type": "yesno"},
        {"key": "followup", "label": "Follow-up work needed", "type": "text"},
        {"key": "photo", "label": "Photo of finished work", "type": "photo"}]},
    {"name": "Backflow test report", "kind": "test", "fields": [
        {"key": "device", "label": "Device type", "type": "choice", "options": ["RPZD", "DCV", "Testable single check", "Other"]},
        {"key": "check1", "label": "Check valve 1 (kPa)", "type": "number"},
        {"key": "check2", "label": "Check valve 2 (kPa)", "type": "number"},
        {"key": "relief", "label": "Relief valve opened at (kPa)", "type": "number"},
        {"key": "result", "label": "Result", "type": "choice", "options": ["Pass", "Fail", "Repaired and passed"]},
        {"key": "sign", "label": "Tester signature", "type": "signature"}]},
    {"name": "TMV service", "kind": "test", "fields": [
        {"key": "temp", "label": "Outlet temperature (°C)", "type": "number"},
        {"key": "fail_safe", "label": "Fail-safe test passed", "type": "yesno"},
        {"key": "strainers", "label": "Strainers and checks cleaned", "type": "check"},
        {"key": "result", "label": "Result", "type": "choice", "options": ["Pass", "Fail"]}]},
]


def seed_forms(db: Session) -> None:
    if db.scalar(select(FormTemplate.id).limit(1)):
        return
    for f in DEFAULT_FORMS:
        db.add(FormTemplate(**f))
    db.flush()


def check_fields(fields: list[dict]) -> list[dict]:
    out, keys = [], set()
    for i, f in enumerate(fields):
        label = str(f.get("label", "")).strip()
        typ = f.get("type", "text")
        if not label or typ not in FIELD_TYPES:
            raise HTTPException(422, f"Question {i + 1}: needs a label and a type ({', '.join(FIELD_TYPES)})")
        key = str(f.get("key") or re.sub(r"[^a-z0-9]+", "_", label.lower())[:40] or f"q{i}")
        while key in keys:
            key += "_"
        keys.add(key)
        out.append({"key": key, "label": label, "type": typ, "options": [str(o) for o in f.get("options") or []],
                    "required": bool(f.get("required"))})
    return out


def check_answers(t: FormTemplate, answers: dict) -> dict:
    for f in t.fields:
        if f.get("required") and answers.get(f["key"]) in (None, "", False):
            raise HTTPException(422, f"Answer \"{f['label']}\"")
    return {f["key"]: answers.get(f["key"]) for f in t.fields if f["type"] != "heading"}


# --- assets and the maintenance planner ---
def advance(d: date, months: int) -> date:
    """Same day of the month, `months` later (the 31st becomes the last day of a shorter month)."""
    import calendar

    m = d.month - 1 + months
    y, m = d.year + m // 12, m % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def due_assets(db: Session, within_days: int = 30, today: date | None = None) -> list[Asset]:
    today = today or date.today()
    return list(db.scalars(select(Asset).where(Asset.active.is_(True), Asset.next_due.is_not(None),
                                               Asset.next_due <= today + timedelta(days=within_days)).order_by(Asset.next_due)))


def make_service_jobs(db: Session, assets: list[Asset], user_id: int | None) -> list[Job]:
    """One job per site for the assets due there (the way a tech does a round), unless one's already open for them."""
    from . import sales

    by_site: dict[int, list[Asset]] = {}
    for a in assets:
        by_site.setdefault(a.site_id, []).append(a)
    made = []
    for site_id, items in by_site.items():
        site = db.get(Site, site_id)
        open_jobs = db.scalars(select(Job).where(Job.site_id == site_id, Job.work_status.in_(("scheduled", "in_progress")),
                                                 Job.work_type == "Scheduled service"))
        if any(True for _ in open_jobs):
            continue
        cust_name = ""
        if site and site.customer_id:
            from .models import Customer

            c = db.get(Customer, site.customer_id)
            cust_name = c.name if c else ""
        lines = "\n".join(f"- {a.kind}{' – ' + a.location if a.location else ''}{' (s/n ' + a.serial + ')' if a.serial else ''}, due "
                          f"{a.next_due.strftime('%d/%m/%Y') if a.next_due else ''}" for a in items)
        price = sum(a.service_price or 0 for a in items) or None
        job = Job(name=f"Scheduled service – {site.name if site else ''}", sector="maintenance", kind="hydraulic", client=cust_name,
                  customer_id=site.customer_id if site else None, site_id=site_id, address=site.address if site else "",
                  work_type="Scheduled service", description=f"Service due:\n{lines}", billing="fixed" if price else "charge",
                  contract_value=price, tender_value=price, tender_result="won", decided_date=date.today(),
                  quote_sent_date=date.today(), created_by=user_id, lead_source="Maintenance planner",
                  due_date=min(a.next_due for a in items if a.next_due) if any(a.next_due for a in items) else None)
        sales.prepare_new(db, job)
        db.add(job)
        db.flush()
        ops.start_job(db, job, None)
        made.append(job)
    return made


def record_service(a: Asset, day: date) -> None:
    a.last_service = day
    a.next_due = advance(day, a.interval_months or 12)


def now() -> datetime:
    return datetime.now(timezone.utc)
