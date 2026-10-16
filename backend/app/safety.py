"""Safety: SWMS (a library, a copy on each job, and everyone signing on), incident / near-miss / hazard reports with
corrective actions, toolbox talks, the daily site pre-start, and the safety dashboard. Each day the phone tells each person
what they still need to do before starting on each job (sign the SWMS, the pre-start, ITP checks).
"""
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (Job, JobSwms, ScheduleEntry, SafetyAction, SafetyEvent, SitePrestart, SwmsSignon, SwmsTemplate, TimeEntry, ToolboxTalk,
                     User)
from .plant import notify
from .timesheets import local_day

# Queensland WHS Regulation s291: high risk construction work
HIGH_RISK = [
    "Risk of a person falling more than 2 m", "Telecommunication tower", "Demolition of load-bearing structure",
    "Disturbing or removing asbestos", "Structural alteration needing temporary support", "Confined space",
    "Shaft or trench deeper than 1.5 m, or a tunnel", "Use of explosives", "On or near pressurised gas mains or piping",
    "On or near chemical, fuel or refrigerant lines", "On or near energised electrical installations",
    "Area with a contaminated or flammable atmosphere", "Tilt-up or precast concrete", "On or adjacent to a road or railway in use",
    "Workplace with movement of powered mobile plant", "Artificial extremes of temperature", "In or near water with a risk of drowning",
    "Diving work",
]
EVENT_KINDS = {"hazard": "Hazard", "near_miss": "Near miss", "incident": "Incident", "injury": "Injury", "property": "Property damage",
               "environment": "Environmental"}
TREATMENT = {"none": "None", "first_aid": "First aid", "medical": "Medical treatment", "lost_time": "Lost time"}
PRESTART_QUESTIONS = [
    {"key": "weather", "label": "Weather and site conditions", "type": "text"},
    {"key": "hazards", "label": "Hazards on site today", "type": "text"},
    {"key": "services", "label": "Underground services located (DBYD, potholed)", "type": "yesno"},
    {"key": "permits", "label": "Permits needed today", "type": "multi", "options": ["None", "Hot work", "Confined space", "Excavation", "Road closure / TMP", "Isolation"]},
    {"key": "exclusion", "label": "Exclusion zones and barricades set up", "type": "yesno"},
    {"key": "plant", "label": "Plant pre-starts done", "type": "yesno"},
    {"key": "ppe", "label": "Everyone has the right PPE", "type": "yesno"},
    {"key": "first_aid", "label": "First aid kit, extinguisher and eyewash on site", "type": "yesno"},
    {"key": "assembly", "label": "Emergency assembly point", "type": "text"},
    {"key": "swms", "label": "Today's SWMS reviewed with the crew", "type": "yesno"},
    {"key": "notes", "label": "Anything else", "type": "text"},
]


def _s(step, hazards, before, controls, after, who="All workers"):
    return {"step": step, "hazards": hazards, "risk_before": before, "controls": controls, "risk_after": after, "who": who}


