"""Documents, project items (RFIs, defects...), site diary, forms, assets and maintenance, plant register (office side)."""
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import plant as plant_rules
from .. import project, storage
from .. import timesheets as ts
from ..audit import record
from ..auth import current_user
from ..db import get_db
from ..finance import entry_hours
from ..models import (Asset, AssetService, DailyLog, Document, FormResponse, FormTemplate, Job, Plant, PlantCheck, PlantDefect,
                      ProjectItem, Site, TimeEntry, User)
from . import get_or_404

router = APIRouter(prefix="/api", tags=["project"])


# --- documents ---
@router.get("/files")
def list_docs(job_id: int | None = None, folder: str = "", all_versions: bool = False, db: Session = Depends(get_db),
              _: User = Depends(current_user)):
    stmt = select(Document).where(Document.job_id == job_id if job_id else Document.job_id.is_(None))
    if folder:
        stmt = stmt.where(Document.folder == folder)
    if not all_versions:
        stmt = stmt.where(Document.current.is_(True))
    return {"folders": project.JOB_FOLDERS if job_id else project.COMPANY_FOLDERS,
            "documents": [project.doc_out(d) for d in db.scalars(stmt.order_by(Document.folder, Document.filename, Document.version.desc()))]}


@router.get("/jobs/{job_id}/docs")
def job_docs(job_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    get_or_404(db, Job, job_id)
    return list_docs(job_id, "", False, db, user)


@router.post("/jobs/{job_id}/docs")
async def upload_job_doc(job_id: int, files: list[UploadFile] = File(...), folder: str = Form("General"), field_visible: bool = Form(True),
                         db: Session = Depends(get_db), user: User = Depends(current_user)):
    get_or_404(db, Job, job_id)
    out = []
    for f in files:
        d = await project.store(db, f, job_id=job_id, folder=folder, user_id=user.id, field_visible=field_visible)
        out.append(project.doc_out(d))
    record(db, user.id, "job", job_id, "documents", after={"folder": folder, "files": [o["filename"] for o in out]})
    db.commit()
    return out


@router.post("/files")
async def upload_company_doc(files: list[UploadFile] = File(...), folder: str = Form("General"), field_visible: bool = Form(True),
                             db: Session = Depends(get_db), user: User = Depends(current_user)):
    out = []
    for f in files:
        d = await project.store(db, f, job_id=None, folder=folder, user_id=user.id, field_visible=field_visible)
        out.append(project.doc_out(d))
    db.commit()
    return out


@router.get("/files/{document_id}")
def doc_file(document_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    d = get_or_404(db, Document, document_id)
    return Response(storage.read_bytes(d.path), media_type=d.mime or "application/octet-stream",
                    headers={"Content-Disposition": f'inline; filename="{project.safe_name(d.filename)}"'})


@router.get("/files/{document_id}/versions")
def versions(document_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    d = get_or_404(db, Document, document_id)
    stmt = select(Document).where(Document.filename == d.filename, Document.folder == d.folder,
                                  Document.job_id == d.job_id if d.job_id else Document.job_id.is_(None))
    return [project.doc_out(x) for x in db.scalars(stmt.order_by(Document.version.desc()))]


class DocPatch(BaseModel):
    folder: str | None = None
    title: str | None = None
    field_visible: bool | None = None


@router.patch("/files/{document_id}")
def edit_doc(document_id: int, body: DocPatch, db: Session = Depends(get_db), _: User = Depends(current_user)):
    d = get_or_404(db, Document, document_id)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(d, k, v)
    db.commit()
    return project.doc_out(d)


@router.delete("/files/{document_id}", status_code=204)
def delete_doc(document_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    d = get_or_404(db, Document, document_id)
    record(db, user.id, "document", d.id, "delete", before={"job_id": d.job_id, **project.doc_out(d)})
    if d.supersedes_id:
        prev = db.get(Document, d.supersedes_id)
        if prev is not None and d.current:
            prev.current = True
    for later in db.scalars(select(Document).where(Document.supersedes_id == d.id)):
        later.supersedes_id = d.supersedes_id
    storage.delete(d.path)
    db.delete(d)
    db.commit()


# --- project items ---
class ItemIn(BaseModel):
    kind: str
    title: str = Field(min_length=1)
    body: str = ""
    status: str = "open"
    priority: str = "normal"
    location: str = ""
    assignee_id: int | None = None
    assignee_name: str = ""
    due_date: date | None = None
    response: str = ""
    cost_impact: float | None = None


def _users(db: Session) -> dict:
    return {u.id: u.name or u.email for u in db.scalars(select(User))}


@router.get("/jobs/{job_id}/items")
def list_items(job_id: int, kind: str = "", db: Session = Depends(get_db), _: User = Depends(current_user)):
    get_or_404(db, Job, job_id)
    stmt = select(ProjectItem).where(ProjectItem.job_id == job_id)
    if kind:
        stmt = stmt.where(ProjectItem.kind == kind)
    users = _users(db)
    items = list(db.scalars(stmt.order_by(ProjectItem.kind, ProjectItem.number.desc())))
    photos = {}
    for d in db.scalars(select(Document).where(Document.job_id == job_id, Document.linked_type == "project_item")):
        photos.setdefault(d.linked_id, []).append(project.doc_out(d))
    return {"kinds": project.ITEM_KINDS, "items": [{**project.item_out(db, p, users), "photos": photos.get(p.id, [])} for p in items]}


@router.post("/jobs/{job_id}/items")
def add_item(job_id: int, body: ItemIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    get_or_404(db, Job, job_id)
    if body.kind not in project.ITEM_KINDS:
        raise HTTPException(422, "Unknown kind")
    p = ProjectItem(job_id=job_id, number=project.next_item_no(db, job_id, body.kind), created_by=user.id, **body.model_dump())
    if p.status == "closed":
        p.closed_at = datetime.now(timezone.utc)
    db.add(p)
    db.flush()
    if p.assignee_id and p.assignee_id != user.id:
        j = db.get(Job, job_id)
        plant_rules.notify(db, p.assignee_id, "item", f"{project.ITEM_KINDS[p.kind]} {p.number} on {j.job_no} {j.name}: {p.title}",
                           f"/work/{job_id}?tab=project")
    record(db, user.id, "project_item", p.id, "create", after={"job_id": job_id, **body.model_dump(mode="json")})
    db.commit()
    return project.item_out(db, p, _users(db))


@router.put("/items/{pitem_id}")
def update_item(pitem_id: int, body: ItemIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    p = get_or_404(db, ProjectItem, pitem_id)
    before = project.item_out(db, p)
    for k, v in body.model_dump().items():
        if k != "kind":
            setattr(p, k, v)
    p.closed_at = (p.closed_at or datetime.now(timezone.utc)) if p.status == "closed" else None
    record(db, user.id, "project_item", p.id, "update", before, project.item_out(db, p))
    db.commit()
    return project.item_out(db, p, _users(db))


@router.post("/items/{pitem_id}/variation")
def item_to_variation(pitem_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """An RFI answer or site instruction that changes the scope becomes a pending variation."""
    from .. import purchasing
    from ..models import Variation

    p = get_or_404(db, ProjectItem, pitem_id)
    if p.variation_id:
        raise HTTPException(409, "It already has a variation")
    v = Variation(job_id=p.job_id, number=purchasing.next_variation_no(db, p.job_id), title=f"{project.ITEM_KINDS[p.kind]} {p.number}: {p.title}"[:255],
                  description=p.body + ("\n\n" + p.response if p.response else ""), reason="site instruction" if p.kind == "site_instruction" else "design change",
                  sell=p.cost_impact or 0, created_by=user.id)
    db.add(v)
    db.flush()
    p.variation_id = v.id
    db.commit()
    return {"variation_id": v.id, "number": v.number}


# --- site diary ---
class LogIn(BaseModel):
    day: date
    weather: str = ""
    work_done: str = ""
    delays: str = ""
    deliveries: str = ""
    visitors: str = ""
    safety: str = ""
    lost_hours: float = Field(default=0, ge=0)


LOG_FIELDS = ["day", "weather", "work_done", "delays", "deliveries", "visitors", "safety", "lost_hours"]


def _crew(db: Session, job_id: int, d: date) -> list[dict]:
    lo, hi = ts.day_bounds(d)
    out: dict = {}
    for e in db.scalars(select(TimeEntry).where(TimeEntry.job_id == job_id, TimeEntry.start_at >= lo, TimeEntry.start_at < hi)):
        u = db.get(User, e.user_id)
        r = out.setdefault(e.user_id, {"name": (u.name or u.email) if u else "", "trade": u.trade if u else "", "hours": 0.0})
        r["hours"] = round(r["hours"] + entry_hours(e), 2)
    return list(out.values())


@router.get("/jobs/{job_id}/diary")
def diary(job_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    get_or_404(db, Job, job_id)
    users = _users(db)
    logs = db.scalars(select(DailyLog).where(DailyLog.job_id == job_id).order_by(DailyLog.day.desc()).limit(120))
    return [{"id": l.id, **{f: (getattr(l, f).isoformat() if isinstance(getattr(l, f), date) else getattr(l, f)) for f in LOG_FIELDS},
             "by": users.get(l.created_by, ""), "crew": _crew(db, job_id, l.day)} for l in logs]


@router.get("/jobs/{job_id}/diary/crew")
def diary_crew(job_id: int, day: date, db: Session = Depends(get_db), _: User = Depends(current_user)):
    """Who was on site that day, from the timesheets: fills the diary's labour section by itself."""
    get_or_404(db, Job, job_id)
    return _crew(db, job_id, day)


@router.post("/jobs/{job_id}/diary")
def add_log(job_id: int, body: LogIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    get_or_404(db, Job, job_id)
    l = db.scalar(select(DailyLog).where(DailyLog.job_id == job_id, DailyLog.day == body.day))
    if l is None:
        l = DailyLog(job_id=job_id, created_by=user.id, **body.model_dump())
        db.add(l)
    else:
        for k, v in body.model_dump().items():
            setattr(l, k, v)
    db.commit()
    return {"id": l.id}


# --- forms ---
class TemplateIn(BaseModel):
    name: str = Field(min_length=1)
    kind: str = "checklist"
    fields: list[dict]
    active: bool = True
    required_on_completion: bool = False


@router.get("/form-templates")
def templates(db: Session = Depends(get_db), _: User = Depends(current_user)):
    return [{"id": t.id, "name": t.name, "kind": t.kind, "fields": t.fields, "active": t.active,
             "required_on_completion": t.required_on_completion} for t in db.scalars(select(FormTemplate).order_by(FormTemplate.name))]


@router.post("/forms/templates")
def add_template(body: TemplateIn, db: Session = Depends(get_db), _: User = Depends(current_user)):
    t = FormTemplate(name=body.name, kind=body.kind, fields=project.check_fields(body.fields), active=body.active,
                     required_on_completion=body.required_on_completion)
    db.add(t)
    db.commit()
    return {"id": t.id}


@router.put("/forms/templates/{template_id}")
def edit_template(template_id: int, body: TemplateIn, db: Session = Depends(get_db), _: User = Depends(current_user)):
    t = get_or_404(db, FormTemplate, template_id)
    t.name, t.kind, t.fields, t.active, t.required_on_completion = (body.name, body.kind, project.check_fields(body.fields), body.active,
                                                                    body.required_on_completion)
    db.commit()
    return {"id": t.id}


@router.get("/jobs/{job_id}/forms")
def job_forms(job_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    get_or_404(db, Job, job_id)
    users, tpl = _users(db), {t.id: t for t in db.scalars(select(FormTemplate))}
    return [{"id": r.id, "template": tpl[r.template_id].name if r.template_id in tpl else "", "fields": tpl[r.template_id].fields if r.template_id in tpl else [],
             "answers": r.answers, "by": users.get(r.user_id, ""), "at": r.created_at.isoformat()}
            for r in db.scalars(select(FormResponse).where(FormResponse.job_id == job_id).order_by(FormResponse.created_at.desc()))]


# --- assets and maintenance ---
class AssetIn(BaseModel):
    site_id: int
    kind: str
    location: str = ""
    make: str = ""
    model: str = ""
    serial: str = ""
    installed: date | None = None
    interval_months: int = Field(default=12, ge=1, le=120)
    last_service: date | None = None
    next_due: date | None = None
    service_price: float | None = Field(default=None, ge=0)
    form_template_id: int | None = None
    notes: str = ""
    active: bool = True


ASSET_FIELDS = list(AssetIn.model_fields)


def _asset(db: Session, a: Asset) -> dict:
    site = db.get(Site, a.site_id)
    return {"id": a.id, **{f: (getattr(a, f).isoformat() if isinstance(getattr(a, f), date) else getattr(a, f)) for f in ASSET_FIELDS},
            "site": site.name if site else "", "address": site.address if site else "",
            "overdue": bool(a.next_due and a.next_due < date.today())}


@router.get("/assets")
def list_assets(site_id: int | None = None, due_within: int | None = None, db: Session = Depends(get_db), _: User = Depends(current_user)):
    stmt = select(Asset).order_by(Asset.next_due)
    if site_id:
        stmt = stmt.where(Asset.site_id == site_id)
    if due_within is not None:
        stmt = stmt.where(Asset.next_due <= date.today() + timedelta(days=due_within), Asset.active.is_(True))
    return {"kinds": project.ASSET_KINDS, "assets": [_asset(db, a) for a in db.scalars(stmt.limit(1000))]}


@router.post("/assets")
def add_asset(body: AssetIn, db: Session = Depends(get_db), _: User = Depends(current_user)):
    get_or_404(db, Site, body.site_id)
    a = Asset(**body.model_dump())
    if a.next_due is None:
        a.next_due = project.advance(a.last_service, a.interval_months) if a.last_service else date.today()
    db.add(a)
    db.commit()
    return _asset(db, a)


@router.put("/assets/{asset_id}")
def edit_asset(asset_id: int, body: AssetIn, db: Session = Depends(get_db), _: User = Depends(current_user)):
    a = get_or_404(db, Asset, asset_id)
    for k, v in body.model_dump().items():
        setattr(a, k, v)
    db.commit()
    return _asset(db, a)


@router.get("/assets/{asset_id}/history")
def asset_history(asset_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    get_or_404(db, Asset, asset_id)
    users = _users(db)
    return [{"id": s.id, "day": s.day.isoformat(), "result": s.result, "readings": s.readings, "notes": s.notes, "job_id": s.job_id,
             "by": users.get(s.user_id, "")} for s in db.scalars(select(AssetService).where(AssetService.asset_id == asset_id)
                                                                  .order_by(AssetService.day.desc()))]


class Generate(BaseModel):
    within_days: int = Field(default=30, ge=0, le=365)
    asset_ids: list[int] = []


@router.post("/maintenance/generate")
def generate(body: Generate, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Make service jobs for what's due: one job per site."""
    assets = [db.get(Asset, i) for i in body.asset_ids] if body.asset_ids else project.due_assets(db, body.within_days)
    jobs = project.make_service_jobs(db, [a for a in assets if a], user.id)
    db.commit()
    return {"jobs": [{"id": j.id, "job_no": j.job_no, "name": j.name} for j in jobs]}


# --- plant and vehicles ---
class PlantIn(BaseModel):
    kind: str = "plant"
    name: str = Field(min_length=1)
    fleet_no: str = ""
    category: str = ""
    rego: str = ""
    make: str = ""
    model: str = ""
    year: int | None = None
    serial: str = ""
    assigned_user_id: int | None = None
    hours: float | None = None
    odometer: float | None = None
    service_every_hours: float | None = None
    service_every_km: float | None = None
    last_service_hours: float | None = None
    last_service_km: float | None = None
    next_service_date: date | None = None
    rego_expiry: date | None = None
    insurance_expiry: date | None = None
    status: str = "in_service"
    hire_rate: float = Field(default=0, ge=0)
    checklist_id: int | None = None
    photos_required: bool = True
    notes: str = ""


PLANT_FIELDS = list(PlantIn.model_fields)


def _plant(db: Session, p: Plant, users: dict | None = None) -> dict:
    users = users if users is not None else _users(db)
    today = ts.local_day(ts.now())
    last = db.scalar(select(PlantCheck).where(PlantCheck.plant_id == p.id, PlantCheck.kind.in_(("prestart", "weekly")))
                     .order_by(PlantCheck.at.desc()))
    return {"id": p.id, **{f: (getattr(p, f).isoformat() if isinstance(getattr(p, f), date) else getattr(p, f)) for f in PLANT_FIELDS},
            "assigned_to": users.get(p.assigned_user_id, ""), "due": plant_rules.service_due(p, today),
            "open_defects": len(list(db.scalars(select(PlantDefect.id).where(PlantDefect.plant_id == p.id, PlantDefect.status.in_(("open", "in_repair")))))),
            "last_check": {"kind": last.kind, "at": last.at.isoformat(), "passed": last.passed, "by": users.get(last.user_id, "")} if last else None,
            "weekly_done": bool(plant_rules.last_check(db, p.id, "weekly", ts.day_bounds(ts.week_start(today))[0])) if p.kind == "vehicle" else None,
            "wash_done": bool(plant_rules.last_check(db, p.id, "wash", ts.day_bounds(today.replace(day=1))[0])) if p.kind == "vehicle" else None}


@router.get("/plant")
def plant_register(db: Session = Depends(get_db), _: User = Depends(current_user)):
    users = _users(db)
    return {"plant": [_plant(db, p, users) for p in db.scalars(select(Plant).order_by(Plant.kind, Plant.name))],
            "settings": plant_rules.settings(db)}


@router.post("/plant")
def add_plant(body: PlantIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    p = Plant(**body.model_dump())
    db.add(p)
    db.flush()
    record(db, user.id, "plant", p.id, "create", after=body.model_dump(mode="json"))
    db.commit()
    return _plant(db, p)


@router.put("/plant/{plant_id}")
def edit_plant(plant_id: int, body: PlantIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    p = get_or_404(db, Plant, plant_id)
    for k, v in body.model_dump().items():
        setattr(p, k, v)
    record(db, user.id, "plant", p.id, "update", after=body.model_dump(mode="json"))
    db.commit()
    return _plant(db, p)


@router.get("/plant/{plant_id}")
def plant_detail(plant_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    p = get_or_404(db, Plant, plant_id)
    users = _users(db)
    checks = db.scalars(select(PlantCheck).where(PlantCheck.plant_id == p.id).order_by(PlantCheck.at.desc()).limit(200))
    defects = db.scalars(select(PlantDefect).where(PlantDefect.plant_id == p.id).order_by(PlantDefect.reported_at.desc()))
    hours = sum(entry_hours(e) for e in db.scalars(select(TimeEntry).where(TimeEntry.plant_id == p.id)))
    return {**_plant(db, p, users), "operated_hours": round(hours, 1),
            "checks": [{"id": c.id, "kind": c.kind, "at": c.at.isoformat(), "by": users.get(c.user_id, ""), "passed": c.passed,
                        "hours": c.hours, "odometer": c.odometer, "fuel_pct": c.fuel_pct, "photo_ids": c.photo_ids or {}, "answers": c.answers,
                        "notes": c.notes} for c in checks],
            "defects": [{"id": d.id, "kind": d.kind, "severity": d.severity, "description": d.description, "status": d.status,
                         "reported_at": d.reported_at.isoformat(), "by": users.get(d.reported_by, ""), "photo_ids": d.photo_ids or [],
                         "repair_notes": d.repair_notes, "repair_cost": d.repair_cost,
                         "fixed_at": d.fixed_at.isoformat() if d.fixed_at else None} for d in defects]}


class DefectFix(BaseModel):
    status: str
    repair_notes: str = ""
    repair_cost: float | None = Field(default=None, ge=0)


@router.put("/plant-defects/{defect_id}")
def fix_defect(defect_id: int, body: DefectFix, db: Session = Depends(get_db), user: User = Depends(current_user)):
    d = get_or_404(db, PlantDefect, defect_id)
    if body.status not in ("open", "in_repair", "fixed", "no_action"):
        raise HTTPException(422, "Unknown status")
    d.status, d.repair_notes, d.repair_cost = body.status, body.repair_notes, body.repair_cost
    p = db.get(Plant, d.plant_id)
    if body.status in ("fixed", "no_action"):
        d.fixed_at, d.fixed_by = datetime.now(timezone.utc), user.id
        still = db.scalar(select(PlantDefect.id).where(PlantDefect.plant_id == p.id, PlantDefect.id != d.id, PlantDefect.severity == "critical",
                                                       PlantDefect.status.in_(("open", "in_repair"))))
        if p.status in ("out_of_service", "in_repair") and not still:
            p.status = "in_service"
    elif body.status == "in_repair":
        p.status = "in_repair"
    db.commit()
    return {"id": d.id, "status": d.status, "plant_status": p.status}


@router.put("/plant-settings")
def plant_settings(body: dict, db: Session = Depends(get_db), user: User = Depends(current_user)):
    from ..models import AppSetting

    if user.role != "admin":
        raise HTTPException(403, "Admin only")
    clean = {k: v for k, v in body.items() if k in plant_rules.DEFAULTS}
    s = db.get(AppSetting, "plant") or AppSetting(key="plant", value={})
    s.value = {**(s.value or {}), **clean}
    db.merge(s)
    db.commit()
    return plant_rules.settings(db)


@router.get("/plant-compliance")
def compliance(db: Session = Depends(get_db), _: User = Depends(current_user)):
    """This week: who has done their vehicle pre-start and this month's wash, and which machines were checked today."""
    users = _users(db)
    today = ts.local_day(ts.now())
    rows = []
    for p in db.scalars(select(Plant).where(Plant.status != "sold").order_by(Plant.kind, Plant.name)):
        rows.append({"id": p.id, "name": p.name, "kind": p.kind, "rego": p.rego, "assigned_to": users.get(p.assigned_user_id, ""),
                     "status": p.status, "prestart_today": bool(plant_rules.last_check(db, p.id, "prestart", ts.day_bounds(today)[0])),
                     "weekly_done": bool(plant_rules.last_check(db, p.id, "weekly", ts.day_bounds(ts.week_start(today))[0])),
                     "wash_done": bool(plant_rules.last_check(db, p.id, "wash", ts.day_bounds(today.replace(day=1))[0])),
                     "due": plant_rules.service_due(p, today)})
    return rows
