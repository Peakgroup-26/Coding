"""People (HR): the office side at /api/people (needs can_hr), everyone's own side at /api/field/me
(works for the phone app and the office), and the public careers page at /api/public/careers."""
import json
import mimetypes
import secrets
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import config, hr, storage
from ..audit import record
from ..auth import ROLES, current_user, hash_password
from ..db import get_db
from ..models import (Announcement, Candidate, CandidateNote, ChecklistTask, ChecklistTemplate, Credential, CredentialType,
                      EmployeeFile, EmployeeProfile, Goal, IssuedItem, JobOpening, LeaveAdjustment, LeavePolicy, PayChange, Policy,
                      PolicySignature, Review, ReviewCycle, Survey, SurveyInvite, SurveyResponse, TimeOff, User)
from ..plant import notify
from . import get_or_404

router = APIRouter(prefix="/api/people", tags=["people"])
me = APIRouter(prefix="/api/field/me", tags=["people"])
public = APIRouter(prefix="/api/public/careers", tags=["public"])

PROFILE_FIELDS = ["position", "department", "employment_type", "status", "start_date", "end_date", "end_reason", "manager_id",
                  "hours_per_week", "award", "apprentice_year", "dob", "personal_email", "address", "emergency_contacts",
                  "drivers_licence", "shirt_size", "pants_size", "boot_size", "medical_notes", "notes"]
SELF_FIELDS = ["personal_email", "address", "emergency_contacts", "drivers_licence", "shirt_size", "pants_size", "boot_size",
               "medical_notes", "dob"]


def _iso(v):
    return v.isoformat() if isinstance(v, (date, datetime)) else v


def _names(db: Session) -> dict[int, str]:
    return {u.id: u.name or u.email for u in db.scalars(select(User))}


async def _read(upload: UploadFile) -> bytes:
    data = await upload.read(config.MAX_UPLOAD_BYTES + 1)
    if len(data) > config.MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"{upload.filename} is too large")
    if not data:
        raise HTTPException(422, f"{upload.filename} is empty")
    return data


def _send(key: str, name: str) -> Response:
    if not key:
        raise HTTPException(404, "No file")
    safe = "".join(c if c.isalnum() or c in ".-_ " else "_" for c in name or "file")
    return Response(storage.read_bytes(key), media_type=mimetypes.guess_type(name or "")[0] or "application/octet-stream",
                    headers={"Content-Disposition": f'inline; filename="{safe}"'})


def profile_out(db: Session, u: User, p: EmployeeProfile, names: dict[int, str]) -> dict:
    out = {"user_id": u.id, "name": u.name or u.email, "email": u.email, "phone": u.phone, "role": u.role, "trade": u.trade,
           "active": u.active, "has_photo": bool(p.photo_key), "manager": names.get(p.manager_id or 0, ""),
           "years_of_service": round(hr.years_of_service(p), 1)}
    for f in PROFILE_FIELDS:
        out[f] = _iso(getattr(p, f))
    return out


def directory_row(u: User, p: EmployeeProfile | None, names: dict[int, str]) -> dict:
    return {"user_id": u.id, "name": u.name or u.email, "email": u.email, "phone": u.phone, "trade": u.trade,
            "position": p.position if p else "", "department": p.department if p else "", "manager_id": p.manager_id if p else None,
            "manager": names.get((p.manager_id if p else None) or 0, ""), "has_photo": bool(p and p.photo_key),
            "status": p.status if p else "active"}


def _staff(db: Session, include_left: bool = False) -> list[tuple[User, EmployeeProfile | None]]:
    profiles = {p.user_id: p for p in db.scalars(select(EmployeeProfile))}
    out = []
    for u in db.scalars(select(User).order_by(User.name, User.email)):
        p = profiles.get(u.id)
        if not include_left and (not u.active or (p and p.status == "terminated" and p.end_date and p.end_date < hr.today_local())):
            continue
        out.append((u, p))
    return out


# ============ office side ============
@router.get("")
def people(include_left: bool = False, db: Session = Depends(get_db), _: User = Depends(current_user)):
    names = _names(db)
    out = []
    for u, p in _staff(db, include_left):
        c = hr.compliance(db, u)
        out.append({**directory_row(u, p, names), "employment_type": p.employment_type if p else "",
                    "start_date": _iso(p.start_date) if p else None, "active": u.active,
                    "years_of_service": round(hr.years_of_service(p), 1) if p else None,
                    "missing": len(c["missing"]), "expired": c["expired"], "expiring": c["expiring"]})
    return out


class NewPerson(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=8)
    role: str = "field"
    trade: str = ""
    phone: str = ""
    position: str = ""
    department: str = ""
    employment_type: str = "full_time"
    start_date: date | None = None
    manager_id: int | None = None
    checklist_id: int | None = None