DEFAULT_SWMS = [
    {"title": "Excavation and trenching", "activity": "Digging and working in trenches for sewer, stormwater and water mains",
     "high_risk": ["Shaft or trench deeper than 1.5 m, or a tunnel", "Workplace with movement of powered mobile plant",
                   "On or near pressurised gas mains or piping", "On or near energised electrical installations"],
     "ppe": ["Hard hat", "Hi-vis", "Steel caps", "Gloves", "Safety glasses", "Hearing protection"],
     "steps": [_s("Locate services", "Striking gas, power, water or comms", "E", "DBYD plans on site; locate and pothole by hand / vac before digging; spotter", "M", "Supervisor"),
               _s("Set up the site", "Public and other trades entering, mobile plant", "H", "Barricade and sign; exclusion zone around the excavator; spotter for reversing", "L"),
               _s("Excavate", "Plant strikes worker, overhead power lines", "H", "Swing radius kept clear; ground worker only in view of operator; check overhead clearances", "M", "Operator"),
               _s("Work in the trench", "Collapse, falling objects, water", "E", "Over 1.5 m: shore, bench or batter; spoil 1 m back from the edge; ladder within 9 m; no one alone in a trench", "M"),
               _s("Backfill and compact", "Plant, vibration, dust", "M", "Compactor rotated between workers; dust suppressed; area clear before backfilling", "L")]},
    {"title": "Working at heights", "activity": "Ladders, mobile scaffold, roofs and ceiling spaces",
     "high_risk": ["Risk of a person falling more than 2 m"], "ppe": ["Hard hat", "Steel caps", "Harness (roof work)"],
     "steps": [_s("Choose the access", "Wrong equipment for the task", "H", "Platform ladder or mobile scaffold first; extension ladders only for access, tied off, 1 m above landing", "L"),
               _s("Roof work", "Falls through skylights or off edges", "E", "Edge protection or anchor points and harness; skylights covered; not in wet or high wind", "M"),
               _s("Ceiling spaces", "Falling through ceiling, heat, electrical", "H", "Walk on joists / crawl boards; power isolated if cables disturbed; hydrate, limit time in heat", "M")]},
    {"title": "Confined spaces", "activity": "Pits, manholes, tanks, wet wells",
     "high_risk": ["Confined space", "Area with a contaminated or flammable atmosphere"], "ppe": ["Gas detector", "Harness and tripod", "Gloves"],
     "steps": [_s("Permit and plan", "Entering without a plan", "E", "Confined space entry permit signed; rescue plan; trained entrants only", "M", "Supervisor"),
               _s("Test the atmosphere", "Low oxygen, H2S, methane", "E", "Gas test before entry and continuously; ventilate; isolate inflows", "M"),
               _s("Enter and work", "Engulfment, fatigue, communication", "H", "Standby person at the entry at all times; harness and tripod; radio contact", "M")]},
    {"title": "Hot works", "activity": "Brazing, soldering, welding and cutting",
     "high_risk": [], "ppe": ["Welding gloves", "Face shield / goggles", "Fire extinguisher"],
     "steps": [_s("Check the area", "Fire, flammable materials", "H", "Hot work permit where required; 10 m clear of flammables or covered; extinguisher at hand", "L"),
               _s("Do the work", "Burns, fumes", "M", "Ventilate; correct gloves and eye protection; gas bottles upright and secured", "L"),
               _s("Fire watch", "Smouldering after work", "M", "Watch the area 30 minutes after finishing", "L")]},
    {"title": "Gas fitting and commissioning", "activity": "Installing, testing, purging and commissioning gas lines and appliances",
     "high_risk": ["On or near pressurised gas mains or piping"], "ppe": ["Gas detector", "Gloves", "Safety glasses"],
     "steps": [_s("Isolate", "Gas escape", "E", "Isolate and tag the supply; check with a detector", "M", "Licensed gasfitter"),
               _s("Pressure test", "Leaks, over-pressure", "H", "Test to AS/NZS 5601 with a calibrated gauge; record readings", "L", "Licensed gasfitter"),
               _s("Purge and commission", "Explosive atmosphere, CO", "E", "Purge to outside; no ignition sources; check flue and CO; record", "M", "Licensed gasfitter")]},
    {"title": "Drain clearing and jetting", "activity": "Clearing blockages with eels and jetters; CCTV",
     "high_risk": [], "ppe": ["Gloves", "Face shield", "Waterproofs"],
     "steps": [_s("Set up", "Sewage contact, trips", "M", "Barricade the area; mats and hoses run neatly", "L"),
               _s("Jet / eel", "High-pressure injury, whipping cable", "H", "Trained operators only; foot pedal control; never hold the hose by hand at the nozzle", "M"),
               _s("Clean up", "Infection", "M", "Wash down, sanitise; vaccinations current (Hep A/B, tetanus)", "L")]},
    {"title": "Working near traffic and mobile plant", "activity": "Road reserves, carparks, driveways",
     "high_risk": ["On or adjacent to a road or railway in use", "Workplace with movement of powered mobile plant"], "ppe": ["Hi-vis class D/N", "Hard hat"],
     "steps": [_s("Traffic management", "Being struck by vehicles", "E", "Approved TGS / TMP; accredited traffic controllers where needed", "M", "Supervisor"),
               _s("Mobile plant", "Plant strikes worker", "H", "Exclusion zones; reversing cameras / beepers; spotter; eye contact with operator", "M")]},
    {"title": "Asbestos cement pipe (non-friable, under 10 m²)", "activity": "Cutting into or removing AC pipe",
     "high_risk": ["Disturbing or removing asbestos"], "ppe": ["P2 mask", "Disposable coveralls", "Gloves"],
     "steps": [_s("Identify", "Not knowing it's asbestos", "H", "Assume old grey pipe is AC; check the asbestos register", "M"),
               _s("Cut / remove", "Breathing in fibres", "E", "Wet methods only; no power tools; hand tools or pipe cutters; area bunted off", "M"),
               _s("Dispose", "Contaminating the site", "H", "Double-wrap in 200 µm plastic, label, licensed disposal; decontaminate", "L")]},
]


