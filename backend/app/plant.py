"""Plant and vehicles (Plant Assessor style): pre-starts, start/end-of-day photos, weekly vehicle checks, washes, defects.

The rules that hold up clocking in (each can be switched off in the settings):
  * Someone with a company vehicle can't clock in for the week until that week's vehicle pre-start is done.
  * Operating a machine needs that day's pre-start, with a photo of the machine and of the fuel gauge.
  * Clocking off after operating it needs the end-of-day photos (machine and fuel gauge again).
  * Plant with an open critical defect is out of service and can't be picked.
A monthly reminder asks each driver to wash their vehicle and send photos of the outside and inside.
"""
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import AppSetting, FormTemplate, Notification, Plant, PlantCheck, PlantDefect, TimeEntry, User
from .timesheets import day_bounds, local_day, week_start

DEFAULTS = {
    "weekly_vehicle_prestart": True,  # block clock-in until the week's vehicle check is done
    "plant_photos": True,  # machine + fuel photos at the start and end of each day
    "wash_monthly": True,  # monthly wash reminder with photos
    "wash_block_after_days": 0,  # 0 = remind only; e.g. 10 = can't clock in after the 10th until it's done
}
VEHICLE_CHECK = [
    {"key": "tyres", "label": "Tyres: tread, pressure, no damage", "type": "yesno"},
    {"key": "lights", "label": "Lights, indicators and horn work", "type": "yesno"},
    {"key": "fluids", "label": "Oil, coolant, washer fluid OK", "type": "yesno"},
    {"key": "brakes", "label": "Brakes OK", "type": "yesno"},
    {"key": "body", "label": "No new damage to the body or glass", "type": "yesno"},
    {"key": "load", "label": "Load restraints, ladder racks and toolboxes secure", "type": "yesno"},
    {"key": "kit", "label": "First aid kit and fire extinguisher present", "type": "yesno"},
]
PLANT_CHECK = [
    {"key": "walkaround", "label": "Walk-around done: no leaks, damage or loose parts", "type": "yesno"},
    {"key": "fluids", "label": "Engine oil, hydraulic oil and coolant levels OK", "type": "yesno"},
    {"key": "tracks", "label": "Tracks / tyres, pins and bushes OK", "type": "yesno"},
    {"key": "guards", "label": "Guards, steps, handrails and ROPS in place", "type": "yesno"},
    {"key": "controls", "label": "Controls, brakes and isolators work", "type": "yesno"},
    {"key": "alarm", "label": "Reversing alarm, beacon and lights work", "type": "yesno"},
    {"key": "seatbelt", "label": "Seatbelt OK", "type": "yesno"},
    {"key": "attachments", "label": "Bucket / attachments and quick hitch locked", "type": "yesno"},
]


def settings(db: Session) -> dict:
    s = db.get(AppSetting, "plant")
    return {**DEFAULTS, **((s.value or {}) if s else {})}


def checklist(db: Session, p: Plant) -> list[dict]:
    if p.checklist_id:
        t = db.get(FormTemplate, p.checklist_id)
        if t:
            return t.fields
    return VEHICLE_CHECK if p.kind == "vehicle" else PLANT_CHECK


def failed_items(fields: list[dict], answers: dict) -> list[str]:
    return [f["label"] for f in fields if f.get("type") == "yesno" and answers.get(f["key"]) in (False, "no", "No")]


def _since(d: date) -> datetime:
    return day_bounds(d)[0]


def last_check(db: Session, plant_id: int, kind: str, since: datetime, user_id: int | None = None) -> PlantCheck | None:
    stmt = select(PlantCheck).where(PlantCheck.plant_id == plant_id, PlantCheck.kind == kind, PlantCheck.at >= since)
    if user_id is not None:
        stmt = stmt.where(PlantCheck.user_id == user_id)
    return db.scalar(stmt.order_by(PlantCheck.at.desc()))


def my_vehicles(db: Session, user: User) -> list[Plant]:
    return list(db.scalars(select(Plant).where(Plant.assigned_user_id == user.id, Plant.kind == "vehicle", Plant.status != "sold")))


def todo(db: Session, user: User, today: date | None = None) -> dict:
    """What this person must do before (blocking) or soon (reminders), for the phone's front screen."""
    today = today or local_day(datetime.now(timezone.utc))
    cfg = settings(db)
    blocking, reminders = [], []
    for v in my_vehicles(db, user):
        if cfg["weekly_vehicle_prestart"] and not last_check(db, v.id, "weekly", _since(week_start(today))):
            blocking.append({"kind": "weekly", "plant_id": v.id, "plant": v.name,
                             "text": f"Do this week's pre-start on {v.name}{' (' + v.rego + ')' if v.rego else ''} before you clock in."})
        if cfg["wash_monthly"] and not last_check(db, v.id, "wash", _since(today.replace(day=1))):
            item = {"kind": "wash", "plant_id": v.id, "plant": v.name,
                    "text": f"Wash {v.name} this month and send photos of the outside and the inside."}
            limit = int(cfg["wash_block_after_days"] or 0)
            (blocking if limit and today.day > limit else reminders).append(item)
        for label, d in (("Rego", v.rego_expiry), ("Insurance", v.insurance_expiry)):
            if d and d <= today + timedelta(days=14):
                reminders.append({"kind": "expiry", "plant_id": v.id, "plant": v.name,
                                  "text": f"{label} on {v.name} {'expired' if d < today else 'is due'} {d.strftime('%d/%m/%Y')}. Tell the office."})
    return {"blocking": blocking, "reminders": reminders}