@router.post("")
def add_person(body: NewPerson, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if body.role not in ROLES or (body.role == "admin" and user.role != "admin"):
        raise HTTPException(422, "Pick field, estimator or reviewer")
    if db.scalar(select(User).where(func.lower(User.email) == body.email.strip().lower())):
        raise HTTPException(409, "Someone already signs in with that email")
    u = User(email=body.email.strip().lower(), name=body.name, role=body.role, password_hash=hash_password(body.password),
             trade=body.trade, phone=body.phone, can_ops=body.role != "field", can_finance=False)
    db.add(u)
    db.flush()
    p = hr.profile(db, u.id)
    for f in ("position", "department", "employment_type", "start_date", "manager_id"):
        setattr(p, f, getattr(body, f))
    if body.checklist_id:
        tpl = get_or_404(db, ChecklistTemplate, body.checklist_id)
        hr.start_checklist(db, u, tpl, body.start_date or hr.today_local(), user)
    record(db, user.id, "employee", u.id, "create", after={"name": u.name, "email": u.email, "role": u.role})
    db.commit()
    return profile_out(db, u, p, _names(db))


@router.get("/report")
def people_report(db: Session = Depends(get_db), _: User = Depends(current_user)):
    return hr.report(db)


@router.get("/options")
def options(db: Session = Depends(get_db), _: User = Depends(current_user)):
    return {"departments": hr.DEPARTMENTS, "employment_types": hr.EMPLOYMENT_TYPES, "stages": hr.STAGES,
            "credential_types": [{"id": t.id, "name": t.name, "category": t.category, "renew_months": t.renew_months,
                                  "required_for": t.required_for, "active": t.active}
                                 for t in db.scalars(select(CredentialType).order_by(CredentialType.category, CredentialType.name))],
            "checklists": [{"id": t.id, "name": t.name, "kind": t.kind, "tasks": t.tasks, "active": t.active}
                           for t in db.scalars(select(ChecklistTemplate).order_by(ChecklistTemplate.kind, ChecklistTemplate.name))],
            "policies": [{"id": p.id, "kind": p.kind, "name": p.name, "hours_per_year": p.hours_per_year,
                          "accrues_on_hours": p.accrues_on_hours, "after_years": p.after_years, "casuals": p.casuals, "active": p.active}
                         for p in db.scalars(select(LeavePolicy).order_by(LeavePolicy.id))],
            "review_questions": hr.DEFAULT_REVIEW_QUESTIONS, "enps_question": hr.ENPS_QUESTION}


@router.get("/leave")
def leave_overview(db: Session = Depends(get_db), _: User = Depends(current_user)):
    out = []
    for u, p in _staff(db):
        if p is None and u.role != "field" and not u.trade:
            continue
        out.append({"user_id": u.id, "name": u.name or u.email, "balances": hr.balances(db, u)})
    return out


class ProfileIn(BaseModel):
    name: str | None = None
    phone: str | None = None
    trade: str | None = None
    position: str = ""
    department: str = ""
    employment_type: str = "full_time"
    status: str = "active"
    start_date: date | None = None
    end_date: date | None = None
    end_reason: str = ""
    manager_id: int | None = None
    hours_per_week: float = Field(default=38.0, ge=0, le=80)
    award: str = ""
    apprentice_year: int | None = Field(default=None, ge=1, le=4)
    dob: date | None = None
    personal_email: str = ""
    address: str = ""
    emergency_contacts: list[dict] = []
    drivers_licence: str = ""
    shirt_size: str = ""
    pants_size: str = ""
    boot_size: str = ""
    medical_notes: str = ""
    notes: str = ""


@router.put("/{user_id}/profile")
def save_profile(user_id: int, body: ProfileIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    u = get_or_404(db, User, user_id)
    if body.manager_id == u.id:
        raise HTTPException(422, "Someone can't be their own manager")
    p = hr.profile(db, u.id)
    before = {f: _iso(getattr(p, f)) for f in PROFILE_FIELDS if f != "medical_notes"}
    for f in PROFILE_FIELDS:
        setattr(p, f, getattr(body, f))
    for f in ("name", "phone", "trade"):
        if getattr(body, f) is not None:
            setattr(u, f, getattr(body, f))
    record(db, user.id, "employee", u.id, "update", before, {f: _iso(getattr(p, f)) for f in PROFILE_FIELDS if f != "medical_notes"})
    db.commit()
    return profile_out(db, u, p, _names(db))


class PayIn(BaseModel):
    effective: date
    pay_type: str = Field(default="hourly", pattern="^(hourly|salary)$")
    amount: float = Field(gt=0)
    position: str = ""
    reason: str = ""
    notes: str = ""
    update_cost_rate: bool = True  # set the cost rate used for job costing to pay x (1 + on-costs)


@router.post("/{user_id}/pay")
def add_pay(user_id: int, body: PayIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    u = get_or_404(db, User, user_id)
    x = PayChange(user_id=u.id, created_by=user.id, **body.model_dump(exclude={"update_cost_rate"}))
    db.add(x)
    db.flush()
    p = hr.profile(db, u.id)
    if body.position:
        p.position = body.position
    if body.update_cost_rate and body.effective <= hr.today_local():
        rate = hr.hourly_rate(db, u.id, p)
        if rate:
            u.cost_rate = round(rate * (1 + hr.settings(db)["oncost_pct"] / 100), 2)
    record(db, user.id, "employee", u.id, "pay", after={"effective": body.effective.isoformat(), "reason": body.reason})
    db.commit()
    return {"id": x.id, "cost_rate": u.cost_rate}


@router.delete("/pay/{pay_id}", status_code=204)
def delete_pay(pay_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    x = get_or_404(db, PayChange, pay_id)
    record(db, user.id, "employee", x.user_id, "pay_delete", before={"effective": _iso(x.effective), "amount": x.amount})
    db.delete(x)
    db.commit()


# --- licences, tickets and training ---
async def _credential(db: Session, user_id: int, type_id: int, number: str, issuer: str, issued: str, expires: str, hours: str,
                      cost: str, notes: str, file: UploadFile | None, by: User, verified: bool) -> Credential:
    t = get_or_404(db, CredentialType, type_id)
    iss = date.fromisoformat(issued) if issued else None
    exp = date.fromisoformat(expires) if expires else hr.default_expiry(db, t.id, iss)
    c = Credential(user_id=user_id, type_id=t.id, number=number, issuer=issuer, issued=iss, expires=exp,
                   hours=float(hours) if hours else None, cost=float(cost) if cost else None, notes=notes)
    if file is not None and file.filename:
        data = await _read(file)
        c.file_key, c.file_name = hr.save_file(f"{user_id}/licences", file.filename, data), file.filename
    if verified:
        c.verified_by, c.verified_at = by.id, datetime.now(timezone.utc)
    db.add(c)
    db.flush()
    return c


@router.post("/{user_id}/credentials")
async def add_credential(user_id: int, type_id: int = Form(...), number: str = Form(""), issuer: str = Form(""), issued: str = Form(""),
                         expires: str = Form(""), hours: str = Form(""), cost: str = Form(""), notes: str = Form(""),
                         file: UploadFile | None = File(None), db: Session = Depends(get_db), user: User = Depends(current_user)):
    get_or_404(db, User, user_id)
    c = await _credential(db, user_id, type_id, number, issuer, issued, expires, hours, cost, notes, file, user, True)
    db.commit()
    return hr.credential_out(c, db.get(CredentialType, c.type_id), hr.settings(db)["warn_days"])


class CredentialPatch(BaseModel):
    number: str | None = None
    issuer: str | None = None
    issued: date | None = None
    expires: date | None = None
    notes: str | None = None
    verified: bool | None = None


@router.patch("/credentials/{cred_id}")
def edit_credential(cred_id: int, body: CredentialPatch, db: Session = Depends(get_db), user: User = Depends(current_user)):
    c = get_or_404(db, Credential, cred_id)
    data = body.model_dump(exclude_unset=True)
    v = data.pop("verified", None)
    for k, val in data.items():
        setattr(c, k, val)
    if v is not None:
        c.verified_by, c.verified_at = (user.id, datetime.now(timezone.utc)) if v else (None, None)
    db.commit()
    return hr.credential_out(c, db.get(CredentialType, c.type_id), hr.settings(db)["warn_days"])


@router.delete("/credentials/{cred_id}", status_code=204)
def delete_credential(cred_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    c = get_or_404(db, Credential, cred_id)
    if c.file_key:
        storage.delete(c.file_key)
    db.delete(c)
    db.commit()


@router.get("/credentials/{cred_id}/file")
def credential_file(cred_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    c = get_or_404(db, Credential, cred_id)
    return _send(c.file_key, c.file_name)


class CredTypeIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    category: str = Field(default="licence", pattern="^(licence|ticket|training|induction)$")
    renew_months: int | None = Field(default=None, ge=1, le=240)
    required_for: list[str] = []
    active: bool = True


@router.post("/credential-types")
def add_cred_type(body: CredTypeIn, db: Session = Depends(get_db), _: User = Depends(current_user)):
    if db.scalar(select(CredentialType).where(func.lower(CredentialType.name) == body.name.strip().lower())):
        raise HTTPException(409, "That one's already on the list")
    t = CredentialType(**body.model_dump())
    db.add(t)
    db.commit()
    return {"id": t.id}


@router.put("/credential-types/{type_id}")
def edit_cred_type(type_id: int, body: CredTypeIn, db: Session = Depends(get_db), _: User = Depends(current_user)):
    t = get_or_404(db, CredentialType, type_id)
    for k, v in body.model_dump().items():
        setattr(t, k, v)
    db.commit()
    return {"id": t.id}


@router.get("/credentials")
def all_credentials(db: Session = Depends(get_db), _: User = Depends(current_user)):
    """Everyone's licences in one list, for the compliance matrix."""
    warn = hr.settings(db)["warn_days"]
    types = {t.id: t for t in db.scalars(select(CredentialType))}
    names = _names(db)
    active = {u.id for u, _p in _staff(db)}
    return [{**hr.credential_out(c, types.get(c.type_id), warn), "name": names.get(c.user_id, "")}
            for c in db.scalars(select(Credential).order_by(Credential.expires)) if c.user_id in active]


# --- leave ---
class AdjustIn(BaseModel):
    kind: str
    day: date
    hours: float
    reason: str = ""


@router.post("/{user_id}/leave-adjustments")
def adjust_leave(user_id: int, body: AdjustIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    get_or_404(db, User, user_id)
    if not db.scalar(select(LeavePolicy.id).where(LeavePolicy.kind == body.kind)):
        raise HTTPException(422, "Unknown kind of leave")
    a = LeaveAdjustment(user_id=user_id, created_by=user.id, **body.model_dump())
    db.add(a)
    record(db, user.id, "employee", user_id, "leave_adjust", after=body.model_dump(mode="json"))
    db.commit()
    return {"id": a.id}


@router.delete("/leave-adjustments/{adj_id}", status_code=204)
def delete_adjustment(adj_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    db.delete(get_or_404(db, LeaveAdjustment, adj_id))
    db.commit()


class PolicyIn(BaseModel):
    name: str
    hours_per_year: float = Field(ge=0, le=1000)
    accrues_on_hours: bool = True
    after_years: float = Field(default=0, ge=0, le=20)
    casuals: bool = False
    active: bool = True


@router.put("/leave-policies/{policy_id}")
def edit_leave_policy(policy_id: int, body: PolicyIn, db: Session = Depends(get_db), _: User = Depends(current_user)):
    pol = get_or_404(db, LeavePolicy, policy_id)
    for k, v in body.model_dump().items():
        setattr(pol, k, v)
    db.commit()
    return {"id": pol.id}


# --- private files ---
@router.post("/{user_id}/files")
async def add_files(user_id: int, files: list[UploadFile] = File(...), folder: str = Form("General"), employee_can_see: bool = Form(True),
                    db: Session = Depends(get_db), user: User = Depends(current_user)):
    get_or_404(db, User, user_id)
    out = []
    for f in files:
        data = await _read(f)
        ef = EmployeeFile(user_id=user_id, folder=folder, filename=f.filename or "file", key=hr.save_file(f"{user_id}/files", f.filename or "file", data),
                          mime=f.content_type or "", size=len(data), employee_can_see=employee_can_see, uploaded_by=user.id)
        db.add(ef)
        db.flush()
        out.append(ef.id)
    db.commit()
    return out


@router.get("/files/{file_id}")
def get_file(file_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    f = get_or_404(db, EmployeeFile, file_id)
    return _send(f.key, f.filename)


@router.delete("/files/{file_id}", status_code=204)
def delete_file(file_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    f = get_or_404(db, EmployeeFile, file_id)
    storage.delete(f.key)
    db.delete(f)
    db.commit()


# --- gear issued ---
class GearIn(BaseModel):
    item: str = Field(min_length=1)
    serial: str = ""
    value: float | None = None
    issued: date | None = None
    returned: date | None = None
    notes: str = ""


@router.post("/{user_id}/gear")
def add_gear(user_id: int, body: GearIn, db: Session = Depends(get_db), _: User = Depends(current_user)):
    get_or_404(db, User, user_id)
    g = IssuedItem(user_id=user_id, **body.model_dump())
    db.add(g)
    db.commit()
    return {"id": g.id}


@router.put("/gear/{gear_id}")
def edit_gear(gear_id: int, body: GearIn, db: Session = Depends(get_db), _: User = Depends(current_user)):
    g = get_or_404(db, IssuedItem, gear_id)
    for k, v in body.model_dump().items():
        setattr(g, k, v)
    db.commit()
    return {"id": g.id}


@router.delete("/gear/{gear_id}", status_code=204)
def delete_gear(gear_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    db.delete(get_or_404(db, IssuedItem, gear_id))
    db.commit()


# --- onboarding / offboarding ---
class ChecklistIn(BaseModel):
    name: str = Field(min_length=1)
    kind: str = Field(default="onboarding", pattern="^(onboarding|offboarding)$")
    tasks: list[dict] = []
    active: bool = True


@router.post("/checklists")
def add_checklist(body: ChecklistIn, db: Session = Depends(get_db), _: User = Depends(current_user)):
    t = ChecklistTemplate(**body.model_dump())
    db.add(t)
    db.commit()
    return {"id": t.id}


@router.put("/checklists/{tpl_id}")
def edit_checklist(tpl_id: int, body: ChecklistIn, db: Session = Depends(get_db), _: User = Depends(current_user)):
    t = get_or_404(db, ChecklistTemplate, tpl_id)
    for k, v in body.model_dump().items():
        setattr(t, k, v)
    db.commit()
    return {"id": t.id}


class StartChecklist(BaseModel):
    template_id: int
    start: date | None = None


@router.post("/{user_id}/checklists")
def run_checklist(user_id: int, body: StartChecklist, db: Session = Depends(get_db), user: User = Depends(current_user)):
    u = get_or_404(db, User, user_id)
    tpl = get_or_404(db, ChecklistTemplate, body.template_id)
    tasks = hr.start_checklist(db, u, tpl, body.start or hr.today_local(), user)
    db.commit()
    return {"tasks": len(tasks)}


class OffboardIn(BaseModel):
    end_date: date
    end_reason: str = "resigned"
    template_id: int | None = None


@router.post("/{user_id}/offboard")
def offboard(user_id: int, body: OffboardIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    u = get_or_404(db, User, user_id)
    if u.id == user.id:
        raise HTTPException(409, "You can't offboard yourself")
    p = hr.profile(db, u.id)
    p.end_date, p.end_reason, p.status = body.end_date, body.end_reason, "terminated"
    if body.template_id:
        hr.start_checklist(db, u, get_or_404(db, ChecklistTemplate, body.template_id), body.end_date, user)
    if body.end_date < hr.today_local():
        u.active = False
    gear = [g.item for g in db.scalars(select(IssuedItem).where(IssuedItem.user_id == u.id, IssuedItem.returned.is_(None)))]
    record(db, user.id, "employee", u.id, "offboard", after={"end_date": body.end_date.isoformat(), "reason": body.end_reason})
    db.commit()
    return {"gear_to_collect": gear}


class TaskIn(BaseModel):
    done: bool | None = None
    assignee_id: int | None = None
    due: date | None = None
    title: str | None = None


def _task_update(db: Session, t: ChecklistTask, body: TaskIn, user: User) -> dict:
    data = body.model_dump(exclude_unset=True)
    if "done" in data:
        t.done_at, t.done_by = (datetime.now(timezone.utc), user.id) if data.pop("done") else (None, None)
    for k, v in data.items():
        setattr(t, k, v)
    if "assignee_id" in data and t.assignee_id and t.assignee_id != user.id:
        notify(db, t.assignee_id, "hr", f"For you: {t.title}", "/my-work", key=f"cl-{t.id}-{t.assignee_id}")
    db.commit()
    return hr.task_out(db, t, _names(db))


@router.put("/tasks/{task_id}")
def edit_task(task_id: int, body: TaskIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return _task_update(db, get_or_404(db, ChecklistTask, task_id), body, user)


@router.get("/tasks")
def open_tasks(db: Session = Depends(get_db), _: User = Depends(current_user)):
    names = _names(db)
    return [hr.task_out(db, t, names) for t in db.scalars(select(ChecklistTask).where(ChecklistTask.done_at.is_(None))
                                                          .order_by(ChecklistTask.due))]


# --- policies to sign ---
@router.get("/policies")
def list_policies(db: Session = Depends(get_db), _: User = Depends(current_user)):
    staff = [u for u, _p in _staff(db)]
    out = []
    for p in db.scalars(select(Policy).order_by(Policy.title)):
        signed = set(db.scalars(select(PolicySignature.user_id).where(PolicySignature.policy_id == p.id, PolicySignature.version == p.version)))
        due = [u for u in staff if hr.audience_ok(p.audience, u)]
        out.append({"id": p.id, "title": p.title, "body": p.body, "has_file": bool(p.file_key), "file_name": p.file_name, "version": p.version,
                    "audience": p.audience, "active": p.active, "signed": len([u for u in due if u.id in signed]), "of": len(due),
                    "not_signed": [u.name or u.email for u in due if u.id not in signed]})
    return out


@router.post("/policies")
async def save_policy(title: str = Form(...), body: str = Form(""), audience: str = Form("all"), policy_id: int | None = Form(None),
                      new_version: bool = Form(False), active: bool = Form(True), file: UploadFile | None = File(None),
                      db: Session = Depends(get_db), _: User = Depends(current_user)):
    """Add a policy, or change one. A new version asks everyone to sign again."""
    if audience not in ("all", "field", "office", "none"):
        raise HTTPException(422, "Audience must be all, field, office or none")
    p = get_or_404(db, Policy, policy_id) if policy_id else Policy(title=title)
    if not policy_id:
        db.add(p)
    p.title, p.body, p.audience, p.active = title, body, audience, active
    if file is not None and file.filename:
        data = await _read(file)
        p.file_key, p.file_name = hr.save_file("policies", file.filename, data), file.filename
    if policy_id and new_version:
        p.version += 1
    p.updated_at = datetime.now(timezone.utc)
    db.flush()
    if not policy_id or new_version:
        for u, _p in _staff(db):
            if hr.audience_ok(p.audience, u):
                notify(db, u.id, "policy", f"Please read and sign: {p.title}", "/field/me", key=f"pol-{p.id}-{p.version}-{u.id}")
    db.commit()
    return {"id": p.id, "version": p.version}


@router.get("/policies/{policy_id}/signatures")
def policy_signatures(policy_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    names = _names(db)
    return [{"name": names.get(s.user_id, ""), "version": s.version, "typed_name": s.typed_name, "signed_at": _iso(s.signed_at),
             "signature": s.signature}
            for s in db.scalars(select(PolicySignature).where(PolicySignature.policy_id == policy_id).order_by(PolicySignature.signed_at.desc()))]


# --- reviews and goals ---
class CycleIn(BaseModel):
    name: str = Field(min_length=1)
    due: date | None = None
    questions: list[dict] = []
    user_ids: list[int] = []


@router.get("/reviews")
def list_cycles(db: Session = Depends(get_db), _: User = Depends(current_user)):
    names = _names(db)
    out = []
    for c in db.scalars(select(ReviewCycle).order_by(ReviewCycle.created_at.desc())):
        rs = list(db.scalars(select(Review).where(Review.cycle_id == c.id)))
        out.append({"id": c.id, "name": c.name, "due": _iso(c.due), "status": c.status, "questions": c.questions,
                    "reviews": [{"id": r.id, "user_id": r.user_id, "name": names.get(r.user_id, ""), "reviewer_id": r.reviewer_id,
                                 "reviewer": names.get(r.reviewer_id or 0, ""), "self_done": r.self_done_at is not None,
                                 "manager_done": r.manager_done_at is not None, "shared": r.shared_at is not None, "overall": r.overall}
                                for r in rs]})
    return out


@router.post("/reviews")
def add_cycle(body: CycleIn, db: Session = Depends(get_db), _: User = Depends(current_user)):
    c = ReviewCycle(name=body.name, due=body.due, questions=body.questions or hr.DEFAULT_REVIEW_QUESTIONS)
    db.add(c)
    db.flush()
    ids = body.user_ids or [u.id for u, p in _staff(db) if p is not None or u.role == "field"]
    hr.start_cycle(db, c, ids)
    db.commit()
    return {"id": c.id}


@router.get("/reviews/item/{review_id}")
def review_detail(review_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    r = get_or_404(db, Review, review_id)
    return review_out(db, r, True)


class ReviewPatch(BaseModel):
    reviewer_id: int | None = None
    share: bool | None = None


@router.patch("/reviews/item/{review_id}")
def edit_review(review_id: int, body: ReviewPatch, db: Session = Depends(get_db), _: User = Depends(current_user)):
    r = get_or_404(db, Review, review_id)
    data = body.model_dump(exclude_unset=True)
    if "reviewer_id" in data:
        r.reviewer_id = data["reviewer_id"]
    if data.get("share") is not None:
        r.shared_at = datetime.now(timezone.utc) if data["share"] else None
        if r.shared_at:
            notify(db, r.user_id, "review", "Your review is ready to read.", "/field/me", key=f"rv-shared-{r.id}")
    db.commit()
    return review_out(db, r, True)


@router.put("/reviews/{cycle_id}/status")
def cycle_status(cycle_id: int, status: str, db: Session = Depends(get_db), _: User = Depends(current_user)):
    c = get_or_404(db, ReviewCycle, cycle_id)
    if status not in ("open", "closed"):
        raise HTTPException(422, "open or closed")
    c.status = status
    db.commit()
    return {"id": c.id, "status": c.status}


def review_out(db: Session, r: Review, full: bool) -> dict:
    c = db.get(ReviewCycle, r.cycle_id)
    names = _names(db)
    return {"id": r.id, "cycle": c.name if c else "", "due": _iso(c.due) if c else None, "questions": c.questions if c else [],
            "user_id": r.user_id, "name": names.get(r.user_id, ""), "reviewer_id": r.reviewer_id, "reviewer": names.get(r.reviewer_id or 0, ""),
            "self_answers": r.self_answers, "manager_answers": r.manager_answers if full or r.shared_at else {},
            "self_done": r.self_done_at is not None, "manager_done": r.manager_done_at is not None, "shared": r.shared_at is not None,
            "overall": r.overall if full or r.shared_at else None, "open": (c.status == "open") if c else False}


class GoalIn(BaseModel):
    title: str = Field(min_length=1)
    description: str = ""
    due: date | None = None
    progress: int = Field(default=0, ge=0, le=100)
    status: str = Field(default="open", pattern="^(open|done|dropped)$")


def goal_out(g: Goal) -> dict:
    return {"id": g.id, "user_id": g.user_id, "title": g.title, "description": g.description, "due": _iso(g.due),
            "progress": g.progress, "status": g.status}


@router.post("/{user_id}/goals")
def add_goal(user_id: int, body: GoalIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    get_or_404(db, User, user_id)
    g = Goal(user_id=user_id, created_by=user.id, **body.model_dump())
    db.add(g)
    db.commit()
    return goal_out(g)


@router.put("/goals/{goal_id}")
def edit_goal(goal_id: int, body: GoalIn, db: Session = Depends(get_db), _: User = Depends(current_user)):
    g = get_or_404(db, Goal, goal_id)
    for k, v in body.model_dump().items():
        setattr(g, k, v)
    db.commit()
    return goal_out(g)


# --- staff surveys ---
class SurveyIn(BaseModel):
    title: str = Field(min_length=1)
    questions: list[dict] = []
    anonymous: bool = True
    audience: str = Field(default="all", pattern="^(all|field|office)$")
    closes: date | None = None


@router.get("/surveys")
def list_surveys(db: Session = Depends(get_db), _: User = Depends(current_user)):
    return [{"id": s.id, "title": s.title, "status": s.status, "anonymous": s.anonymous, "audience": s.audience, "closes": _iso(s.closes),
             "questions": s.questions, **{k: v for k, v in hr.survey_results(db, s).items() if k in ("responses", "invited", "response_rate")}}
            for s in db.scalars(select(Survey).order_by(Survey.created_at.desc()))]


@router.post("/surveys")
def add_survey(body: SurveyIn, db: Session = Depends(get_db), _: User = Depends(current_user)):
    qs = body.questions or [hr.ENPS_QUESTION, {"key": "why", "label": "What's the main reason for your score?", "type": "text"},
                            {"key": "better", "label": "One thing we could do better", "type": "text"}]
    for i, q in enumerate(qs):
        q.setdefault("key", f"q{i + 1}")
        q.setdefault("type", "text")
    s = Survey(title=body.title, questions=qs, anonymous=body.anonymous, audience=body.audience, closes=body.closes)
    db.add(s)
    db.flush()
    n = hr.open_survey(db, s)
    db.commit()
    return {"id": s.id, "invited": n}


@router.get("/surveys/{survey_id}")
def survey_results(survey_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    return hr.survey_results(db, get_or_404(db, Survey, survey_id))


@router.put("/surveys/{survey_id}/status")
def survey_status(survey_id: int, status: str, db: Session = Depends(get_db), _: User = Depends(current_user)):
    s = get_or_404(db, Survey, survey_id)
    if status not in ("open", "closed"):
        raise HTTPException(422, "open or closed")
    s.status = status
    db.commit()
    return {"id": s.id, "status": s.status}


# --- hiring ---
class OpeningIn(BaseModel):
    title: str = Field(min_length=1)
    department: str = ""
    employment_type: str = "full_time"
    location: str = "Sunshine Coast"
    pay: str = ""
    description: str = ""
    questions: list[dict] = []
    status: str = Field(default="open", pattern="^(draft|open|closed)$")
    hiring_manager_id: int | None = None


def opening_out(db: Session, o: JobOpening) -> dict:
    counts = dict(db.execute(select(Candidate.stage, func.count()).where(Candidate.opening_id == o.id).group_by(Candidate.stage)).all())
    return {"id": o.id, "title": o.title, "department": o.department, "employment_type": o.employment_type, "location": o.location,
            "pay": o.pay, "description": o.description, "questions": o.questions, "status": o.status,
            "hiring_manager_id": o.hiring_manager_id, "candidates": sum(counts.values()), "by_stage": counts,
            "created_at": _iso(o.created_at)}


@router.get("/openings")
def list_openings(db: Session = Depends(get_db), _: User = Depends(current_user)):
    return [opening_out(db, o) for o in db.scalars(select(JobOpening).order_by(JobOpening.status, JobOpening.created_at.desc()))]


@router.post("/openings")
def add_opening(body: OpeningIn, db: Session = Depends(get_db), _: User = Depends(current_user)):
    o = JobOpening(**body.model_dump())
    db.add(o)
    db.commit()
    return opening_out(db, o)


@router.put("/openings/{opening_id}")
def edit_opening(opening_id: int, body: OpeningIn, db: Session = Depends(get_db), _: User = Depends(current_user)):
    o = get_or_404(db, JobOpening, opening_id)
    for k, v in body.model_dump().items():
        setattr(o, k, v)
    db.commit()
    return opening_out(db, o)


def candidate_out(db: Session, c: Candidate, notes: bool = False) -> dict:
    o = db.get(JobOpening, c.opening_id) if c.opening_id else None
    out = {"id": c.id, "opening_id": c.opening_id, "opening": o.title if o else "", "name": c.name, "email": c.email, "phone": c.phone,
           "stage": c.stage, "rating": c.rating, "source": c.source, "answers": c.answers, "cover_note": c.cover_note,
           "has_resume": bool(c.resume_key), "resume_name": c.resume_name, "hired_user_id": c.hired_user_id, "created_at": _iso(c.created_at)}
    if notes:
        names = _names(db)
        out["notes"] = [{"id": n.id, "by": names.get(n.user_id or 0, ""), "text": n.text, "at": _iso(n.created_at)}
                        for n in db.scalars(select(CandidateNote).where(CandidateNote.candidate_id == c.id).order_by(CandidateNote.created_at))]
    return out


@router.get("/candidates")
def list_candidates(opening_id: int | None = None, db: Session = Depends(get_db), _: User = Depends(current_user)):
    stmt = select(Candidate).order_by(Candidate.created_at.desc())
    if opening_id:
        stmt = stmt.where(Candidate.opening_id == opening_id)
    return [candidate_out(db, c) for c in db.scalars(stmt)]


class CandidateIn(BaseModel):
    opening_id: int | None = None
    name: str = Field(min_length=1)
    email: str = ""
    phone: str = ""
    source: str = "referral"
    cover_note: str = ""


@router.post("/candidates")
def add_candidate(body: CandidateIn, db: Session = Depends(get_db), _: User = Depends(current_user)):
    c = Candidate(**body.model_dump())
    db.add(c)
    db.commit()
    return candidate_out(db, c)


@router.get("/candidates/{cand_id}")
def candidate(cand_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    return candidate_out(db, get_or_404(db, Candidate, cand_id), True)


class CandidatePatch(BaseModel):
    stage: str | None = None
    rating: int | None = Field(default=None, ge=1, le=5)
    opening_id: int | None = None
    note: str | None = None


@router.patch("/candidates/{cand_id}")
def edit_candidate(cand_id: int, body: CandidatePatch, db: Session = Depends(get_db), user: User = Depends(current_user)):
    c = get_or_404(db, Candidate, cand_id)
    data = body.model_dump(exclude_unset=True)
    if "stage" in data:
        if data["stage"] not in hr.STAGES or data["stage"] == "hired":
            raise HTTPException(422, "Use Hire to hire someone")
        c.stage = data["stage"]
    if "rating" in data:
        c.rating = data["rating"]
    if "opening_id" in data:
        c.opening_id = data["opening_id"]
    if data.get("note"):
        db.add(CandidateNote(candidate_id=c.id, user_id=user.id, text=data["note"]))
    db.commit()
    return candidate_out(db, c, True)


@router.get("/candidates/{cand_id}/resume")
def resume(cand_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    c = get_or_404(db, Candidate, cand_id)
    return _send(c.resume_key, c.resume_name)


class HireIn(BaseModel):
    email: str = ""
    role: str = "field"
    trade: str = ""
    start: date | None = None
    checklist_id: int | None = None


@router.post("/candidates/{cand_id}/hire")
def hire(cand_id: int, body: HireIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    c = get_or_404(db, Candidate, cand_id)
    if c.hired_user_id:
        raise HTTPException(409, "Already hired")
    email = (body.email or c.email).strip().lower()
    if not email:
        raise HTTPException(422, "They need an email to sign in with")
    if body.role not in ROLES or body.role == "admin":
        raise HTTPException(422, "Pick field, estimator or reviewer")
    if db.scalar(select(User).where(func.lower(User.email) == email)):
        raise HTTPException(409, "Someone already signs in with that email")
    u = hr.hire(db, c, email=email, role=body.role, trade=body.trade, start=body.start, by=user, checklist_id=body.checklist_id)
    record(db, user.id, "employee", u.id, "hire", after={"candidate": c.id, "email": email})
    db.commit()
    return {"user_id": u.id, "note": "Set their password in Admin → Users (or reset it there) before their first day."}


# --- announcements ---
class AnnouncementIn(BaseModel):
    title: str = Field(min_length=1)
    body: str = ""
    audience: str = Field(default="all", pattern="^(all|field|office)$")
    pinned: bool = False
    expires: date | None = None
    notify: bool = True


@router.get("/announcements")
def list_announcements(db: Session = Depends(get_db), _: User = Depends(current_user)):
    return [{"id": a.id, "title": a.title, "body": a.body, "audience": a.audience, "pinned": a.pinned, "expires": _iso(a.expires),
             "at": _iso(a.created_at)} for a in db.scalars(select(Announcement).order_by(Announcement.created_at.desc()))]


@router.post("/announcements")
def add_announcement(body: AnnouncementIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    a = Announcement(created_by=user.id, **body.model_dump(exclude={"notify"}))
    db.add(a)
    db.flush()
    if body.notify:
        for u, _p in _staff(db):
            if hr.audience_ok(a.audience, u) and u.id != user.id:
                notify(db, u.id, "news", a.title, "/field/me", key=f"news-{a.id}-{u.id}")
    db.commit()
    return {"id": a.id}


@router.delete("/announcements/{ann_id}", status_code=204)
def delete_announcement(ann_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    db.delete(get_or_404(db, Announcement, ann_id))
    db.commit()


# (last, so /api/people/<word> routes above aren't taken for a person id)
@router.get("/{user_id}")
def person(user_id: int, db: Session = Depends(get_db), viewer: User = Depends(current_user)):
    from .. import features

    u = get_or_404(db, User, user_id)
    see_pay = features.level(db, viewer, "hr_pay") != "none"
    p = hr.profile(db, u.id)
    names = _names(db)
    db.commit()
    warn = hr.settings(db)["warn_days"]
    pays = list(db.scalars(select(PayChange).where(PayChange.user_id == u.id).order_by(PayChange.effective.desc(), PayChange.id.desc()))) if see_pay else []
    cycles = {c.id: c for c in db.scalars(select(ReviewCycle))}
    signed = list(db.scalars(select(PolicySignature).where(PolicySignature.user_id == u.id)))
    policies = {x.id: x for x in db.scalars(select(Policy))}
    return {
        "profile": profile_out(db, u, p, names),
        "pay": [{"id": x.id, "effective": _iso(x.effective), "pay_type": x.pay_type, "amount": x.amount, "position": x.position,
                 "reason": x.reason, "notes": x.notes, "by": names.get(x.created_by or 0, "")} for x in pays],
        "hourly_rate": hr.hourly_rate(db, u.id, p) if see_pay else None, "cost_rate": u.cost_rate if see_pay else None, "see_pay": see_pay,
        "compliance": hr.compliance(db, u), "warn_days": warn,
        "leave": [b if see_pay else {**b, "value": None} for b in hr.balances(db, u)],
        "time_off": [{"id": t.id, "kind": t.kind, "start_date": _iso(t.start_date), "end_date": _iso(t.end_date),
                      "hours": round(hr.leave_days_hours(t, p), 2), "status": t.status, "notes": t.notes}
                     for t in db.scalars(select(TimeOff).where(TimeOff.user_id == u.id).order_by(TimeOff.start_date.desc()))],
        "adjustments": [{"id": a.id, "kind": a.kind, "day": _iso(a.day), "hours": a.hours, "reason": a.reason}
                        for a in db.scalars(select(LeaveAdjustment).where(LeaveAdjustment.user_id == u.id).order_by(LeaveAdjustment.day))],
        "files": [{"id": f.id, "folder": f.folder, "filename": f.filename, "size": f.size, "employee_can_see": f.employee_can_see,
                   "created_at": _iso(f.created_at)}
                  for f in db.scalars(select(EmployeeFile).where(EmployeeFile.user_id == u.id).order_by(EmployeeFile.folder, EmployeeFile.filename))],
        "gear": [{"id": i.id, "item": i.item, "serial": i.serial, "value": i.value, "issued": _iso(i.issued), "returned": _iso(i.returned),
                  "notes": i.notes} for i in db.scalars(select(IssuedItem).where(IssuedItem.user_id == u.id).order_by(IssuedItem.issued))],
        "tasks": [hr.task_out(db, t, names) for t in db.scalars(select(ChecklistTask).where(ChecklistTask.user_id == u.id)
                                                                 .order_by(ChecklistTask.kind, ChecklistTask.position))],
        "reviews": [{"id": r.id, "cycle": cycles[r.cycle_id].name if r.cycle_id in cycles else "", "reviewer": names.get(r.reviewer_id or 0, ""),
                     "self_done": r.self_done_at is not None, "manager_done": r.manager_done_at is not None,
                     "shared": r.shared_at is not None, "overall": r.overall}
                    for r in db.scalars(select(Review).where(Review.user_id == u.id).order_by(Review.id.desc()))],
        "goals": [goal_out(g) for g in db.scalars(select(Goal).where(Goal.user_id == u.id).order_by(Goal.status, Goal.due))],
        "signed": [{"policy": policies[s.policy_id].title if s.policy_id in policies else "", "version": s.version,
                    "signed_at": _iso(s.signed_at), "typed_name": s.typed_name} for s in signed],
        "to_sign": [{"id": x.id, "title": x.title} for x in hr.policies_to_sign(db, u)],
    }


# ============ everyone's own side ============
@me.get("")
def my_record(db: Session = Depends(get_db), user: User = Depends(current_user)):
    p = hr.profile(db, user.id)
    db.commit()
    pay = hr.current_pay(db, user.id)
    return {"profile": {**{f: _iso(getattr(p, f)) for f in SELF_FIELDS + ["position", "department", "employment_type", "start_date",
                                                                         "hours_per_week"]},
                        "name": user.name or user.email, "email": user.email, "phone": user.phone, "has_photo": bool(p.photo_key),
                        "manager": _names(db).get(p.manager_id or 0, ""), "years_of_service": round(hr.years_of_service(p), 1)},
            "pay": {"effective": _iso(pay.effective), "pay_type": pay.pay_type, "amount": pay.amount} if pay else None,
            "leave": hr.balances(db, user),
            "compliance": hr.compliance(db, user),
            "credential_types": [{"id": t.id, "name": t.name, "category": t.category}
                                 for t in db.scalars(select(CredentialType).where(CredentialType.active.is_(True)).order_by(CredentialType.name))],
            "files": [{"id": f.id, "folder": f.folder, "filename": f.filename}
                      for f in db.scalars(select(EmployeeFile).where(EmployeeFile.user_id == user.id, EmployeeFile.employee_can_see.is_(True)))],
            "gear": [{"item": g.item, "serial": g.serial, "issued": _iso(g.issued)}
                     for g in db.scalars(select(IssuedItem).where(IssuedItem.user_id == user.id, IssuedItem.returned.is_(None)))],
            "reviews_shared": [review_out(db, r, False) for r in db.scalars(select(Review).where(Review.user_id == user.id,
                                                                                                 Review.shared_at.is_not(None)))],
            **hr.my_hr(db, user)}


class SelfIn(BaseModel):
    phone: str | None = None
    personal_email: str = ""
    address: str = ""
    emergency_contacts: list[dict] = []
    drivers_licence: str = ""
    shirt_size: str = ""
    pants_size: str = ""
    boot_size: str = ""
    medical_notes: str = ""
    dob: date | None = None


@me.put("/profile")
def my_profile(body: SelfIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    p = hr.profile(db, user.id)
    for f in SELF_FIELDS:
        setattr(p, f, getattr(body, f))
    if body.phone is not None:
        user.phone = body.phone
    db.commit()
    return {"ok": True}


@me.post("/photo")
async def my_photo(file: UploadFile = File(...), db: Session = Depends(get_db), user: User = Depends(current_user)):
    data = await _read(file)
    p = hr.profile(db, user.id)
    if p.photo_key:
        storage.delete(p.photo_key)
    p.photo_key = hr.save_file(f"{user.id}/photo", file.filename or "photo.jpg", data)
    db.commit()
    return {"ok": True}


@me.get("/photo/{user_id}")
def photo(user_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    p = db.scalar(select(EmployeeProfile).where(EmployeeProfile.user_id == user_id))
    if not p or not p.photo_key:
        raise HTTPException(404, "No photo")
    return Response(storage.read_bytes(p.photo_key), media_type=mimetypes.guess_type(p.photo_key)[0] or "image/jpeg",
                    headers={"Cache-Control": "private, max-age=300"})


@me.post("/credentials")
async def my_credential(type_id: int = Form(...), number: str = Form(""), issuer: str = Form(""), issued: str = Form(""),
                        expires: str = Form(""), file: UploadFile | None = File(None), db: Session = Depends(get_db),
                        user: User = Depends(current_user)):
    """Upload a photo of a licence or ticket. The office checks it (verified) after."""
    c = await _credential(db, user.id, type_id, number, issuer, issued, expires, "", "", "", file, user, False)
    t = db.get(CredentialType, type_id)
    hr.notify_hr(db, "licence", f"{user.name or user.email} uploaded {t.name if t else 'a licence'} – check it.", f"/people/{user.id}",
                 key=f"cred-new-{c.id}")
    now = datetime.now(timezone.utc)
    for task in db.scalars(select(ChecklistTask).where(ChecklistTask.user_id == user.id, ChecklistTask.done_at.is_(None),
                                                       ChecklistTask.title.ilike("%licence%"))):
        task.done_at, task.done_by = now, user.id
    db.commit()
    return hr.credential_out(c, t, hr.settings(db)["warn_days"])


@me.get("/credentials/{cred_id}/file")
def my_credential_file(cred_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    c = get_or_404(db, Credential, cred_id)
    if c.user_id != user.id:
        raise HTTPException(404, "Not found")
    return _send(c.file_key, c.file_name)


@me.get("/files/{file_id}")
def my_file(file_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    f = get_or_404(db, EmployeeFile, file_id)
    if f.user_id != user.id or not f.employee_can_see:
        raise HTTPException(404, "Not found")
    return _send(f.key, f.filename)


@me.get("/leave/projected")
def my_projection(on: date, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return hr.projected(db, user, on)


@me.get("/policies/{policy_id}")
def read_policy(policy_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    p = get_or_404(db, Policy, policy_id)
    s = db.scalar(select(PolicySignature).where(PolicySignature.policy_id == p.id, PolicySignature.user_id == user.id,
                                                PolicySignature.version == p.version))
    return {"id": p.id, "title": p.title, "body": p.body, "has_file": bool(p.file_key), "file_name": p.file_name, "version": p.version,
            "signed_at": _iso(s.signed_at) if s else None}


@me.get("/policies/{policy_id}/file")
def policy_file(policy_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    p = get_or_404(db, Policy, policy_id)
    return _send(p.file_key, p.file_name)


class SignIn(BaseModel):
    typed_name: str = Field(min_length=2, max_length=200)
    signature: str = Field(default="", max_length=400_000)
    agree: bool


@me.post("/policies/{policy_id}/sign")
def sign(policy_id: int, body: SignIn, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if not body.agree:
        raise HTTPException(422, "Tick that you've read it")
    p = get_or_404(db, Policy, policy_id)
    s = hr.sign_policy(db, p, user, body.typed_name, body.signature, request.client.host if request.client else "")
    db.commit()
    return {"signed_at": _iso(s.signed_at), "version": s.version}


@me.get("/reviews/{review_id}")
def my_review(review_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    r = get_or_404(db, Review, review_id)
    if user.id not in (r.user_id, r.reviewer_id):
        raise HTTPException(404, "Not found")
    return {**review_out(db, r, user.id == r.reviewer_id), "as": "manager" if user.id == r.reviewer_id else "self"}


class ReviewAnswers(BaseModel):
    answers: dict
    submit: bool = True


@me.put("/reviews/{review_id}")
def answer_review(review_id: int, body: ReviewAnswers, db: Session = Depends(get_db), user: User = Depends(current_user)):
    r = get_or_404(db, Review, review_id)
    c = db.get(ReviewCycle, r.cycle_id)
    if c is None or c.status != "open":
        raise HTTPException(409, "This review is closed")
    now = datetime.now(timezone.utc) if body.submit else None
    if user.id == r.reviewer_id:
        r.manager_answers = body.answers
        r.manager_done_at = now
        r.overall = hr.overall_of(body.answers, c.questions)
    elif user.id == r.user_id:
        if r.self_done_at and body.submit is False:
            raise HTTPException(409, "Already sent")
        r.self_answers = body.answers
        r.self_done_at = now
        if now and r.reviewer_id:
            notify(db, r.reviewer_id, "review", f"{user.name or user.email} has done their side of the review.", "/my-work",
                   key=f"rv-selfdone-{r.id}")
    else:
        raise HTTPException(404, "Not found")
    db.commit()
    return {"ok": True}


@me.put("/goals/{goal_id}")
def my_goal(goal_id: int, progress: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    g = get_or_404(db, Goal, goal_id)
    if g.user_id != user.id:
        raise HTTPException(404, "Not found")
    g.progress = max(0, min(100, progress))
    if g.progress == 100:
        g.status = "done"
    db.commit()
    return goal_out(g)


@me.get("/surveys/{survey_id}")
def my_survey(survey_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    s = get_or_404(db, Survey, survey_id)
    inv = db.scalar(select(SurveyInvite).where(SurveyInvite.survey_id == s.id, SurveyInvite.user_id == user.id))
    if inv is None:
        raise HTTPException(404, "Not found")
    return {"id": s.id, "title": s.title, "questions": s.questions, "anonymous": s.anonymous, "answered": inv.answered,
            "open": s.status == "open"}


@me.post("/surveys/{survey_id}")
def answer_survey(survey_id: int, body: dict, db: Session = Depends(get_db), user: User = Depends(current_user)):
    s = get_or_404(db, Survey, survey_id)
    inv = db.scalar(select(SurveyInvite).where(SurveyInvite.survey_id == s.id, SurveyInvite.user_id == user.id))
    if inv is None:
        raise HTTPException(404, "Not found")
    if inv.answered:
        raise HTTPException(409, "You've already answered this one. Thanks!")
    if s.status != "open":
        raise HTTPException(409, "This survey has closed")
    answers = {}
    for q in s.questions or []:
        v = (body.get("answers") or {}).get(q["key"])
        if v in (None, ""):
            continue
        if q.get("type") == "enps":
            v = int(v)
            if not 0 <= v <= 10:
                raise HTTPException(422, "0 to 10")
        elif q.get("type") == "rating":
            v = int(v)
            if not 1 <= v <= 5:
                raise HTTPException(422, "1 to 5")
        else:
            v = str(v)[:2000]
        answers[q["key"]] = v
    p = hr.profile(db, user.id)
    db.add(SurveyResponse(survey_id=s.id, user_id=None if s.anonymous else user.id, department=p.department or "",
                          answers=answers, month=hr.today_local().strftime("%Y-%m")))
    inv.answered = True
    db.commit()
    return {"ok": True}


@me.put("/tasks/{task_id}")
def my_task(task_id: int, body: TaskIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    t = get_or_404(db, ChecklistTask, task_id)
    if t.assignee_id != user.id:
        raise HTTPException(404, "Not found")
    return _task_update(db, t, TaskIn(done=body.done), user)


@me.get("/directory")
def directory(db: Session = Depends(get_db), _: User = Depends(current_user)):
    """Everyone's work contact details and who they report to (the org chart)."""
    names = _names(db)
    return [directory_row(u, p, names) for u, p in _staff(db)]


@me.get("/new-password")
def suggest_password(_: User = Depends(current_user)):
    return {"password": secrets.token_urlsafe(9)}


# ============ public careers page ============
@public.get("")
def careers(db: Session = Depends(get_db)):
    from .. import ops

    return {"company": ops.settings(db)["company_name"],
            "openings": [{"id": o.id, "title": o.title, "department": o.department, "employment_type": o.employment_type,
                          "location": o.location, "pay": o.pay, "description": o.description, "questions": o.questions}
                         for o in db.scalars(select(JobOpening).where(JobOpening.status == "open").order_by(JobOpening.created_at.desc()))]}


@public.post("/{opening_id}")
async def apply(opening_id: int, name: str = Form(..., min_length=2, max_length=200), email: str = Form(..., max_length=255),
                phone: str = Form("", max_length=50), cover_note: str = Form("", max_length=5000), answers: str = Form("{}"),
                website: str = Form(""), resume: UploadFile | None = File(None), db: Session = Depends(get_db)):
    o = db.get(JobOpening, opening_id)
    if o is None or o.status != "open":
        raise HTTPException(404, "That job isn't open any more")
    if website:  # hidden field: only bots fill it in
        return {"ok": True}
    if "@" not in email:
        raise HTTPException(422, "Check your email address")
    try:
        ans = {str(k)[:40]: str(v)[:2000] for k, v in (json.loads(answers or "{}") or {}).items()}
    except (ValueError, AttributeError):
        ans = {}
    c = Candidate(opening_id=o.id, name=name.strip(), email=email.strip(), phone=phone.strip(), cover_note=cover_note, answers=ans)
    if resume is not None and resume.filename:
        data = await _read(resume)
        c.resume_key, c.resume_name = hr.save_file("candidates", resume.filename, data), resume.filename
    db.add(c)
    db.flush()
    hr.notify_hr(db, "hiring", f"New application for {o.title}: {c.name}", "/people?tab=hiring", key=f"cand-{c.id}")
    if o.hiring_manager_id:
        notify(db, o.hiring_manager_id, "hiring", f"New application for {o.title}: {c.name}", "/people?tab=hiring", key=f"cand-{c.id}-m")
    db.commit()
    return {"ok": True}