def seed(db: Session) -> None:
    if not db.scalar(select(SwmsTemplate.id).limit(1)):
        for t in DEFAULT_SWMS:
            db.add(SwmsTemplate(**t))
    from . import itp

    itp.seed(db)
    db.flush()


def today() -> date:
    return local_day(datetime.now(timezone.utc))


def admins(db: Session) -> list[User]:
    return list(db.scalars(select(User).where(User.active.is_(True), User.role == "admin")))


# --- SWMS ---
def add_to_job(db: Session, job: Job, t: SwmsTemplate, user: User | None, site_notes: str = "") -> JobSwms:
    js = JobSwms(job_id=job.id, template_id=t.id, title=t.title, activity=t.activity, high_risk=list(t.high_risk or []), ppe=list(t.ppe or []),
                 steps=[dict(s) for s in t.steps or []], site_notes=site_notes, created_by=user.id if user else None)
    db.add(js)
    db.flush()
    return js


def signed(db: Session, js: JobSwms, user_id: int) -> SwmsSignon | None:
    return db.scalar(select(SwmsSignon).where(SwmsSignon.job_swms_id == js.id, SwmsSignon.version == js.version, SwmsSignon.user_id == user_id))


def sign_on(db: Session, js: JobSwms, user: User, typed_name: str, signature: str) -> SwmsSignon:
    s = signed(db, js, user.id)
    if s is None:
        s = SwmsSignon(job_swms_id=js.id, version=js.version, user_id=user.id, typed_name=typed_name, signature=signature)
        db.add(s)
        db.flush()
    return s


def swms_out(db: Session, js: JobSwms, names: dict[int, str], me: int | None = None) -> dict:
    signs = list(db.scalars(select(SwmsSignon).where(SwmsSignon.job_swms_id == js.id, SwmsSignon.version == js.version).order_by(SwmsSignon.signed_at)))
    return {"id": js.id, "job_id": js.job_id, "template_id": js.template_id, "title": js.title, "activity": js.activity, "high_risk": js.high_risk,
            "ppe": js.ppe, "steps": js.steps, "site_notes": js.site_notes, "version": js.version, "status": js.status,
            "signed": [{"user_id": s.user_id, "name": names.get(s.user_id, s.typed_name), "typed_name": s.typed_name, "at": s.signed_at.isoformat()} for s in signs],
            "i_signed": any(s.user_id == me for s in signs) if me else None, "created_at": js.created_at.isoformat()}


