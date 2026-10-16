"""The phone app for people on the tools: today, clock in/out, jobs, photos, materials, POs, forms, pre-starts.

Everything here works for every signed-in user (office staff clock in too); people with role "field" can
reach nothing else. Field users only see live jobs and the documents marked for the field.
"""
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .. import ops, plant, project, purchasing, storage
from .. import timesheets as ts
from ..access import can_see_job
from ..audit import record
from ..auth import current_user
from ..db import get_db
from ..finance import entry_hours
from ..models import (Customer, Document, DrawingFile, FormResponse, FormTemplate, Job, JobCost, Notification, Plant, PlantCheck, PlantDefect,
                      ProjectItem, PurchaseOrder, ScheduleEntry, Site, Supplier, TenderDocument, TimeEntry, TimeOff, User)
from . import get_or_404

router = APIRouter(prefix="/api/field", tags=["field"])


def _job(db: Session, job_id: int, user: User) -> Job:
    job = get_or_404(db, Job, job_id)
    if not job.work_status or not can_see_job(user, job):
        raise HTTPException(404, "Job not found")
    return job


def _brief(db: Session, j: Job) -> dict:
    site = db.get(Site, j.site_id) if j.site_id else None
    return {"id": j.id, "job_no": j.job_no, "name": j.name, "customer": j.client, "address": site.address if site and site.address else j.address,
            "priority": j.priority, "work_status": j.work_status, "work_type": j.work_type, "kind": j.kind, "sector": j.sector}


@router.get("/today")
def today(db: Session = Depends(get_db), user: User = Depends(current_user)):
    now = ts.now()
    d = ts.local_day(now)
    cur = ts.open_entry(db, user.id)
    sched = [ts.schedule_out(db, s) for s in db.scalars(select(ScheduleEntry).where(ScheduleEntry.user_id == user.id, ScheduleEntry.day == d,
                                                                                    ScheduleEntry.published.is_(True)).order_by(ScheduleEntry.start))]
    week = ts.week_entries(db, ts.week_start(d), user.id)
    day_hours = sum(entry_hours(e) for e in week if ts.local_day(e.start_at) == d)
    unread = db.scalars(select(Notification).where(Notification.user_id == user.id, Notification.read_at.is_(None))
                        .order_by(Notification.created_at.desc()).limit(20))
    todo = plant.todo(db, user, d)
    return {"user": {"id": user.id, "name": user.name or user.email, "trade": user.trade, "role": user.role},
            "now": now.isoformat(), "day": d.isoformat(),
            "current": ts.entry_out(db, cur) if cur else None,
            "schedule": sched, "today_hours": round(day_hours, 2), "week_hours": round(sum(entry_hours(e) for e in week), 2),
            "todo": todo, "end_needs": plant.end_requirements(db, user, d) if cur else [],
            "notifications": [{"id": n.id, "kind": n.kind, "text": n.text, "link": n.link, "at": n.created_at.isoformat()} for n in unread],
            "vehicles": [{"id": v.id, "name": v.name, "rego": v.rego} for v in plant.my_vehicles(db, user)],
            "is_supervisor": user.role == "admin" or user.trade in ("supervisor", "project manager", "manager")}


