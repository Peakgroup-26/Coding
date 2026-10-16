"""People: the BambooHR side. Profiles, pay history, licences and training, leave balances, onboarding and
offboarding, policies people sign, reviews and goals, staff surveys (eNPS), hiring, announcements and gear issued.

Leave balances are worked out from records, never typed in: opening balance and corrections (leave_adjustments)
+ what has built up + what has been taken (approved time off). Annual and personal leave build up with ordinary
hours worked (approved timesheets, capped at the person's normal week) and paid leave taken, as the NES does;
long service builds up with time. Xero Payroll stays the pay run; this is the running view for the office and the boys.
"""
import secrets
import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import ops, storage
from .finance import entry_hours
from .models import (Announcement, Candidate, ChecklistTask, ChecklistTemplate, Credential, CredentialType, EmployeeProfile,
                     IssuedItem, JobOpening, LeaveAdjustment, LeavePolicy, PayChange, Policy, PolicySignature,
                     Review, ReviewCycle, Survey, SurveyInvite, SurveyResponse, TimeEntry, TimeOff, User)
from .plant import notify
from .reports import holidays
from .timesheets import local_day

DEPARTMENTS = ["plumbing", "civil", "maintenance", "office", "management"]
EMPLOYMENT_TYPES = ["full_time", "part_time", "casual", "apprentice", "contractor"]
STAGES = ["applied", "screen", "interview", "offer", "hired", "rejected"]
PAID_LEAVE = {"annual", "sick", "long_service", "rdo", "other"}  # counts as ordinary hours for accrual
STANDARD_WEEK = 38.0

DEFAULT_POLICIES = [
    # kind, name, hours per year (38 h week), accrues on hours worked, usable after years, casuals
    ("annual", "Annual leave", 152.0, True, 0.0, False),
    ("sick", "Personal / carer's leave", 76.0, True, 0.0, False),
    ("long_service", "Long service leave", 8.667 * STANDARD_WEEK / 10, False, 7.0, True),  # 8.667 weeks per 10 years (Qld)
    ("rdo", "RDO", 0.0, True, 0.0, False),
]
DEFAULT_CREDENTIALS = [
    ("White card (general construction induction)", "induction", None, ["*"]),
    ("Plumbing licence (QBCC)", "licence", 12, ["plumber", "supervisor"]),
    ("Drainage licence (QBCC)", "licence", 12, []),
    ("Gasfitting licence (QBCC)", "licence", 12, []),
    ("Driver licence", "licence", None, ["*"]),
    ("First aid (HLTAID011)", "training", 36, ["supervisor"]),
    ("CPR (HLTAID009)", "training", 12, []),
    ("Confined space entry", "ticket", 24, []),
    ("Working at heights", "ticket", 24, []),
    ("Asbestos awareness", "training", None, []),
    ("Excavator ticket / VOC", "ticket", None, []),
    ("Backflow prevention accreditation", "licence", 12, []),
    ("Site induction", "induction", None, []),
]
DEFAULT_CHECKLISTS = [
    ("New starter", "onboarding", [
        {"title": "Send the welcome email and first-day details", "who": "hr", "due_days": -3},
        {"title": "Set up their sign-in for the phone app", "who": "hr", "due_days": -1},
        {"title": "Order uniform and PPE (check sizes on their profile)", "who": "hr", "due_days": -5},
        {"title": "Fill in personal details and emergency contacts", "who": "employee", "due_days": 0},
        {"title": "Upload white card and licences", "who": "employee", "due_days": 0},
        {"title": "Sign the company policies", "who": "employee", "due_days": 1},
        {"title": "Tax file number and super choice forms (in Xero)", "who": "hr", "due_days": 1},
        {"title": "Issue van, tools, phone and fuel card", "who": "manager", "due_days": 0},
        {"title": "Site induction and SWMS walk-through", "who": "manager", "due_days": 1},
        {"title": "Two-week check-in", "who": "manager", "due_days": 14},
        {"title": "Three-month probation review", "who": "manager", "due_days": 90},
    ]),
    ("Leaver", "offboarding", [
        {"title": "Confirm last day and final pay in Xero", "who": "hr", "due_days": 0},
        {"title": "Collect van, tools, phone, keys and fuel card", "who": "manager", "due_days": 0},
        {"title": "Turn off their sign-in", "who": "hr", "due_days": 0},
        {"title": "Exit interview", "who": "hr", "due_days": -1},
    ]),
]
DEFAULT_REVIEW_QUESTIONS = [
    {"key": "quality", "label": "Quality of work", "type": "rating"},
    {"key": "safety", "label": "Safety and following SWMS", "type": "rating"},
    {"key": "customers", "label": "Dealing with customers and builders", "type": "rating"},
    {"key": "teamwork", "label": "Teamwork and reliability", "type": "rating"},
    {"key": "wins", "label": "What went well this year?", "type": "text"},
    {"key": "improve", "label": "What could be better?", "type": "text"},
    {"key": "next", "label": "Training or goals for next year", "type": "text"},
]
ENPS_QUESTION = {"key": "enps", "label": "How likely are you to recommend Peak as a place to work? (0-10)", "type": "enps"}