# --- incidents and hazards ---
def report(db: Session, user: User, **fields) -> SafetyEvent:
    e = SafetyEvent(reported_by=user.id, **fields)
    db.add(e)
    db.flush()
    label = EVENT_KINDS.get(e.kind, e.kind)
    urgent = e.severity in ("high", "critical") or e.treatment in ("medical", "lost_time") or e.notifiable
    job = db.get(Job, e.job_id) if e.job_id else None
    for a in admins(db):
        if a.id != user.id:
            notify(db, a.id, "safety", f"{'🚨 ' if urgent else ''}{label} reported by {user.name or user.email}: {e.title}"
                   + (f" ({job.job_no or job.name})" if job else ""), f"/safety?event={e.id}", key=f"safety-{e.id}-{a.id}")
    if job and job.supervisor_id and job.supervisor_id != user.id:
        notify(db, job.supervisor_id, "safety", f"{label} on {job.job_no or job.name}: {e.title}", f"/safety?event={e.id}", key=f"safety-{e.id}-sup")
    return e


def event_out(db: Session, e: SafetyEvent, names: dict[int, str]) -> dict:
    job = db.get(Job, e.job_id) if e.job_id else None
    acts = list(db.scalars(select(SafetyAction).where(SafetyAction.event_id == e.id).order_by(SafetyAction.id)))
    return {"id": e.id, "kind": e.kind, "kind_label": EVENT_KINDS.get(e.kind, e.kind), "job_id": e.job_id, "job": f"{job.job_no or ''} {job.name}".strip() if job else "",
            "location": e.location, "occurred_at": e.occurred_at.isoformat(), "reported_by": names.get(e.reported_by or 0, ""), "title": e.title,
            "description": e.description, "immediate_action": e.immediate_action, "severity": e.severity, "treatment": e.treatment,
            "treatment_label": TREATMENT.get(e.treatment, e.treatment), "people": e.people, "notifiable": e.notifiable, "photos": e.photos or [],
            "status": e.status, "root_cause": e.root_cause, "closed_at": e.closed_at.isoformat() if e.closed_at else None,
            "actions": [action_out(a, names) for a in acts]}


def action_out(a: SafetyAction, names: dict[int, str]) -> dict:
    return {"id": a.id, "event_id": a.event_id, "job_id": a.job_id, "description": a.description, "assignee_id": a.assignee_id,
            "assignee": names.get(a.assignee_id or 0, ""), "due": a.due.isoformat() if a.due else None, "status": a.status,
            "overdue": a.status == "open" and a.due is not None and a.due < today(), "done_note": a.done_note,
            "done_at": a.done_at.isoformat() if a.done_at else None}


# --- daily site pre-start ---
def prestart_out(sp: SitePrestart, names: dict[int, str]) -> dict:
    return {"id": sp.id, "job_id": sp.job_id, "day": sp.day.isoformat(), "led_by": names.get(sp.led_by or 0, ""), "answers": sp.answers,
            "attendees": sp.attendees, "questions": PRESTART_QUESTIONS}


def sign_attendee(record, user: User, signature: str = "") -> None:
    att = list(record.attendees or [])
    if not any(a.get("user_id") == user.id for a in att):
        att.append({"user_id": user.id, "name": user.name or user.email, "signed_at": datetime.now(timezone.utc).isoformat(), "signature": signature})
        record.attendees = att


# --- what each person still has to do today, per job ---
def jobs_today(db: Session, user: User, day: date | None = None) -> list[Job]:
    day = day or today()
    ids = set(db.scalars(select(ScheduleEntry.job_id).where(ScheduleEntry.user_id == user.id, ScheduleEntry.day == day,
                                                            ScheduleEntry.job_id.is_not(None))))
    open_e = db.scalar(select(TimeEntry).where(TimeEntry.user_id == user.id, TimeEntry.end_at.is_(None)))
    if open_e and open_e.job_id:
        ids.add(open_e.job_id)
    for e in db.scalars(select(TimeEntry).where(TimeEntry.user_id == user.id, TimeEntry.job_id.is_not(None),
                                                TimeEntry.start_at >= datetime.now(timezone.utc) - timedelta(hours=16))):
        if local_day(e.start_at) == day:
            ids.add(e.job_id)
    return [j for j in (db.get(Job, i) for i in ids) if j and j.work_status not in ("invoiced", "closed")]


