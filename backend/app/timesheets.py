"""Clocking in and out, timesheets, overtime and the schedule (QuickBooks Time style).

Times are stored in UTC and shown in the company's time zone (Brisbane by default: no daylight saving).
A person has at most one open entry. Clocking into another job closes the open one at the same moment,
so switching jobs never loses or doubles a minute. Breaks pause the clock inside an entry.
"""
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import ops
from .finance import entry_hours
from .models import Job, ScheduleEntry, TimeEntry, TimeOff, User

TZ = ZoneInfo("Australia/Brisbane")
LONG_SHIFT_HOURS = 12  # an entry longer than this is flagged (forgot to clock out?)


def now() -> datetime:
    return datetime.now(timezone.utc)


def aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def local(dt: datetime) -> datetime:
    return aware(dt).astimezone(TZ)


def local_day(dt: datetime) -> date:
    return local(dt).date()


def day_bounds(d: date) -> tuple[datetime, datetime]:
    start = datetime.combine(d, time.min, tzinfo=TZ).astimezone(timezone.utc)
    return start, start + timedelta(days=1)


def week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def open_entry(db: Session, user_id: int) -> TimeEntry | None:
    return db.scalar(select(TimeEntry).where(TimeEntry.user_id == user_id, TimeEntry.end_at.is_(None)).order_by(TimeEntry.start_at.desc()))


def close(e: TimeEntry, at: datetime, lat=None, lng=None) -> None:
    if e.break_started_at:
        e.break_minutes = (e.break_minutes or 0) + max(0.0, (at - aware(e.break_started_at)).total_seconds() / 60)
        e.break_started_at = None
    e.end_at = max(at, aware(e.start_at))
    e.end_lat, e.end_lng = lat, lng


def clock_in(db: Session, user: User, job_id: int | None, task: str = "", lat=None, lng=None, at: datetime | None = None,
             client_ref: str = "", source: str = "app", notes: str = "") -> TimeEntry:
    at = aware(at) or now()
    if client_ref:
        dup = db.scalar(select(TimeEntry).where(TimeEntry.user_id == user.id, TimeEntry.client_ref == client_ref))
        if dup:
            return dup  # a phone retrying after a dropout
    cur = open_entry(db, user.id)
    if cur is not None:
        close(cur, at, lat, lng)
    e = TimeEntry(user_id=user.id, job_id=job_id, task=task, start_at=at, start_lat=lat, start_lng=lng, source=source,
                  client_ref=client_ref, notes=notes)
    db.add(e)
    if job_id:
        job = db.get(Job, job_id)
        if job is not None and job.work_status == "scheduled":
            job.work_status = "in_progress"
    db.flush()
    return e


def clock_out(db: Session, user: User, lat=None, lng=None, notes: str = "", at: datetime | None = None) -> TimeEntry | None:
    e = open_entry(db, user.id)
    if e is None:
        return None
    close(e, aware(at) or now(), lat, lng)
    if notes:
        e.notes = (e.notes + "\n" + notes).strip()
    db.flush()
    return e


def start_break(db: Session, user: User) -> TimeEntry | None:
    e = open_entry(db, user.id)
    if e is not None and not e.break_started_at:
        e.break_started_at = now()
    return e


def end_break(db: Session, user: User) -> TimeEntry | None:
    e = open_entry(db, user.id)
    if e is not None and e.break_started_at:
        e.break_minutes = (e.break_minutes or 0) + max(0.0, (now() - aware(e.break_started_at)).total_seconds() / 60)
        e.break_started_at = None
    return e


def entry_out(db: Session, e: TimeEntry, jobs: dict[int, Job] | None = None) -> dict:
    job = (jobs or {}).get(e.job_id) if jobs is not None else (db.get(Job, e.job_id) if e.job_id else None)
    hrs = entry_hours(e)
    flags = []
    if hrs > LONG_SHIFT_HOURS:
        flags.append("long")
    if e.source in ("manual", "office"):
        flags.append("added by hand")
    if e.edited_reason:
        flags.append("edited")
    if e.source == "app" and e.start_lat is None:
        flags.append("no location")
    return {"id": e.id, "user_id": e.user_id, "job_id": e.job_id, "job_no": job.job_no if job else "", "job": job.name if job else "",
            "task": e.task, "start_at": aware(e.start_at).isoformat(), "end_at": aware(e.end_at).isoformat() if e.end_at else None,
            "local_day": local_day(e.start_at).isoformat(), "start_local": local(e.start_at).strftime("%H:%M"),
            "end_local": local(e.end_at).strftime("%H:%M") if e.end_at else None, "hours": round(hrs, 2),
            "break_minutes": round(e.break_minutes or 0), "on_break": bool(e.break_started_at), "notes": e.notes, "status": e.status,
            "source": e.source, "start_lat": e.start_lat, "start_lng": e.start_lng, "end_lat": e.end_lat, "end_lng": e.end_lng,
            "edited_reason": e.edited_reason, "flags": flags}