def seed(db: Session) -> None:
    if not db.scalar(select(LeavePolicy.id).limit(1)):
        for kind, name, hpy, on_hours, after, casuals in DEFAULT_POLICIES:
            db.add(LeavePolicy(kind=kind, name=name, hours_per_year=round(hpy, 2), accrues_on_hours=on_hours, after_years=after,
                               casuals=casuals))
    if not db.scalar(select(CredentialType.id).limit(1)):
        for name, cat, months, req in DEFAULT_CREDENTIALS:
            db.add(CredentialType(name=name, category=cat, renew_months=months, required_for=req))
    if not db.scalar(select(ChecklistTemplate.id).limit(1)):
        for name, kind, tasks in DEFAULT_CHECKLISTS:
            db.add(ChecklistTemplate(name=name, kind=kind, tasks=tasks))
    db.flush()


def settings(db: Session) -> dict:
    s = ops.settings(db)
    return {"oncost_pct": float(s.get("hr_oncost_pct", 25.0)), "warn_days": int(s.get("credential_warn_days", 60)),
            "tracking_from": s.get("leave_tracking_from") or ""}


def today_local() -> date:
    return local_day(datetime.now(timezone.utc))


def profile(db: Session, user_id: int) -> EmployeeProfile:
    p = db.scalar(select(EmployeeProfile).where(EmployeeProfile.user_id == user_id))
    if p is None:
        p = EmployeeProfile(user_id=user_id, emergency_contacts=[])
        db.add(p)
        db.flush()
    return p


def hr_people(db: Session) -> list[User]:
    return list(db.scalars(select(User).where(User.active.is_(True), (User.role == "admin") | User.can_hr.is_(True))))


def notify_hr(db: Session, kind: str, text: str, link: str, key: str) -> None:
    for u in hr_people(db):
        notify(db, u.id, kind, text, link, key=f"{key}-{u.id}")


def save_file(prefix: str, name: str, data: bytes) -> str:
    key = f"people/{prefix}/{uuid.uuid4().hex}-{''.join(c if c.isalnum() or c in '.-_' else '_' for c in name)[:120]}"
    storage.save_bytes(key, data)
    return key


# --- service and pay ---
def years_of_service(p: EmployeeProfile, on: date | None = None) -> float:
    if not p.start_date:
        return 0.0
    end = p.end_date or on or today_local()
    return max(0.0, (end - p.start_date).days / 365.25)


def current_pay(db: Session, user_id: int, on: date | None = None) -> PayChange | None:
    on = on or today_local()
    return db.scalar(select(PayChange).where(PayChange.user_id == user_id, PayChange.effective <= on)
                     .order_by(PayChange.effective.desc(), PayChange.id.desc()).limit(1))


def hourly_rate(db: Session, user_id: int, p: EmployeeProfile | None = None) -> float | None:
    pay = current_pay(db, user_id)
    if pay is None:
        return None
    if pay.pay_type == "hourly":
        return pay.amount
    week = (p.hours_per_week if p else None) or STANDARD_WEEK
    return pay.amount / 52 / week