def start_requirements(db: Session, user: User, plant_ids: list[int], today: date | None = None) -> list[str]:
    """Why this person can't clock in yet (empty = fine)."""
    today = today or local_day(datetime.now(timezone.utc))
    problems = [b["text"] for b in todo(db, user, today)["blocking"]]
    cfg = settings(db)
    for pid in plant_ids:
        p = db.get(Plant, pid)
        if p is None:
            problems.append("That machine isn't in the plant register")
            continue
        if p.status in ("out_of_service", "in_repair"):
            problems.append(f"{p.name} is out of service. Pick another machine or talk to your supervisor.")
            continue
        chk = last_check(db, p.id, "prestart", _since(today))
        if chk is None:
            problems.append(f"Do the pre-start on {p.name} first.")
        elif not chk.passed:
            problems.append(f"{p.name} failed today's pre-start. It can't be used until it's fixed.")
        elif cfg["plant_photos"] and p.photos_required:
            photos = chk.photo_ids or {}
            if not photos.get("machine") or not photos.get("fuel"):
                problems.append(f"Add the start-of-day photos of {p.name} and its fuel gauge.")
    return problems


def end_requirements(db: Session, user: User, today: date | None = None) -> list[str]:
    """Machines this person ran today that still need their end-of-day photos."""
    today = today or local_day(datetime.now(timezone.utc))
    cfg = settings(db)
    if not cfg["plant_photos"]:
        return []
    lo, hi = day_bounds(today)
    used = {e.plant_id for e in db.scalars(select(TimeEntry).where(TimeEntry.user_id == user.id, TimeEntry.start_at >= lo,
                                                                 TimeEntry.start_at < hi, TimeEntry.plant_id.is_not(None)))}
    out = []
    for pid in used:
        p = db.get(Plant, pid)
        if p is None or not p.photos_required:
            continue
        chk = last_check(db, pid, "end_day", lo, user.id)
        if chk is None or not (chk.photo_ids or {}).get("machine") or not (chk.photo_ids or {}).get("fuel"):
            out.append(f"Before you clock off: photos of {p.name} and its fuel gauge.")
    return out


def record_readings(p: Plant, hours: float | None, km: float | None) -> None:
    if hours is not None and (p.hours is None or hours >= p.hours):
        p.hours = hours
    if km is not None and (p.odometer is None or km >= p.odometer):
        p.odometer = km


def service_due(p: Plant, today: date | None = None) -> list[str]:
    today = today or date.today()
    out = []
    if p.service_every_hours and p.hours is not None and p.hours - (p.last_service_hours or 0) >= p.service_every_hours:
        out.append(f"service due at {(p.last_service_hours or 0) + p.service_every_hours:.0f} h")
    if p.service_every_km and p.odometer is not None and p.odometer - (p.last_service_km or 0) >= p.service_every_km:
        out.append(f"service due at {(p.last_service_km or 0) + p.service_every_km:,.0f} km")
    if p.next_service_date and p.next_service_date <= today:
        out.append(f"service due {p.next_service_date.strftime('%d/%m/%Y')}")
    if p.rego_expiry and p.rego_expiry <= today + timedelta(days=30):
        out.append(f"rego {'expired' if p.rego_expiry < today else 'due'} {p.rego_expiry.strftime('%d/%m/%Y')}")
    if p.insurance_expiry and p.insurance_expiry <= today + timedelta(days=30):
        out.append(f"insurance {'expired' if p.insurance_expiry < today else 'due'} {p.insurance_expiry.strftime('%d/%m/%Y')}")
    return out


def report_defect(db: Session, p: Plant, user: User | None, severity: str, description: str, photo_ids: list[int] | None = None,
                  kind: str = "defect", check_id: int | None = None) -> PlantDefect:
    d = PlantDefect(plant_id=p.id, reported_by=user.id if user else None, severity=severity, description=description,
                    photo_ids=photo_ids or [], kind=kind, check_id=check_id)
    db.add(d)
    if severity == "critical":
        p.status = "out_of_service"
    db.flush()
    who = (user.name or user.email) if user else "Someone"
    for u in db.scalars(select(User).where(User.active.is_(True))):
        if u.role == "admin" or u.trade in ("supervisor", "manager", "project manager"):
            notify(db, u.id, "plant_defect", f"{who} reported {'CRITICAL ' if severity == 'critical' else ''}{kind} on {p.name}: {description[:120]}",
                   f"/plant/{p.id}", key=f"defect-{d.id}-{u.id}")
    return d


def notify(db: Session, user_id: int, kind: str, text: str, link: str = "", key: str = "") -> Notification | None:
    if key and db.scalar(select(Notification.id).where(Notification.key == key)):
        return None
    n = Notification(user_id=user_id, kind=kind, text=text, link=link, key=key)
    db.add(n)
    db.flush()
    return n


def monthly_reminders(db: Session, today: date | None = None) -> int:
    """On the first working days of the month, remind each driver to wash their vehicle (once a month)."""
    today = today or local_day(datetime.now(timezone.utc))
    if not settings(db)["wash_monthly"]:
        return 0
    n = 0
    for v in db.scalars(select(Plant).where(Plant.kind == "vehicle", Plant.assigned_user_id.is_not(None), Plant.status != "sold")):
        if last_check(db, v.id, "wash", _since(today.replace(day=1))):
            continue
        if notify(db, v.assigned_user_id, "wash", f"Time to wash {v.name}. Send a photo of the outside and the inside from Pre-start.",
                  "/field/prestart", key=f"wash-{v.id}-{today.strftime('%Y-%m')}"):
            n += 1
    return n


def plant_cost_rate(db: Session, plant_id: int | None) -> float:
    if not plant_id:
        return 0.0
    p = db.get(Plant, plant_id)
    return p.hire_rate if p else 0.0