def week_entries(db: Session, start: date, user_id: int | None = None) -> list[TimeEntry]:
    lo, _ = day_bounds(start)
    hi, _ = day_bounds(start + timedelta(days=7))
    stmt = select(TimeEntry).where(TimeEntry.start_at >= lo, TimeEntry.start_at < hi).order_by(TimeEntry.start_at)
    if user_id is not None:
        stmt = stmt.where(TimeEntry.user_id == user_id)
    return list(db.scalars(stmt))


def overtime(db: Session, hours_by_day: dict[str, float]) -> dict:
    """Ordinary and overtime hours for one person's week, by the daily and weekly limits in the settings."""
    cfg = ops.settings(db)
    daily, weekly = float(cfg["overtime_daily_hours"] or 0), float(cfg["overtime_weekly_hours"] or 0)
    ordinary = ot = 0.0
    for d in sorted(hours_by_day):
        h = hours_by_day[d]
        o = min(h, daily) if daily else h
        if weekly:
            o = min(o, max(0.0, weekly - ordinary))
        ordinary += o
        ot += h - o
    return {"ordinary": round(ordinary, 2), "overtime": round(ot, 2)}


def week_summary(db: Session, start: date) -> list[dict]:
    """Everyone's week: hours per day, ordinary and overtime, what's waiting for approval, and anything odd."""
    entries = week_entries(db, start)
    jobs = {j.id: j for j in db.scalars(select(Job).where(Job.id.in_({e.job_id for e in entries if e.job_id})))} if entries else {}
    by_user: dict[int, list[TimeEntry]] = defaultdict(list)
    for e in entries:
        by_user[e.user_id].append(e)
    leave = defaultdict(float)
    for t in db.scalars(select(TimeOff).where(TimeOff.status == "approved", TimeOff.end_date >= start,
                                              TimeOff.start_date < start + timedelta(days=7))):
        leave[t.user_id] += t.hours or 0
    out = []
    for u in db.scalars(select(User).where(User.active.is_(True)).order_by(User.name, User.email)):
        es = by_user.get(u.id, [])
        if not es and u.role != "field" and not u.trade:
            continue
        days = defaultdict(float)
        for e in es:
            days[local_day(e.start_at).isoformat()] += entry_hours(e)
        ot = overtime(db, days)
        out.append({"user_id": u.id, "name": u.name or u.email, "trade": u.trade, "entries": [entry_out(db, e, jobs) for e in es],
                    "days": {k: round(v, 2) for k, v in days.items()}, "total": round(sum(days.values()), 2), **ot,
                    "leave_hours": leave.get(u.id, 0.0),
                    "open": sum(1 for e in es if e.status == "open"), "submitted": sum(1 for e in es if e.status == "submitted"),
                    "approved": sum(1 for e in es if e.status == "approved"), "flags": sum(1 for e in es if entry_out(db, e, jobs)["flags"])})
    return out


def approve(db: Session, entries: list[TimeEntry], approver: User) -> int:
    n = 0
    for e in entries:
        if e.end_at is None or e.status == "approved":
            continue
        u = db.get(User, e.user_id)
        e.status = "approved"
        e.cost_rate = ops.cost_rate(db, u)
        e.approved_by, e.approved_at = approver.id, now()
        n += 1
    return n


def who_is_working(db: Session) -> list[dict]:
    rows = []
    for e in db.scalars(select(TimeEntry).where(TimeEntry.end_at.is_(None))):
        u = db.get(User, e.user_id)
        rows.append({**entry_out(db, e), "name": (u.name or u.email) if u else "", "trade": u.trade if u else "",
                     "since": local(e.start_at).strftime("%H:%M")})
    return sorted(rows, key=lambda r: r["name"])


def schedule_out(db: Session, s: ScheduleEntry, jobs: dict[int, Job] | None = None) -> dict:
    job = (jobs or {}).get(s.job_id) if jobs is not None else (db.get(Job, s.job_id) if s.job_id else None)
    return {"id": s.id, "user_id": s.user_id, "job_id": s.job_id, "job_no": job.job_no if job else "", "job": job.name if job else "",
            "address": job.address if job else "", "day": s.day.isoformat(), "start": s.start, "end": s.end, "kind": s.kind,
            "notes": s.notes, "published": s.published, "priority": job.priority if job else ""}
