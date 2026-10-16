"""Safety and ITPs: the office side (/api/safety, job tabs, templates), everyone's side on the phone (/api/field/safety)
and PDFs to download, share or email (/api/field/pdf)."""
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import features, itp, messaging, pdfs
from .. import safety as sf
from ..access import can_see_job
from ..audit import record
from ..auth import current_user
from ..db import get_db
from ..models import (FormResponse, ItpTemplate, Job, JobItp, JobSwms, PlantCheck, SafetyAction, SafetyEvent, SitePrestart, SwmsSignon,
                      SwmsTemplate, ToolboxTalk, User)
from ..plant import notify
from . import get_or_404

router = APIRouter(prefix="/api", tags=["safety"])
field = APIRouter(prefix="/api/field", tags=["safety"])


def _names(db: Session) -> dict[int, str]:
    return {u.id: u.name or u.email for u in db.scalars(select(User))}


def _job(db: Session, job_id: int | None, user: User) -> Job | None:
    if not job_id:
        return None
    j = get_or_404(db, Job, job_id)
    if not can_see_job(user, j):
        raise HTTPException(404, "Job not found")
    return j


# ================= office =================
@router.get("/safety/dashboard")
def dashboard(db: Session = Depends(get_db), _: User = Depends(current_user)):
    return sf.dashboard(db)


@router.get("/safety/options")
def options(db: Session = Depends(get_db), _: User = Depends(current_user)):
    return {"high_risk": sf.HIGH_RISK, "event_kinds": sf.EVENT_KINDS, "treatment": sf.TREATMENT, "prestart_questions": sf.PRESTART_QUESTIONS,
            "itp_points": itp.POINTS, "itp_frequency": itp.FREQUENCY,
            "swms_templates": [swms_tpl_out(t) for t in db.scalars(select(SwmsTemplate).order_by(SwmsTemplate.title))],
            "itp_templates": [{"id": t.id, "name": t.name, "items": t.items, "active": t.active}
                              for t in db.scalars(select(ItpTemplate).order_by(ItpTemplate.name))]}


def swms_tpl_out(t: SwmsTemplate) -> dict:
    return {"id": t.id, "title": t.title, "activity": t.activity, "high_risk": t.high_risk, "ppe": t.ppe, "steps": t.steps, "version": t.version,
            "active": t.active}


class SwmsIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    activity: str = ""
    high_risk: list[str] = []
    ppe: list[str] = []
    steps: list[dict] = []
    active: bool = True


@router.post("/safety/swms-templates")
def add_swms_tpl(body: SwmsIn, db: Session = Depends(get_db), _: User = Depends(current_user)):
    t = SwmsTemplate(**body.model_dump())
    db.add(t)
    db.commit()
    return swms_tpl_out(t)


@router.put("/safety/swms-templates/{tpl_id}")
def edit_swms_tpl(tpl_id: int, body: SwmsIn, db: Session = Depends(get_db), _: User = Depends(current_user)):
    t = get_or_404(db, SwmsTemplate, tpl_id)
    for k, v in body.model_dump().items():
        setattr(t, k, v)
    t.version += 1
    t.updated_at = datetime.now(timezone.utc)
    db.commit()
    return swms_tpl_out(t)


@router.get("/safety/events")
def list_events(status: str = "", kind: str = "", job_id: int | None = None, db: Session = Depends(get_db), user: User = Depends(current_user)):
    stmt = select(SafetyEvent).order_by(SafetyEvent.occurred_at.desc())
    if status:
        stmt = stmt.where(SafetyEvent.status == status)
    if kind:
        stmt = stmt.where(SafetyEvent.kind == kind)
    if job_id:
        stmt = stmt.where(SafetyEvent.job_id == job_id)
    names = _names(db)
    return [sf.event_out(db, e, names) for e in db.scalars(stmt.limit(500))]


class EventPatch(BaseModel):
    status: str | None = Field(default=None, pattern="^(open|investigating|closed)$")
    severity: str | None = Field(default=None, pattern="^(low|medium|high|critical)$")
    root_cause: str | None = None
    notifiable: bool | None = None
    treatment: str | None = Field(default=None, pattern="^(none|first_aid|medical|lost_time)$")


@router.patch("/safety/events/{event_id}")
def edit_event(event_id: int, body: EventPatch, db: Session = Depends(get_db), user: User = Depends(current_user)):
    e = get_or_404(db, SafetyEvent, event_id)
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(e, k, v)
    if data.get("status") == "closed":
        e.closed_at, e.closed_by = datetime.now(timezone.utc), user.id
    record(db, user.id, "safety_event", e.id, "update", after=data)
    db.commit()
    return sf.event_out(db, e, _names(db))