# --- credentials ---
def credential_status(c: Credential, warn_days: int, today: date | None = None) -> str:
    today = today or today_local()
    if c.expires is None:
        return "current"
    if c.expires < today:
        return "expired"
    if c.expires <= today + timedelta(days=warn_days):
        return "expiring"
    return "current"


def required_types(db: Session, user: User) -> list[CredentialType]:
    trade = (user.trade or "").lower()
    out = []
    for t in db.scalars(select(CredentialType).where(CredentialType.active.is_(True))):
        req = [r.lower() for r in (t.required_for or [])]
        if "*" in req and (user.role == "field" or trade not in ("", "office", "manager")):
            out.append(t)
        elif trade and trade in req:
            out.append(t)
    return out


def compliance(db: Session, user: User, today: date | None = None) -> dict:
    """What a person holds, what's expiring and what's missing that their trade needs."""
    today = today or today_local()
    warn = settings(db)["warn_days"]
    types = {t.id: t for t in db.scalars(select(CredentialType))}
    held = list(db.scalars(select(Credential).where(Credential.user_id == user.id).order_by(Credential.expires)))
    rows = [credential_out(c, types.get(c.type_id), warn, today) for c in held]
    best: dict[int, str] = {}
    rank = {"current": 3, "expiring": 2, "expired": 1}
    for r in rows:
        if rank[r["status"]] > rank.get(best.get(r["type_id"], ""), 0):
            best[r["type_id"]] = r["status"]
    missing = [t.name for t in required_types(db, user) if best.get(t.id) not in ("current", "expiring")]
    return {"credentials": rows, "missing": missing,
            "expired": sum(1 for r in rows if r["status"] == "expired" and best.get(r["type_id"]) == "expired"),
            "expiring": sum(1 for r in rows if r["status"] == "expiring" and best.get(r["type_id"]) == "expiring")}


def credential_out(c: Credential, t: CredentialType | None, warn: int, today: date | None = None) -> dict:
    return {"id": c.id, "user_id": c.user_id, "type_id": c.type_id, "type": t.name if t else "", "category": t.category if t else "",
            "number": c.number, "issuer": c.issuer, "issued": _iso(c.issued), "expires": _iso(c.expires), "hours": c.hours,
            "cost": c.cost, "has_file": bool(c.file_key), "file_name": c.file_name, "verified": c.verified_at is not None,
            "notes": c.notes, "status": credential_status(c, warn, today)}