@router.get("/jobs")
def jobs(q: str = "", finished: bool = False, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Jobs to clock into: today's schedule first, then the ones recently worked on, then everything live.
    Finished jobs (invoiced, closed) come too when asked for or searched for, so photos can be added later."""
    d = ts.local_day(ts.now())
    mine = [s.job_id for s in db.scalars(select(ScheduleEntry).where(ScheduleEntry.user_id == user.id, ScheduleEntry.day == d)) if s.job_id]
    recent = [e.job_id for e in db.scalars(select(TimeEntry).where(TimeEntry.user_id == user.id, TimeEntry.job_id.is_not(None))
                                           .order_by(TimeEntry.start_at.desc()).limit(30))]
    statuses = ("scheduled", "in_progress", "on_hold", "complete") + (("invoiced", "closed") if finished or q else ())
    stmt = select(Job).where(Job.work_status.in_(statuses))
    if q:
        stmt = stmt.where(or_(Job.name.ilike(f"%{q}%"), Job.job_no.ilike(f"%{q}%"), Job.client.ilike(f"%{q}%"), Job.address.ilike(f"%{q}%")))
    live = {j.id: j for j in db.scalars(stmt.order_by(Job.id.desc()).limit(200)) if can_see_job(user, j)}
    order = list(dict.fromkeys([*mine, *recent, *live.keys()]))
    return [{**_brief(db, live[i]), "today": i in mine} for i in order if i in live]


@router.get("/jobs/{job_id}")
def job_detail(job_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    j = _job(db, job_id, user)
    site = db.get(Site, j.site_id) if j.site_id else None
    cust = db.get(Customer, j.customer_id) if j.customer_id else None
    docs = db.scalars(select(Document).where(Document.job_id == j.id, Document.current.is_(True), Document.field_visible.is_(True))
                      .order_by(Document.folder, Document.filename))
    notes = db.scalars(select(ProjectItem).where(ProjectItem.job_id == j.id, ProjectItem.kind.in_(("note", "defect", "site_instruction")))
                       .order_by(ProjectItem.created_at.desc()).limit(50))
    users = {u.id: u.name or u.email for u in db.scalars(select(User))}
    mats = db.scalars(select(JobCost).where(JobCost.job_id == j.id, JobCost.source.in_(("field", "stock"))).order_by(JobCost.created_at.desc()))
    pos = db.scalars(select(PurchaseOrder).where(PurchaseOrder.job_id == j.id).order_by(PurchaseOrder.id.desc()))
    return {**_brief(db, j), "description": j.description, "order_no": j.order_no, "contact": j.contact,
            "customer_phone": cust.phone if cust else "", "access_notes": site.access_notes if site else "",
            "site_contact": site.contact if site else "", "lat": site.lat if site else None, "lng": site.lng if site else None,
            "documents": [project.doc_out(d) for d in docs if not d.linked_type or d.folder == "Photos"],
            "notes": [project.item_out(db, p, users) for p in notes],
            "materials": [{"id": m.id, "description": m.description, "qty": m.qty, "by": users.get(m.user_id, ""),
                           "day": m.day.isoformat()} for m in mats],
            "pos": [{"po_no": p.po_no, "supplier": p.supplier_name, "status": p.status, "mine": p.created_by == user.id} for p in pos],
            "plans": [{"id": f.id, "filename": f.filename, "pages": f.page_count} for f in db.scalars(select(DrawingFile).where(DrawingFile.job_id == j.id)
                                                                                                     .order_by(DrawingFile.uploaded_at))],
            "specs": [{"id": t.id, "filename": t.filename, "title": t.title or t.filename, "doc_type": t.doc_type}
                      for t in db.scalars(select(TenderDocument).where(TenderDocument.job_id == j.id).order_by(TenderDocument.created_at))],
            "forms": [{"id": t.id, "name": t.name, "kind": t.kind} for t in db.scalars(select(FormTemplate).where(FormTemplate.active.is_(True)))
                      if t.kind not in ("test",) or j.sector == "maintenance"],
            "completed": j.work_status in ("complete", "invoiced", "closed"), "signed_by_name": j.signed_by_name}


# --- clocking ---
class ClockIn(BaseModel):
    job_id: int | None = None
    task: str = ""
    plant_id: int | None = None
    lat: float | None = None
    lng: float | None = None
    at: datetime | None = None  # when it happened on the phone (offline punches catch up later)
    client_ref: str = ""
    notes: str = ""


def _when(at: datetime | None) -> datetime:
    now = ts.now()
    at = ts.aware(at)
    if at is None or at > now + timedelta(minutes=2) or at < now - timedelta(hours=24):
        return now  # don't trust a phone clock that's way off
    return at


@router.post("/clock-in")
def clock_in(body: ClockIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if body.job_id:
        _job(db, body.job_id, user)
    cur = ts.open_entry(db, user.id)
    switching = cur is not None
    if not switching or (body.plant_id and body.plant_id != cur.plant_id):
        problems = plant.start_requirements(db, user, [body.plant_id] if body.plant_id else [])
        if problems and not (switching and not body.plant_id):
            raise HTTPException(409, {"message": problems[0], "problems": problems})
    e = ts.clock_in(db, user, body.job_id, body.task, body.lat, body.lng, _when(body.at), body.client_ref, notes=body.notes)
    e.plant_id = body.plant_id
    db.commit()
    return ts.entry_out(db, e)


class ClockOut(BaseModel):
    lat: float | None = None
    lng: float | None = None
    notes: str = ""
    at: datetime | None = None


@router.post("/clock-out")
def clock_out(body: ClockOut, db: Session = Depends(get_db), user: User = Depends(current_user)):
    needs = plant.end_requirements(db, user)
    if needs:
        raise HTTPException(409, {"message": needs[0], "problems": needs})
    e = ts.clock_out(db, user, body.lat, body.lng, body.notes, _when(body.at))
    if e is None:
        raise HTTPException(409, "You're not clocked in")
    db.commit()
    return ts.entry_out(db, e)


@router.post("/break/start")
def break_start(db: Session = Depends(get_db), user: User = Depends(current_user)):
    e = ts.start_break(db, user)
    if e is None:
        raise HTTPException(409, "You're not clocked in")
    db.commit()
    return ts.entry_out(db, e)


@router.post("/break/end")
def break_end(db: Session = Depends(get_db), user: User = Depends(current_user)):
    e = ts.end_break(db, user)
    if e is None:
        raise HTTPException(409, "You're not clocked in")
    db.commit()
    return ts.entry_out(db, e)


class CrewIn(BaseModel):
    user_ids: list[int]
    job_id: int | None = None
    task: str = ""
    lat: float | None = None
    lng: float | None = None
    out: bool = False


@router.post("/crew")
def crew(body: CrewIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """A supervisor clocks their crew on or off together."""
    if not (user.role == "admin" or user.trade in ("supervisor", "project manager", "manager")):
        raise HTTPException(403, "Only supervisors can clock a crew in")
    if body.job_id:
        _job(db, body.job_id, user)
    done = []
    for uid in body.user_ids:
        u = db.get(User, uid)
        if u is None or not u.active:
            continue
        if body.out:
            if ts.clock_out(db, u, body.lat, body.lng, f"Clocked off by {user.name or user.email}"):
                done.append(u.name or u.email)
        else:
            ts.clock_in(db, u, body.job_id, body.task, body.lat, body.lng, source="crew", notes=f"Clocked on by {user.name or user.email}")
            done.append(u.name or u.email)
    db.commit()
    return {"done": done}


@router.get("/crew")
def crew_list(db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows = []
    for u in db.scalars(select(User).where(User.active.is_(True)).order_by(User.name)):
        if u.role != "field" and u.trade not in ("plumber", "apprentice", "labourer"):
            continue
        cur = ts.open_entry(db, u.id)
        rows.append({"id": u.id, "name": u.name or u.email, "trade": u.trade, "on": bool(cur),
                     "job": (db.get(Job, cur.job_id).name if cur and cur.job_id and db.get(Job, cur.job_id) else "") if cur else ""})
    return rows


# --- my timesheet ---
@router.get("/timesheet")
def my_week(start: date | None = None, db: Session = Depends(get_db), user: User = Depends(current_user)):
    start = ts.week_start(start or ts.local_day(ts.now()))
    es = ts.week_entries(db, start, user.id)
    days = {}
    for e in es:
        k = ts.local_day(e.start_at).isoformat()
        days[k] = round(days.get(k, 0) + entry_hours(e), 2)
    return {"start": start.isoformat(), "entries": [ts.entry_out(db, e) for e in es], "days": days,
            "total": round(sum(days.values()), 2), **ts.overtime(db, days),
            "can_submit": any(e.status == "open" and e.end_at for e in es)}


class Week(BaseModel):
    start: date


@router.post("/timesheet/submit")
def submit(body: Week, db: Session = Depends(get_db), user: User = Depends(current_user)):
    n = 0
    for e in ts.week_entries(db, ts.week_start(body.start), user.id):
        if e.status == "open" and e.end_at is not None:
            e.status = "submitted"
            n += 1
    db.commit()
    return {"submitted": n}


class ManualIn(BaseModel):
    job_id: int | None = None
    task: str = ""
    day: date
    start: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    end: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    break_minutes: float = Field(default=0, ge=0, le=600)
    notes: str = Field(min_length=1)  # why it wasn't clocked


@router.post("/timesheet/manual")
def manual(body: ManualIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Forgot to clock in: add the time by hand. It's flagged for the office to check."""
    if body.day > ts.local_day(ts.now()) or body.day < ts.local_day(ts.now()) - timedelta(days=14):
        raise HTTPException(422, "Only the last two weeks can be added by hand")
    h1, m1 = map(int, body.start.split(":"))
    h2, m2 = map(int, body.end.split(":"))
    start = datetime(body.day.year, body.day.month, body.day.day, h1, m1, tzinfo=ts.TZ)
    end = datetime(body.day.year, body.day.month, body.day.day, h2, m2, tzinfo=ts.TZ)
    if end <= start:
        raise HTTPException(422, "The finish time must be after the start")
    if body.job_id:
        _job(db, body.job_id, user)
    e = TimeEntry(user_id=user.id, job_id=body.job_id, task=body.task, start_at=start, end_at=end, break_minutes=body.break_minutes,
                  notes=body.notes, source="manual", status="open", edited_reason="Added on the phone: " + body.notes)
    db.add(e)
    db.commit()
    return ts.entry_out(db, e)


class LeaveIn(BaseModel):
    kind: str = "annual"
    start_date: date
    end_date: date
    hours: float | None = Field(default=None, ge=0)
    notes: str = ""


@router.post("/time-off")
def ask_leave(body: LeaveIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if body.end_date < body.start_date:
        raise HTTPException(422, "The last day is before the first")
    t = TimeOff(user_id=user.id, **body.model_dump())
    db.add(t)
    for u in db.scalars(select(User).where(User.role == "admin", User.active.is_(True))):
        plant.notify(db, u.id, "leave", f"{user.name or user.email} asked for {body.kind} leave {body.start_date:%d/%m}–{body.end_date:%d/%m}",
                     "/timesheets?tab=leave")
    db.commit()
    return {"id": t.id, "status": t.status}


@router.get("/time-off")
def my_leave(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return [{"id": t.id, "kind": t.kind, "start_date": t.start_date.isoformat(), "end_date": t.end_date.isoformat(), "status": t.status,
             "notes": t.notes} for t in db.scalars(select(TimeOff).where(TimeOff.user_id == user.id).order_by(TimeOff.start_date.desc()))]


@router.get("/schedule")
def my_schedule(start: date | None = None, db: Session = Depends(get_db), user: User = Depends(current_user)):
    start = ts.week_start(start or ts.local_day(ts.now()))
    rows = db.scalars(select(ScheduleEntry).where(ScheduleEntry.user_id == user.id, ScheduleEntry.day >= start,
                                                  ScheduleEntry.day < start + timedelta(days=14), ScheduleEntry.published.is_(True))
                      .order_by(ScheduleEntry.day, ScheduleEntry.start))
    return {"start": start.isoformat(), "entries": [ts.schedule_out(db, s) for s in rows]}


# --- on a job ---
@router.post("/upload")
async def upload(file: UploadFile = File(...), job_id: int | None = Form(None), folder: str = Form("Photos"), title: str = Form(""),
                 db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Photos and files from the phone. Returns the document id to attach to a check, defect or note."""
    if job_id:
        _job(db, job_id, user)
    d = await project.store(db, file, job_id=job_id, folder=folder if job_id else "Plant photos", user_id=user.id, title=title,
                            linked_type="field")
    db.commit()
    return project.doc_out(d)


@router.get("/documents/{document_id}")
def download(document_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    d = get_or_404(db, Document, document_id)
    if d.job_id:
        _job(db, d.job_id, user)
    if user.role == "field" and not d.field_visible and d.uploaded_by != user.id:
        raise HTTPException(404, "Document not found")
    return Response(storage.read_bytes(d.path), media_type=d.mime or "application/octet-stream",
                    headers={"Content-Disposition": f'inline; filename="{project.safe_name(d.filename)}"'})


@router.get("/jobs/{job_id}/plans/{file_id}")
def plan_file(job_id: int, file_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    _job(db, job_id, user)
    f = get_or_404(db, DrawingFile, file_id)
    if f.job_id != job_id:
        raise HTTPException(404, "Plan not found")
    return Response(storage.read_bytes(f.storage_key), media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{project.safe_name(f.filename)}"'})


@router.get("/jobs/{job_id}/specs/{spec_id}")
def spec_file(job_id: int, spec_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    import mimetypes

    _job(db, job_id, user)
    t = get_or_404(db, TenderDocument, spec_id)
    if t.job_id != job_id:
        raise HTTPException(404, "Document not found")
    return Response(storage.read_bytes(t.storage_key), media_type=mimetypes.guess_type(t.filename)[0] or "application/octet-stream",
                    headers={"Content-Disposition": f'inline; filename="{project.safe_name(t.filename)}"'})


class NoteIn(BaseModel):
    text: str = Field(min_length=1)
    kind: str = "note"  # note | defect
    photo_ids: list[int] = []


@router.post("/jobs/{job_id}/notes")
def add_note(job_id: int, body: NoteIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    j = _job(db, job_id, user)
    kind = body.kind if body.kind in ("note", "defect") else "note"
    p = ProjectItem(job_id=j.id, kind=kind, number=project.next_item_no(db, j.id, kind), title=body.text.split("\n")[0][:200],
                    body=body.text, status="closed" if kind == "note" else "open", created_by=user.id)
    db.add(p)
    db.flush()
    for pid in body.photo_ids:
        d = db.get(Document, pid)
        if d and d.job_id == j.id:
            d.linked_type, d.linked_id = "project_item", p.id
    db.commit()
    return project.item_out(db, p)


class MaterialIn(BaseModel):
    description: str = ""
    qty: float = Field(default=1, gt=0)
    unit: str = "ea"
    code: str = ""  # a product from the price files / price book
    supplier_id: int | None = None


def add_material(db: Session, j: Job, body: MaterialIn, user: User, unit_cost: float | None = None, markup_pct: float | None = None) -> JobCost:
    """Materials used from stock: a product code is costed at the price-file rate and sold at cost plus the margin.
    Anything typed in without a code is recorded for the office to price."""
    from .. import stock

    p = stock.price(db, body.code, body.supplier_id) if body.code else None
    if body.code and p is None and unit_cost is None:
        raise HTTPException(422, "That product isn't in the price files any more. Type it in instead.")
    if not body.code and not body.description.strip():
        raise HTTPException(422, "What did you use?")
    cost = unit_cost if unit_cost is not None else (p["cost"] if p else 0.0)
    m = markup_pct if markup_pct is not None else (p["markup_pct"] if p else None)
    desc = body.description.strip() or (p["description"] if p else "")
    unit = body.unit if body.unit != "ea" or not p else (p["unit"] or "ea")
    c = JobCost(job_id=j.id, day=ts.local_day(ts.now()), category="materials", description=f"{body.qty:g} {unit} {desc}"[:500], qty=body.qty,
                unit_cost=cost, amount=round(body.qty * cost, 2), source="stock" if body.code else "field", user_id=user.id, ref=body.code,
                markup_pct=m, sell_unit=round(cost * (1 + m / 100), 2) if m is not None and (p or unit_cost is not None) else None)
    db.add(c)
    db.flush()
    return c


@router.get("/products")
def products(q: str = "", db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Search the stock list (supplier price files and the price book). People on the tools don't see prices."""
    from .. import stock

    rows = stock.search(db, q) if len(q.strip()) >= 2 else []
    if user.role == "field":
        rows = [{k: v for k, v in r.items() if k not in ("cost", "sell", "markup_pct", "supplier", "supplier_id")} for r in rows]
    return rows


@router.post("/jobs/{job_id}/materials")
def use_material(job_id: int, body: MaterialIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    j = _job(db, job_id, user)
    c = add_material(db, j, body, user)
    db.commit()
    return {"id": c.id, "description": c.description, "priced": c.sell_unit is not None}


class FieldPoIn(BaseModel):
    supplier_id: int | None = None
    supplier_name: str = ""
    lines: list[dict] = []
    notes: str = ""
    delivery: str = "Pick up"


@router.get("/suppliers")
def suppliers(db: Session = Depends(get_db), _: User = Depends(current_user)):
    return [{"id": s.id, "name": s.name} for s in db.scalars(select(Supplier).where(Supplier.active.is_(True)).order_by(Supplier.name))]


@router.post("/jobs/{job_id}/po")
def field_po(job_id: int, body: FieldPoIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Get a PO number at the trade counter. It's marked sent; the office matches the bill to it."""
    j = _job(db, job_id, user)
    sup = db.get(Supplier, body.supplier_id) if body.supplier_id else None
    if sup is None and not body.supplier_name.strip():
        raise HTTPException(422, "Which supplier?")
    po = purchasing.make_po(db, job=j, supplier=sup, supplier_name=body.supplier_name.strip(), lines=body.lines, user_id=user.id,
                            status="sent", notes=body.notes, delivery=body.delivery)
    record(db, user.id, "purchase_order", po.id, "create", after={"job_id": j.id, "po_no": po.po_no, "from": "field"})
    db.commit()
    return purchasing.po_out(db, po)


@router.get("/forms/{template_id}")
def form(template_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    t = get_or_404(db, FormTemplate, template_id)
    return {"id": t.id, "name": t.name, "kind": t.kind, "fields": t.fields}


class FormIn(BaseModel):
    answers: dict
    asset_id: int | None = None


@router.post("/jobs/{job_id}/forms/{template_id}")
def fill_form(job_id: int, template_id: int, body: FormIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    j = _job(db, job_id, user)
    t = get_or_404(db, FormTemplate, template_id)
    r = FormResponse(template_id=t.id, job_id=j.id, asset_id=body.asset_id, user_id=user.id, answers=project.check_answers(t, body.answers))
    db.add(r)
    if body.asset_id:
        from ..models import Asset, AssetService

        a = db.get(Asset, body.asset_id)
        if a is not None:
            result = str(body.answers.get("result") or "serviced").lower()
            db.add(AssetService(asset_id=a.id, job_id=j.id, day=ts.local_day(ts.now()), result=result if result in ("pass", "fail") else "serviced",
                                readings=r.answers, user_id=user.id))
            project.record_service(a, ts.local_day(ts.now()))
    db.commit()
    return {"id": r.id}


class CompleteIn(BaseModel):
    notes: str = ""
    signature: str = ""  # data URL of the customer's signature
    signed_by_name: str = ""
    follow_up: str = ""


@router.post("/jobs/{job_id}/complete")
def complete(job_id: int, body: CompleteIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    j = _job(db, job_id, user)
    if body.signature and not body.signature.startswith("data:image/"):
        raise HTTPException(422, "The signature didn't come through. Try again.")
    ops.set_status(j, "complete")
    j.signature, j.signed_by_name = body.signature[:400_000], body.signed_by_name
    text = "Job completed on site." + (f"\n{body.notes}" if body.notes else "") + (f"\nFollow-up needed: {body.follow_up}" if body.follow_up else "")
    db.add(ProjectItem(job_id=j.id, kind="note", number=project.next_item_no(db, j.id, "note"), title="Completed on site", body=text,
                       status="closed", created_by=user.id))
    for u in db.scalars(select(User).where(User.active.is_(True))):
        if u.role == "admin" or u.id == j.supervisor_id:
            plant.notify(db, u.id, "job_complete", f"{user.name or user.email} completed {j.job_no} {j.name}. Ready to invoice.",
                         f"/work/{j.id}", key=f"complete-{j.id}-{u.id}-{ts.now():%Y%m%d%H%M}")
    from .. import crm

    crm.on_event(db, "job_complete", job=j)
    db.commit()
    return _brief(db, j)


# --- pre-starts, plant and vehicles ---
@router.get("/plant")
def plant_list(db: Session = Depends(get_db), user: User = Depends(current_user)):
    d = ts.local_day(ts.now())
    out = []
    for p in db.scalars(select(Plant).where(Plant.status != "sold").order_by(Plant.kind, Plant.name)):
        if p.kind == "vehicle" and p.assigned_user_id not in (None, user.id) and user.role == "field":
            continue
        pre = plant.last_check(db, p.id, "prestart", ts.day_bounds(d)[0])
        out.append({"id": p.id, "kind": p.kind, "name": p.name, "fleet_no": p.fleet_no, "rego": p.rego, "category": p.category,
                    "status": p.status, "mine": p.assigned_user_id == user.id, "photos_required": p.photos_required,
                    "hours": p.hours, "odometer": p.odometer,
                    "prestart_today": bool(pre), "prestart_passed": bool(pre and pre.passed),
                    "weekly_done": bool(plant.last_check(db, p.id, "weekly", ts.day_bounds(ts.week_start(d))[0])),
                    "wash_done": bool(plant.last_check(db, p.id, "wash", ts.day_bounds(d.replace(day=1))[0])),
                    "end_day_done": bool(plant.last_check(db, p.id, "end_day", ts.day_bounds(d)[0], user.id)),
                    "open_defects": sum(1 for _ in db.scalars(select(PlantDefect.id).where(PlantDefect.plant_id == p.id,
                                                                                       PlantDefect.status.in_(("open", "in_repair")))))})
    return out


@router.get("/plant/{plant_id}/checklist")
def plant_checklist(plant_id: int, kind: str = "prestart", db: Session = Depends(get_db), _: User = Depends(current_user)):
    p = get_or_404(db, Plant, plant_id)
    photos = {"prestart": ["machine", "fuel"] if p.photos_required else [], "weekly": ["front", "back"], "start_day": ["machine", "fuel"],
              "end_day": ["machine", "fuel"], "wash": ["exterior", "interior"]}.get(kind, [])
    if p.kind == "vehicle" and kind == "prestart":
        photos = []
    fields = plant.checklist(db, p) if kind in ("prestart", "weekly") else []
    return {"plant": {"id": p.id, "name": p.name, "kind": p.kind, "rego": p.rego, "hours": p.hours, "odometer": p.odometer},
            "kind": kind, "fields": fields, "photos": photos, "reading": "km" if p.kind == "vehicle" else "hours"}


class CheckIn(BaseModel):
    kind: str  # prestart | weekly | end_day | wash
    answers: dict = {}
    hours: float | None = Field(default=None, ge=0)
    odometer: float | None = Field(default=None, ge=0)
    fuel_pct: float | None = Field(default=None, ge=0, le=100)
    photo_ids: dict[str, int] = {}
    notes: str = ""
    job_id: int | None = None
    lat: float | None = None
    lng: float | None = None


@router.post("/plant/{plant_id}/check")
def plant_check(plant_id: int, body: CheckIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    p = get_or_404(db, Plant, plant_id)
    if body.kind not in ("prestart", "weekly", "end_day", "wash", "start_day"):
        raise HTTPException(422, "Unknown check")
    spec = plant_checklist(plant_id, body.kind, db, user)
    missing_photos = [k for k in spec["photos"] if not body.photo_ids.get(k)]
    if missing_photos:
        raise HTTPException(422, f"Add the photo{'s' if len(missing_photos) > 1 else ''}: {', '.join(missing_photos)}")
    for pid in body.photo_ids.values():
        d = db.get(Document, pid)
        if d is None or d.uploaded_by != user.id:
            raise HTTPException(422, "A photo didn't upload. Take it again.")
    fields = spec["fields"]
    unanswered = [f["label"] for f in fields if f.get("type") == "yesno" and body.answers.get(f["key"]) is None]
    if unanswered:
        raise HTTPException(422, f"Answer every question (\"{unanswered[0]}\")")
    failed = plant.failed_items(fields, body.answers)
    chk = PlantCheck(plant_id=p.id, user_id=user.id, kind=body.kind, answers=body.answers, passed=not failed, hours=body.hours,
                     odometer=body.odometer, fuel_pct=body.fuel_pct, photo_ids=body.photo_ids, notes=body.notes, job_id=body.job_id,
                     lat=body.lat, lng=body.lng)
    db.add(chk)
    db.flush()
    plant.record_readings(p, body.hours, body.odometer)
    if failed:
        plant.report_defect(db, p, user, "major", "Failed pre-start: " + "; ".join(failed) + (f". {body.notes}" if body.notes else ""),
                            list(body.photo_ids.values()), check_id=chk.id)
    db.commit()
    return {"id": chk.id, "passed": chk.passed, "failed": failed}


class DefectIn(BaseModel):
    kind: str = "damage"  # defect | damage | incident
    severity: str = "minor"
    description: str = Field(min_length=3)
    photo_ids: list[int] = []


@router.post("/plant/{plant_id}/defects")
def plant_defect(plant_id: int, body: DefectIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    p = get_or_404(db, Plant, plant_id)
    if body.severity not in ("minor", "major", "critical") or body.kind not in ("defect", "damage", "incident"):
        raise HTTPException(422, "Pick how bad it is")
    d = plant.report_defect(db, p, user, body.severity, body.description, body.photo_ids, kind=body.kind)
    db.commit()
    return {"id": d.id, "plant_status": p.status}


@router.post("/notifications/{note_id}/read", status_code=204)
def read_note(note_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    n = db.get(Notification, note_id)
    if n is not None and n.user_id == user.id:
        n.read_at = ts.now()
        db.commit()