def prompts(db: Session, user: User, job: Job, day: date | None = None) -> dict:
    from . import itp

    day = day or today()
    swms = [js for js in db.scalars(select(JobSwms).where(JobSwms.job_id == job.id, JobSwms.status == "active")) if not signed(db, js, user.id)]
    sp = db.scalar(select(SitePrestart).where(SitePrestart.job_id == job.id, SitePrestart.day == day))
    due = itp.due_today(db, job, day)
    out = {"job_id": job.id, "job_no": job.job_no, "job": job.name,
           "swms_to_sign": [{"id": js.id, "title": js.title} for js in swms],
           "prestart": {"done": sp is not None, "id": sp.id if sp else None,
                        "signed": bool(sp and any(a.get("user_id") == user.id for a in sp.attendees or []))},
           "itp_due": due}
    out["count"] = len(out["swms_to_sign"]) + (0 if out["prestart"]["signed"] else 1) + len(due)
    return out


def my_day(db: Session, user: User) -> list[dict]:
    return [prompts(db, user, j) for j in jobs_today(db, user)]


# --- dashboard ---
def dashboard(db: Session, months: int = 12) -> dict:
    t = today()
    events = list(db.scalars(select(SafetyEvent)))
    lti = [e for e in events if e.treatment == "lost_time"]
    last_lti = max((local_day(e.occurred_at) for e in lti), default=None)
    keys = []
    y, m = t.year, t.month
    for _ in range(months):
        keys.append(f"{y}-{m:02d}")
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    keys.reverse()
    by_month: dict[str, dict[str, int]] = {k: defaultdict(int) for k in keys}
    for e in events:
        k = local_day(e.occurred_at).strftime("%Y-%m")
        if k in by_month:
            by_month[k][e.kind] += 1
    acts = list(db.scalars(select(SafetyAction).where(SafetyAction.status == "open")))
    week_start = t - timedelta(days=t.weekday())
    active_jobs = [j for j in db.scalars(select(Job).where(Job.work_status.in_(("scheduled", "in_progress"))))]
    on_today = {e.job_id for e in db.scalars(select(ScheduleEntry).where(ScheduleEntry.day == t, ScheduleEntry.job_id.is_not(None)))}
    prestarts_today = {sp.job_id for sp in db.scalars(select(SitePrestart).where(SitePrestart.day == t))}
    return {"days_since_lti": (t - last_lti).days if last_lti else None, "last_lti": last_lti.isoformat() if last_lti else None,
            "open_events": sum(1 for e in events if e.status != "closed"),
            "open_actions": len(acts), "overdue_actions": sum(1 for a in acts if a.due and a.due < t),
            "events_12m": sum(sum(v.values()) for v in by_month.values()),
            "by_month": [{"month": k, **dict(v)} for k, v in by_month.items()],
            "toolbox_this_month": sum(1 for tb in db.scalars(select(ToolboxTalk)) if tb.day.strftime("%Y-%m") == t.strftime("%Y-%m")),
            "signons_this_week": sum(1 for s in db.scalars(select(SwmsSignon)) if local_day(s.signed_at) >= week_start),
            "jobs_on_today": len(on_today), "prestarts_today": len(prestarts_today & on_today) if on_today else len(prestarts_today),
            "missing_prestarts": [{"job_id": j.id, "job": f"{j.job_no} {j.name}"} for j in active_jobs if j.id in on_today and j.id not in prestarts_today],
            "kinds": EVENT_KINDS}


def daily(db: Session) -> int:
    """Corrective actions now overdue go to whoever has them."""
    n = 0
    for a in db.scalars(select(SafetyAction).where(SafetyAction.status == "open", SafetyAction.due < today())):
        if a.assignee_id and notify(db, a.assignee_id, "safety", f"Overdue safety action: {a.description[:120]}", "/safety?tab=actions",
                                    key=f"sa-over-{a.id}"):
            n += 1
    return n