def default_expiry(db: Session, type_id: int, issued: date | None) -> date | None:
    t = db.get(CredentialType, type_id)
    if not t or not t.renew_months or not issued:
        return None
    m = issued.month - 1 + t.renew_months
    y = issued.year + m // 12
    m = m % 12 + 1
    d = min(issued.day, [31, 29 if y % 4 == 0 and (y % 100 or y % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1])
    return date(y, m, d)


# --- leave ---
def leave_days_hours(t: TimeOff, p: EmployeeProfile) -> float:
    """Hours a time-off request takes: as entered, else working days (no weekends or Qld public holidays) x a normal day."""
    if t.hours is not None:
        return float(t.hours)
    day_hours = (p.hours_per_week or STANDARD_WEEK) / 5
    d, n = t.start_date, 0
    while d <= t.end_date:
        if d.weekday() < 5 and d not in holidays(d.year):
            n += 1
        d += timedelta(days=1)
    return n * day_hours


def _ordinary_hours(db: Session, user_id: int, p: EmployeeProfile, since: date | None, until: date) -> float:
    """Approved hours worked plus paid leave, capped at the person's normal week, since a date."""
    week_cap = p.hours_per_week or STANDARD_WEEK
    by_week: dict[date, float] = defaultdict(float)
    stmt = select(TimeEntry).where(TimeEntry.user_id == user_id, TimeEntry.status == "approved", TimeEntry.end_at.is_not(None))
    for e in db.scalars(stmt):
        d = local_day(e.start_at)
        if (since and d < since) or d > until:
            continue
        by_week[d - timedelta(days=d.weekday())] += entry_hours(e)
    for t in db.scalars(select(TimeOff).where(TimeOff.user_id == user_id, TimeOff.status == "approved", TimeOff.kind.in_(PAID_LEAVE))):
        if (since and t.end_date < since) or t.start_date > until:
            continue
        by_week[t.start_date - timedelta(days=t.start_date.weekday())] += leave_days_hours(t, p)
    return sum(min(h, week_cap) for h in by_week.values())


def balances(db: Session, user: User, on: date | None = None) -> list[dict]:
    """Each kind of leave: opening + built up - taken = balance, with requests waiting and what it's worth."""
    on = on or today_local()
    p = profile(db, user.id)
    cfg = settings(db)
    since = None
    if cfg["tracking_from"]:
        try:
            since = date.fromisoformat(cfg["tracking_from"])
        except ValueError:
            since = None
    if p.start_date and (since is None or p.start_date > since):
        since = p.start_date
    casual = p.employment_type in ("casual", "contractor")
    worked = None
    rate = hourly_rate(db, user.id, p)
    out = []
    for pol in db.scalars(select(LeavePolicy).where(LeavePolicy.active.is_(True)).order_by(LeavePolicy.id)):
        if casual and not pol.casuals:
            continue
        per_hour = pol.hours_per_year / (52 * STANDARD_WEEK) if pol.hours_per_year else 0.0
        if pol.accrues_on_hours:
            if worked is None:
                worked = _ordinary_hours(db, user.id, p, since, on)
            accrued = worked * per_hour
        else:
            start = since or p.start_date
            years = max(0.0, (on - start).days / 365.25) if start else 0.0
            accrued = years * pol.hours_per_year * ((p.hours_per_week or STANDARD_WEEK) / STANDARD_WEEK)
        adj = sum(a.hours for a in db.scalars(select(LeaveAdjustment).where(LeaveAdjustment.user_id == user.id,
                                                                            LeaveAdjustment.kind == pol.kind, LeaveAdjustment.day <= on)))
        taken = pending = 0.0
        for t in db.scalars(select(TimeOff).where(TimeOff.user_id == user.id, TimeOff.kind == pol.kind, TimeOff.status != "declined")):
            if since and t.end_date < since:
                continue
            h = leave_days_hours(t, p)
            if t.status == "approved" and t.start_date <= on:
                taken += h
            elif t.status == "approved":
                pending += h  # booked for later
            else:
                pending += h
        bal = adj + accrued - taken
        available = years_of_service(p, on) >= pol.after_years
        out.append({"kind": pol.kind, "name": pol.name, "opening_and_adjustments": round(adj, 2), "accrued": round(accrued, 2),
                    "taken": round(taken, 2), "balance": round(bal, 2), "booked_or_requested": round(pending, 2),
                    "after_bookings": round(bal - pending, 2), "available": available,
                    "days": round(bal / ((p.hours_per_week or STANDARD_WEEK) / 5), 1),
                    "value": round(bal * rate, 2) if rate else None,
                    "per_week": round((p.hours_per_week or STANDARD_WEEK) * per_hour, 3) if pol.accrues_on_hours else
                    round(pol.hours_per_year * ((p.hours_per_week or STANDARD_WEEK) / STANDARD_WEEK) / 52, 3)})
    return out


def projected(db: Session, user: User, on: date) -> list[dict]:
    """Balance on a future date, assuming a normal week every week until then (for 'can I take 3 weeks at Christmas?')."""
    today = today_local()
    now = balances(db, user, today)
    weeks = max(0.0, (on - today).days / 7)
    for b in now:
        b["projected"] = round(b["balance"] + b["per_week"] * weeks - b["booked_or_requested"], 2)
        b["on"] = on.isoformat()
    return now


# --- onboarding / offboarding ---
def start_checklist(db: Session, user: User, template: ChecklistTemplate, start: date, by: User | None) -> list[ChecklistTask]:
    p = profile(db, user.id)
    out = []
    for i, t in enumerate(template.tasks or []):
        who = t.get("who", "hr")
        assignee = user.id if who == "employee" else (p.manager_id if who == "manager" else None)
        task = ChecklistTask(user_id=user.id, kind=template.kind, template_id=template.id, title=t["title"], who=who,
                             assignee_id=assignee, due=start + timedelta(days=int(t.get("due_days", 0))),
                             policy_id=t.get("policy_id"), position=i)
        db.add(task)
        out.append(task)
    db.flush()
    name = user.name or user.email
    for task in out:
        if task.assignee_id and task.assignee_id != (by.id if by else None):
            notify(db, task.assignee_id, "hr", f"{template.name} for {name}: {task.title}", "/my-work", key=f"cl-{task.id}")
    return out


def task_out(db: Session, t: ChecklistTask, names: dict[int, str] | None = None) -> dict:
    names = names or {}
    return {"id": t.id, "user_id": t.user_id, "person": names.get(t.user_id, ""), "kind": t.kind, "title": t.title, "who": t.who,
            "assignee_id": t.assignee_id, "assignee": names.get(t.assignee_id or 0, ""), "due": _iso(t.due),
            "done": t.done_at is not None, "done_at": t.done_at.isoformat() if t.done_at else None, "policy_id": t.policy_id,
            "overdue": t.done_at is None and t.due is not None and t.due < today_local()}


# --- policies ---
def audience_ok(audience: str, user: User) -> bool:
    if audience == "all":
        return True
    if audience == "field":
        return user.role == "field"
    if audience == "office":
        return user.role != "field"
    return False


def policies_to_sign(db: Session, user: User) -> list[Policy]:
    signed = {(s.policy_id, s.version) for s in db.scalars(select(PolicySignature).where(PolicySignature.user_id == user.id))}
    sent = set(db.scalars(select(ChecklistTask.policy_id).where(ChecklistTask.user_id == user.id, ChecklistTask.policy_id.is_not(None))))
    return [p for p in db.scalars(select(Policy).where(Policy.active.is_(True)).order_by(Policy.title))
            if (audience_ok(p.audience, user) or p.id in sent) and (p.id, p.version) not in signed]


def sign_policy(db: Session, p: Policy, user: User, typed_name: str, signature: str, ip: str) -> PolicySignature:
    s = db.scalar(select(PolicySignature).where(PolicySignature.policy_id == p.id, PolicySignature.version == p.version,
                                                PolicySignature.user_id == user.id))
    if s is None:
        s = PolicySignature(policy_id=p.id, version=p.version, user_id=user.id, typed_name=typed_name, signature=signature, ip=ip)
        db.add(s)
    now = datetime.now(timezone.utc)
    for t in db.scalars(select(ChecklistTask).where(ChecklistTask.user_id == user.id, ChecklistTask.policy_id == p.id,
                                                    ChecklistTask.done_at.is_(None))):
        t.done_at, t.done_by = now, user.id
    db.flush()
    return s


# --- reviews ---
def start_cycle(db: Session, cycle: ReviewCycle, user_ids: list[int]) -> list[Review]:
    out = []
    for uid in user_ids:
        if db.scalar(select(Review.id).where(Review.cycle_id == cycle.id, Review.user_id == uid)):
            continue
        p = profile(db, uid)
        r = Review(cycle_id=cycle.id, user_id=uid, reviewer_id=p.manager_id)
        db.add(r)
        out.append(r)
    db.flush()
    for r in out:
        notify(db, r.user_id, "review", f"{cycle.name}: fill in your side of the review.", "/my-work", key=f"rv-self-{r.id}")
        if r.reviewer_id:
            u = db.get(User, r.user_id)
            notify(db, r.reviewer_id, "review", f"{cycle.name}: review {u.name or u.email if u else 'someone'}.", "/my-work",
                   key=f"rv-mgr-{r.id}")
    return out


def overall_of(answers: dict, questions: list[dict]) -> float | None:
    vals = [float(answers[q["key"]]) for q in questions if q.get("type") == "rating" and answers.get(q["key"]) not in (None, "")]
    return round(sum(vals) / len(vals), 2) if vals else None


# --- surveys ---
def open_survey(db: Session, s: Survey) -> int:
    n = 0
    for u in db.scalars(select(User).where(User.active.is_(True))):
        if audience_ok(s.audience, u) and not db.scalar(select(SurveyInvite.id).where(SurveyInvite.survey_id == s.id,
                                                                                     SurveyInvite.user_id == u.id)):
            db.add(SurveyInvite(survey_id=s.id, user_id=u.id))
            notify(db, u.id, "survey", f"Quick survey: {s.title}", "/my-work", key=f"sv-{s.id}-{u.id}")
            n += 1
    db.flush()
    return n


def survey_results(db: Session, s: Survey) -> dict:
    MIN_GROUP = 3  # don't break anonymous results down into groups smaller than this
    resp = list(db.scalars(select(SurveyResponse).where(SurveyResponse.survey_id == s.id)))
    invited = db.scalar(select(SurveyInvite.id).where(SurveyInvite.survey_id == s.id).limit(1)) is not None
    total_inv = len(list(db.scalars(select(SurveyInvite.id).where(SurveyInvite.survey_id == s.id)))) if invited else 0
    questions = []
    from .crm import nps_of

    for q in s.questions or []:
        vals = [r.answers.get(q["key"]) for r in resp if r.answers.get(q["key"]) not in (None, "")]
        row = {"key": q["key"], "label": q["label"], "type": q.get("type"), "answers": len(vals)}
        if q.get("type") in ("enps", "rating"):
            nums = [float(v) for v in vals]
            row["average"] = round(sum(nums) / len(nums), 2) if nums else None
            if q.get("type") == "enps":
                row["enps"] = nps_of([int(v) for v in nums])
                by_dept: dict[str, list[int]] = defaultdict(list)
                for r in resp:
                    v = r.answers.get(q["key"])
                    if v not in (None, ""):
                        by_dept[r.department or "other"].append(int(float(v)))
                row["by_department"] = [{"department": d, "enps": nps_of(v), "answers": len(v)} for d, v in sorted(by_dept.items())
                                        if len(v) >= MIN_GROUP or not s.anonymous]
        elif q.get("type") == "choice":
            counts: dict[str, int] = defaultdict(int)
            for v in vals:
                counts[str(v)] += 1
            row["counts"] = dict(counts)
        else:
            texts = [str(v) for v in vals]
            secrets.SystemRandom().shuffle(texts)  # no order to match against who answered when
            row["texts"] = texts
        questions.append(row)
    return {"id": s.id, "title": s.title, "anonymous": s.anonymous, "responses": len(resp), "invited": total_inv,
            "response_rate": round(100 * len(resp) / total_inv, 1) if total_inv else None, "questions": questions}


# --- hiring ---
def hire(db: Session, c: Candidate, *, email: str, role: str, trade: str, start: date | None, by: User,
         checklist_id: int | None = None) -> User:
    from .auth import hash_password

    u = User(email=email.strip().lower(), name=c.name, role=role, password_hash=hash_password(secrets.token_urlsafe(16)),
             trade=trade, phone=c.phone, can_ops=role != "field", can_finance=False)
    db.add(u)
    db.flush()
    o = db.get(JobOpening, c.opening_id) if c.opening_id else None
    p = profile(db, u.id)
    p.start_date = start
    p.position = o.title if o else ""
    p.department = o.department if o else ""
    p.employment_type = o.employment_type if o else "full_time"
    p.manager_id = o.hiring_manager_id if o else None
    c.stage, c.hired_user_id = "hired", u.id
    tpl = db.get(ChecklistTemplate, checklist_id) if checklist_id else db.scalar(
        select(ChecklistTemplate).where(ChecklistTemplate.kind == "onboarding", ChecklistTemplate.active.is_(True)).limit(1))
    if tpl:
        start_checklist(db, u, tpl, start or today_local(), by)
    return u


# --- the daily reminders ---
def daily(db: Session, today: date | None = None) -> int:
    """Licences about to run out (60, 30, 7 days and on the day), and overdue on/offboarding steps."""
    today = today or today_local()
    warn = settings(db)["warn_days"]
    types = {t.id: t for t in db.scalars(select(CredentialType))}
    n = 0
    for c in db.scalars(select(Credential).where(Credential.expires.is_not(None), Credential.expires <= today + timedelta(days=warn))):
        u = db.get(User, c.user_id)
        if not u or not u.active:
            continue
        newer = db.scalar(select(Credential.id).where(Credential.user_id == c.user_id, Credential.type_id == c.type_id,
                                                      Credential.id != c.id, (Credential.expires.is_(None)) | (Credential.expires > c.expires)))
        if newer:
            continue  # already renewed
        left = (c.expires - today).days
        step = next((s for s in (0, 7, 30, warn) if left <= s), None)
        if step is None:
            continue
        t = types.get(c.type_id)
        what = t.name if t else "A licence"
        msg = f"{what} expired on {c.expires:%d/%m/%Y}." if left < 0 else (
            f"{what} expires today." if left == 0 else f"{what} expires in {left} days ({c.expires:%d/%m/%Y}).")
        if notify(db, u.id, "licence", msg + " Upload the new one in the app.", "/field/me", key=f"cred-{c.id}-{step}"):
            n += 1
        notify_hr(db, "licence", f"{u.name or u.email}: {msg}", f"/people/{u.id}", key=f"cred-{c.id}-{step}-hr")
    for t in db.scalars(select(ChecklistTask).where(ChecklistTask.done_at.is_(None), ChecklistTask.due < today)):
        if t.assignee_id:
            notify(db, t.assignee_id, "hr", f"Overdue: {t.title}", "/my-work", key=f"cl-over-{t.id}")
    for p in db.scalars(select(EmployeeProfile).where(EmployeeProfile.status == "terminated", EmployeeProfile.end_date < today)):
        u = db.get(User, p.user_id)
        if u and u.active and u.role != "admin":
            u.active = False  # their sign-in stops the day after their last day
    return n


# --- reports ---
def report(db: Session, today: date | None = None) -> dict:
    today = today or today_local()
    users = {u.id: u for u in db.scalars(select(User))}
    profiles = {p.user_id: p for p in db.scalars(select(EmployeeProfile))}
    staff = [u for u in users.values() if u.active and profiles.get(u.id, None) is not None and profiles[u.id].status != "terminated"]
    staff += [u for u in users.values() if u.active and u.id not in profiles and (u.role == "field" or u.trade)]
    by_dept: dict[str, int] = defaultdict(int)
    by_type: dict[str, int] = defaultdict(int)
    tenure = []
    for u in staff:
        p = profiles.get(u.id)
        by_dept[(p.department if p else "") or "not set"] += 1
        by_type[(p.employment_type if p else "") or "not set"] += 1
        if p and p.start_date:
            tenure.append(years_of_service(p, today))
    year_ago = today - timedelta(days=365)
    starters = [p for p in profiles.values() if p.start_date and p.start_date > year_ago]
    leavers = [p for p in profiles.values() if p.end_date and year_ago < p.end_date <= today]
    head_now = len(staff)
    head_then = head_now - len(starters) + len(leavers)
    avg = (head_now + head_then) / 2 if (head_now + head_then) else 0
    liability = 0.0
    liability_rows = []
    for u in staff:
        bals = balances(db, u, today)
        rate = hourly_rate(db, u.id, profiles.get(u.id))
        val = sum((b["value"] or 0) for b in bals if b["kind"] in ("annual", "long_service"))
        liability += val
        liability_rows.append({"user_id": u.id, "name": u.name or u.email, "rate": rate,
                               "annual_hours": next((b["balance"] for b in bals if b["kind"] == "annual"), 0.0),
                               "sick_hours": next((b["balance"] for b in bals if b["kind"] == "sick"), 0.0),
                               "long_service_hours": next((b["balance"] for b in bals if b["kind"] == "long_service"), 0.0),
                               "value": round(val, 2)})
    comp = []
    for u in staff:
        c = compliance(db, u, today)
        if c["missing"] or c["expired"] or c["expiring"]:
            comp.append({"user_id": u.id, "name": u.name or u.email, "missing": c["missing"], "expired": c["expired"],
                         "expiring": c["expiring"], "items": [r for r in c["credentials"] if r["status"] != "current"]})
    upcoming = []
    for u in staff:
        p = profiles.get(u.id)
        if not p:
            continue
        for kind, d in (("birthday", p.dob), ("anniversary", p.start_date)):
            if not d:
                continue
            try:
                nxt = d.replace(year=today.year)
            except ValueError:
                nxt = date(today.year, 3, 1)
            if nxt < today:
                nxt = nxt.replace(year=today.year + 1) if not (nxt.month == 2 and nxt.day == 29) else date(today.year + 1, 3, 1)
            if (nxt - today).days <= 30 and not (kind == "anniversary" and nxt.year == d.year):
                upcoming.append({"user_id": u.id, "name": u.name or u.email, "kind": kind, "date": nxt.isoformat(),
                                 "years": nxt.year - d.year if kind == "anniversary" else None})
    train = [c for c in db.scalars(select(Credential)) if c.issued and c.issued > year_ago]
    no_emergency = [u.name or u.email for u in staff if not (profiles.get(u.id) and profiles[u.id].emergency_contacts)]
    return {"headcount": head_now, "by_department": dict(by_dept), "by_type": dict(by_type),
            "starters_12m": len(starters), "leavers_12m": len(leavers),
            "turnover_pct": round(100 * len(leavers) / avg, 1) if avg else 0.0,
            "average_tenure_years": round(sum(tenure) / len(tenure), 1) if tenure else None,
            "leave_liability": round(liability, 2), "leave": sorted(liability_rows, key=lambda r: -r["value"]),
            "compliance": comp, "upcoming": sorted(upcoming, key=lambda r: r["date"]),
            "training_12m": {"courses": len(train), "hours": round(sum(c.hours or 0 for c in train), 1),
                             "cost": round(sum(c.cost or 0 for c in train), 2)},
            "missing_emergency_contacts": no_emergency,
            "gear_out": sum(1 for i in db.scalars(select(IssuedItem).where(IssuedItem.returned.is_(None))))}


def announcements_for(db: Session, user: User) -> list[dict]:
    today = today_local()
    rows = db.scalars(select(Announcement).order_by(Announcement.pinned.desc(), Announcement.created_at.desc()).limit(30))
    return [{"id": a.id, "title": a.title, "body": a.body, "pinned": a.pinned, "at": a.created_at.isoformat()}
            for a in rows if audience_ok(a.audience, user) and (a.expires is None or a.expires >= today)][:10]


def my_hr(db: Session, user: User) -> dict:
    """The person's own HR things, for the phone and My work."""
    from .models import Goal

    todo_tasks = list(db.scalars(select(ChecklistTask).where(ChecklistTask.assignee_id == user.id, ChecklistTask.done_at.is_(None))
                                 .order_by(ChecklistTask.due)))
    names = {u.id: u.name or u.email for u in db.scalars(select(User))}
    reviews = []
    for r in db.scalars(select(Review).where((Review.user_id == user.id) | (Review.reviewer_id == user.id))):
        cyc = db.get(ReviewCycle, r.cycle_id)
        if not cyc:
            continue
        mine = r.user_id == user.id
        if (mine and r.self_done_at is None) or (not mine and r.manager_done_at is None and cyc.status == "open"):
            reviews.append({"id": r.id, "cycle": cyc.name, "due": _iso(cyc.due), "as": "self" if mine else "manager",
                            "person": names.get(r.user_id, "")})
    surveys = []
    for inv in db.scalars(select(SurveyInvite).where(SurveyInvite.user_id == user.id, SurveyInvite.answered.is_(False))):
        s = db.get(Survey, inv.survey_id)
        if s and s.status == "open":
            surveys.append({"id": s.id, "title": s.title, "anonymous": s.anonymous})
    return {"tasks": [task_out(db, t, names) for t in todo_tasks],
            "policies": [{"id": p.id, "title": p.title, "version": p.version} for p in policies_to_sign(db, user)],
            "reviews": reviews, "surveys": surveys,
            "goals": [{"id": g.id, "title": g.title, "progress": g.progress, "due": _iso(g.due), "status": g.status}
                      for g in db.scalars(select(Goal).where(Goal.user_id == user.id, Goal.status == "open"))],
            "announcements": announcements_for(db, user)}


def _iso(d) -> str | None:
    return d.isoformat() if d else None