class ActionIn(BaseModel):
    description: str = Field(min_length=1)
    assignee_id: int | None = None
    due: date | None = None
    job_id: int | None = None


@router.post("/safety/events/{event_id}/actions")
def add_action(event_id: int, body: ActionIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    e = get_or_404(db, SafetyEvent, event_id)
    a = SafetyAction(event_id=e.id, job_id=body.job_id or e.job_id, description=body.description, assignee_id=body.assignee_id, due=body.due,
                     created_by=user.id)
    db.add(a)
    db.flush()
    if a.assignee_id and a.assignee_id != user.id:
        notify(db, a.assignee_id, "safety", f"Safety action for you: {a.description[:120]}", "/field/safety", key=f"sa-{a.id}")
    if e.status == "open":
        e.status = "investigating"
    db.commit()
    return sf.event_out(db, e, _names(db))


@router.post("/safety/actions")
def add_free_action(body: ActionIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    a = SafetyAction(**body.model_dump(), created_by=user.id)
    db.add(a)
    db.flush()
    if a.assignee_id and a.assignee_id != user.id:
        notify(db, a.assignee_id, "safety", f"Safety action for you: {a.description[:120]}", "/field/safety", key=f"sa-{a.id}")
    db.commit()
    return sf.action_out(a, _names(db))


@router.get("/safety/actions")
def list_actions(status: str = "open", db: Session = Depends(get_db), _: User = Depends(current_user)):
    stmt = select(SafetyAction).order_by(SafetyAction.due.is_(None), SafetyAction.due)
    if status:
        stmt = stmt.where(SafetyAction.status == status)
    names = _names(db)
    return [sf.action_out(a, names) for a in db.scalars(stmt)]


@router.get("/safety/toolbox")
def list_toolbox(db: Session = Depends(get_db), _: User = Depends(current_user)):
    names = _names(db)
    return [toolbox_out(db, t, names) for t in db.scalars(select(ToolboxTalk).order_by(ToolboxTalk.day.desc()).limit(200))]


def toolbox_out(db: Session, t: ToolboxTalk, names: dict[int, str]) -> dict:
    j = db.get(Job, t.job_id) if t.job_id else None
    return {"id": t.id, "job_id": t.job_id, "job": f"{j.job_no or ''} {j.name}".strip() if j else "", "topic": t.topic, "notes": t.notes,
            "day": t.day.isoformat(), "presenter": names.get(t.presenter_id or 0, ""), "attendees": t.attendees}


@router.get("/safety/prestarts")
def list_prestarts(day: date | None = None, db: Session = Depends(get_db), _: User = Depends(current_user)):
    names = _names(db)
    stmt = select(SitePrestart).order_by(SitePrestart.day.desc(), SitePrestart.id.desc())
    if day:
        stmt = stmt.where(SitePrestart.day == day)
    out = []
    for sp in db.scalars(stmt.limit(300)):
        j = db.get(Job, sp.job_id)
        out.append({**sf.prestart_out(sp, names), "job": f"{j.job_no or ''} {j.name}".strip() if j else ""})
    return out


@router.get("/safety/signons")
def list_signons(job_id: int | None = None, db: Session = Depends(get_db), _: User = Depends(current_user)):
    names = _names(db)
    stmt = select(SwmsSignon, JobSwms).join(JobSwms, JobSwms.id == SwmsSignon.job_swms_id).order_by(SwmsSignon.signed_at.desc())
    if job_id:
        stmt = stmt.where(JobSwms.job_id == job_id)
    return [{"swms": js.title, "job_id": js.job_id, "name": names.get(s.user_id, s.typed_name), "version": s.version, "at": s.signed_at.isoformat()}
            for s, js in db.execute(stmt.limit(500)).all()]


# --- a job's SWMS, ITPs and pre-starts (the job hub tabs) ---
@router.get("/jobs/{job_id}/swms")
def job_swms(job_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    _job(db, job_id, user)
    names = _names(db)
    return [sf.swms_out(db, js, names) for js in db.scalars(select(JobSwms).where(JobSwms.job_id == job_id).order_by(JobSwms.id))]


class AddSwms(BaseModel):
    template_id: int
    site_notes: str = ""


@router.post("/jobs/{job_id}/swms")
def add_job_swms(job_id: int, body: AddSwms, db: Session = Depends(get_db), user: User = Depends(current_user)):
    j = _job(db, job_id, user)
    t = get_or_404(db, SwmsTemplate, body.template_id)
    js = sf.add_to_job(db, j, t, user, body.site_notes)
    db.commit()
    return sf.swms_out(db, js, _names(db))


class SwmsPatch(BaseModel):
    title: str | None = None
    site_notes: str | None = None
    steps: list[dict] | None = None
    ppe: list[str] | None = None
    high_risk: list[str] | None = None
    status: str | None = Field(default=None, pattern="^(active|archived)$")


@router.patch("/job-swms/{swms_id}")
def edit_job_swms(swms_id: int, body: SwmsPatch, db: Session = Depends(get_db), user: User = Depends(current_user)):
    js = get_or_404(db, JobSwms, swms_id)
    _job(db, js.job_id, user)
    data = body.model_dump(exclude_unset=True)
    changed = any(k in data for k in ("steps", "ppe", "high_risk", "site_notes"))
    for k, v in data.items():
        setattr(js, k, v)
    if changed:
        js.version += 1  # the content changed: everyone signs on again
        for uid in {s.user_id for s in db.scalars(select(SwmsSignon).where(SwmsSignon.job_swms_id == js.id))}:
            notify(db, uid, "safety", f"The {js.title} SWMS changed. Read it and sign on again.", "/field/safety", key=f"swmsv-{js.id}-{js.version}-{uid}")
    db.commit()
    return sf.swms_out(db, js, _names(db))


@router.get("/jobs/{job_id}/itps")
def job_itps(job_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    _job(db, job_id, user)
    names = _names(db)
    return [itp.itp_out(db, ji, names) for ji in db.scalars(select(JobItp).where(JobItp.job_id == job_id).order_by(JobItp.id))]


class AddItp(BaseModel):
    template_id: int
    area: str = ""


@router.post("/jobs/{job_id}/itps")
def add_job_itp(job_id: int, body: AddItp, db: Session = Depends(get_db), user: User = Depends(current_user)):
    j = _job(db, job_id, user)
    t = get_or_404(db, ItpTemplate, body.template_id)
    ji = itp.create(db, j, t, body.area)
    db.commit()
    return itp.itp_out(db, ji, _names(db))


@router.delete("/job-itps/{itp_id}", status_code=204)
def delete_job_itp(itp_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    ji = get_or_404(db, JobItp, itp_id)
    _job(db, ji.job_id, user)
    if itp.checks(db, ji):
        raise HTTPException(409, "It has checks recorded; keep it as a record")
    db.delete(ji)
    db.commit()


class ItpTplIn(BaseModel):
    name: str = Field(min_length=1)
    items: list[dict] = []
    active: bool = True


def _clean_items(items: list[dict]) -> list[dict]:
    out, keys = [], set()
    for n, i in enumerate(items, 1):
        if not str(i.get("activity") or "").strip():
            raise HTTPException(422, f"Item {n} needs an activity")
        key = str(i.get("key") or f"i{n}")
        while key in keys:
            key += "x"
        keys.add(key)
        out.append({"key": key, "stage": str(i.get("stage") or ""), "activity": str(i["activity"]), "check": str(i.get("check") or ""),
                    "criteria": str(i.get("criteria") or ""), "frequency": i.get("frequency") if i.get("frequency") in itp.FREQUENCY else "once",
                    "point": i.get("point") if i.get("point") in itp.POINTS else "none", "who": str(i.get("who") or ""),
                    "record": i.get("record") if i.get("record") in ("photo", "reading", "signature", "none") else "none"})
    return out


@router.post("/itp-templates")
def add_itp_tpl(body: ItpTplIn, db: Session = Depends(get_db), _: User = Depends(current_user)):
    t = ItpTemplate(name=body.name, items=_clean_items(body.items), active=body.active)
    db.add(t)
    db.commit()
    return {"id": t.id}


@router.put("/itp-templates/{tpl_id}")
def edit_itp_tpl(tpl_id: int, body: ItpTplIn, db: Session = Depends(get_db), _: User = Depends(current_user)):
    t = get_or_404(db, ItpTemplate, tpl_id)
    t.name, t.items, t.active = body.name, _clean_items(body.items), body.active
    db.commit()
    return {"id": t.id}


@router.get("/jobs/{job_id}/prestarts")
def job_prestarts(job_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    _job(db, job_id, user)
    names = _names(db)
    return [sf.prestart_out(sp, names) for sp in db.scalars(select(SitePrestart).where(SitePrestart.job_id == job_id).order_by(SitePrestart.day.desc()))]


# ================= everyone (the phone) =================
@field.get("/safety/today")
def my_today(db: Session = Depends(get_db), user: User = Depends(current_user)):
    """What's left to do before (and while) working on each of today's jobs."""
    names = _names(db)
    acts = [sf.action_out(a, names) for a in db.scalars(select(SafetyAction).where(SafetyAction.assignee_id == user.id, SafetyAction.status == "open"))]
    return {"jobs": sf.my_day(db, user), "actions": acts}


@field.get("/safety/jobs/{job_id}")
def job_safety(job_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    j = _job(db, job_id, user)
    names = _names(db)
    sp = db.scalar(select(SitePrestart).where(SitePrestart.job_id == j.id, SitePrestart.day == sf.today()))
    return {"job": {"id": j.id, "job_no": j.job_no, "name": j.name, "address": j.address},
            "swms": [sf.swms_out(db, js, names, user.id) for js in db.scalars(select(JobSwms).where(JobSwms.job_id == j.id, JobSwms.status == "active"))],
            "prestart": sf.prestart_out(sp, names) if sp else None, "prestart_questions": sf.PRESTART_QUESTIONS,
            "itps": [itp.itp_out(db, ji, names) for ji in db.scalars(select(JobItp).where(JobItp.job_id == j.id).order_by(JobItp.id))],
            "prompts": sf.prompts(db, user, j)}


class SignIn(BaseModel):
    typed_name: str = Field(min_length=2, max_length=200)
    signature: str = Field(default="", max_length=400_000)


@field.post("/safety/swms/{swms_id}/sign")
def sign_swms(swms_id: int, body: SignIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    js = get_or_404(db, JobSwms, swms_id)
    _job(db, js.job_id, user)
    sf.sign_on(db, js, user, body.typed_name, body.signature)
    db.commit()
    return sf.swms_out(db, js, _names(db), user.id)


class PrestartIn(BaseModel):
    job_id: int
    answers: dict = {}
    signature: str = Field(default="", max_length=400_000)


@field.post("/safety/prestart")
def save_prestart(body: PrestartIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """The first person in fills it in; it's the same pre-start for everyone on that job today, and each person signs on."""
    j = _job(db, body.job_id, user)
    day = sf.today()
    sp = db.scalar(select(SitePrestart).where(SitePrestart.job_id == j.id, SitePrestart.day == day))
    if sp is None:
        sp = SitePrestart(job_id=j.id, day=day, led_by=user.id, answers={}, attendees=[])
        db.add(sp)
    if body.answers:
        sp.answers = {**(sp.answers or {}), **body.answers}
    sf.sign_attendee(sp, user, body.signature)
    db.commit()
    return sf.prestart_out(sp, _names(db))


class CheckIn(BaseModel):
    item_key: str
    result: str = Field(pattern="^(pass|fail|na)$")
    reading: str = ""
    notes: str = ""
    photos: list[int] = []
    signed_name: str = ""
    signed_role: str = ""
    signature: str = Field(default="", max_length=400_000)


@field.get("/safety/itps/{itp_id}")
def get_itp(itp_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    ji = get_or_404(db, JobItp, itp_id)
    _job(db, ji.job_id, user)
    return itp.itp_out(db, ji, _names(db))


@field.post("/safety/itps/{itp_id}/check")
def check_itp(itp_id: int, body: CheckIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    ji = get_or_404(db, JobItp, itp_id)
    _job(db, ji.job_id, user)
    try:
        itp.record(db, ji, user, **body.model_dump())
    except ValueError as e:
        raise HTTPException(422, str(e))
    db.commit()
    return itp.itp_out(db, ji, _names(db))


class ReportIn(BaseModel):
    kind: str = Field(default="hazard", pattern="^(hazard|near_miss|incident|injury|property|environment)$")
    title: str = Field(min_length=2, max_length=300)
    description: str = ""
    immediate_action: str = ""
    severity: str = Field(default="medium", pattern="^(low|medium|high|critical)$")
    treatment: str = Field(default="none", pattern="^(none|first_aid|medical|lost_time)$")
    people: str = ""
    location: str = ""
    job_id: int | None = None
    photos: list[int] = []
    occurred_at: datetime | None = None


@field.post("/safety/report")
def report(body: ReportIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if body.job_id:
        _job(db, body.job_id, user)
    data = body.model_dump()
    if not data["occurred_at"]:
        data.pop("occurred_at")
    e = sf.report(db, user, **data)
    db.commit()
    return {"id": e.id}


class ToolboxIn(BaseModel):
    topic: str = Field(min_length=2, max_length=300)
    notes: str = ""
    job_id: int | None = None
    signature: str = Field(default="", max_length=400_000)


@field.post("/safety/toolbox")
def add_toolbox(body: ToolboxIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if body.job_id:
        _job(db, body.job_id, user)
    t = ToolboxTalk(job_id=body.job_id, topic=body.topic, notes=body.notes, day=sf.today(), presenter_id=user.id, attendees=[])
    sf.sign_attendee(t, user, body.signature)
    db.add(t)
    db.commit()
    return toolbox_out(db, t, _names(db))


@field.get("/safety/toolbox/recent")
def recent_toolbox(db: Session = Depends(get_db), user: User = Depends(current_user)):
    names = _names(db)
    return [toolbox_out(db, t, names) for t in db.scalars(select(ToolboxTalk).where(ToolboxTalk.day >= sf.today()).order_by(ToolboxTalk.id.desc()))]


@field.post("/safety/toolbox/{talk_id}/sign")
def sign_toolbox(talk_id: int, body: SignIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    t = get_or_404(db, ToolboxTalk, talk_id)
    sf.sign_attendee(t, user, body.signature)
    db.commit()
    return toolbox_out(db, t, _names(db))


class DoneIn(BaseModel):
    note: str = ""


@field.post("/safety/actions/{action_id}/done")
def action_done(action_id: int, body: DoneIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    a = get_or_404(db, SafetyAction, action_id)
    office = user.role != "field" and features.level(db, user, "safety") == "edit"
    if a.assignee_id not in (user.id, None) and user.role != "admin" and not office:
        raise HTTPException(404, "Not found")
    a.status, a.done_at, a.done_note = "done", datetime.now(timezone.utc), body.note
    db.commit()
    return sf.action_out(a, _names(db))


# ================= PDFs =================
KINDS = {
    "itp": (JobItp, pdfs.itp_pdf, lambda r: f"{r.name} {r.area}"),
    "prestart": (SitePrestart, pdfs.site_prestart_pdf, lambda r: f"site-prestart {r.day}"),
    "plant-check": (PlantCheck, pdfs.plant_check_pdf, lambda r: f"{r.kind} {r.at:%Y-%m-%d}"),
    "swms": (JobSwms, pdfs.swms_pdf, lambda r: r.title),
    "incident": (SafetyEvent, pdfs.event_pdf, lambda r: r.title),
    "toolbox": (ToolboxTalk, pdfs.toolbox_pdf, lambda r: f"{r.topic} {r.day}"),
    "form": (FormResponse, pdfs.form_pdf, lambda r: f"form {r.id}"),
}


def _pdf(db: Session, kind: str, rid: int, user: User) -> tuple[bytes, str]:
    if kind not in KINDS:
        raise HTTPException(404, "Unknown report")
    model, fn, label = KINDS[kind]
    r = get_or_404(db, model, rid)
    job_id = getattr(r, "job_id", None)
    if job_id:
        _job(db, job_id, user)
    elif user.role == "field" and kind == "plant-check" and r.user_id != user.id:
        pass  # anyone on the tools may see a machine's pre-start (they share the machine)
    return fn(db, r), pdfs.filename(kind, label(r))


@field.get("/pdf/{kind}/{rid}")
def pdf(kind: str, rid: int, download: bool = False, db: Session = Depends(get_db), user: User = Depends(current_user)):
    data, name = _pdf(db, kind, rid, user)
    return Response(data, media_type="application/pdf",
                    headers={"Content-Disposition": f'{"attachment" if download else "inline"}; filename="{name}"'})


class EmailIn(BaseModel):
    to: str = Field(min_length=3, max_length=500)
    message: str = ""


@field.post("/pdf/{kind}/{rid}/email")
def email_pdf(kind: str, rid: int, body: EmailIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    data, name = _pdf(db, kind, rid, user)
    to = [a.strip() for a in body.to.replace(";", ",").split(",") if "@" in a]
    if not to:
        raise HTTPException(422, "Add an email address")
    from .. import ops

    company = ops.settings(db)["company_name"]
    try:
        for addr in to:
            messaging.send_email(addr, f"{name.rsplit('.', 1)[0].replace('-', ' ').title()} – {company}",
                                 f"{body.message}\n\nAttached: {name}\n\n{user.name or user.email}\n{company}".strip(),
                                 attachments=[(name, data, "application/pdf")])
    except messaging.NotConfigured as e:
        raise HTTPException(409, f"{e}. Download it and share it from your phone instead.")
    record(db, user.id, "pdf", rid, "email", after={"kind": kind, "to": to})
    db.commit()
    return {"sent": len(to)}
