"""The schedule board, timesheet approval, payroll export, time off and who's working now (office side)."""
import csv
import io
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import timesheets as ts
from ..audit import record
from ..auth import current_user
from ..db import get_db
from ..models import Job, ScheduleEntry, TimeEntry, TimeOff, User
from . import get_or_404

router = APIRouter(prefix="/api", tags=["time"])
HHMM = r"^([01]\d|2[0-3]):[0-5]\d$"


# --- schedule ---
@router.get("/schedule")
def schedule(start: date | None = None, days: int = 7, db: Session = Depends(get_db), _: User = Depends(current_user)):
    start = start or ts.week_start(date.today())
    days = max(1, min(days, 31))
    end = start + timedelta(days=days)
    entries = list(db.scalars(select(ScheduleEntry).where(ScheduleEntry.day >= start, ScheduleEntry.day < end)
                              .order_by(ScheduleEntry.day, ScheduleEntry.start)))
    jobs = {j.id: j for j in db.scalars(select(Job).where(Job.id.in_({e.job_id for e in entries if e.job_id})))} if entries else {}
    leave = [{"user_id": t.user_id, "kind": t.kind, "start_date": t.start_date.isoformat(), "end_date": t.end_date.isoformat(),
              "status": t.status} for t in db.scalars(select(TimeOff).where(TimeOff.status != "declined", TimeOff.end_date >= start,
                                                                              TimeOff.start_date < end))]
    people = [{"id": u.id, "name": u.name or u.email, "trade": u.trade, "colour": u.colour, "role": u.role}
              for u in db.scalars(select(User).where(User.active.is_(True)).order_by(User.name, User.email))
              if u.role == "field" or u.trade in ("plumber", "apprentice", "labourer", "supervisor")]
    return {"start": start.isoformat(), "days": days, "people": people, "entries": [ts.schedule_out(db, e, jobs) for e in entries],
            "leave": leave, "unpublished": sum(1 for e in entries if not e.published)}


class ScheduleIn(BaseModel):
    user_id: int
    job_id: int | None = None
    day: date
    start: str = Field(default="07:00", pattern=HHMM)
    end: str = Field(default="15:30", pattern=HHMM)
    kind: str = "work"
    notes: str = ""


def _clashes(db: Session, s: ScheduleEntry) -> list[int]:
    others = db.scalars(select(ScheduleEntry).where(ScheduleEntry.user_id == s.user_id, ScheduleEntry.day == s.day,
                                                    ScheduleEntry.id != (s.id or 0)))
    return [o.id for o in others if o.start < s.end and s.start < o.end]


@router.post("/schedule")
def add_schedule(body: ScheduleIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if body.end <= body.start:
        raise HTTPException(422, "The finish time must be after the start")
    get_or_404(db, User, body.user_id)
    if body.job_id:
        get_or_404(db, Job, body.job_id)
    s = ScheduleEntry(**body.model_dump(), created_by=user.id)
    db.add(s)
    db.flush()
    out = {**ts.schedule_out(db, s), "clashes": _clashes(db, s)}
    db.commit()
    return out


@router.put("/schedule/{sched_id}")
def move_schedule(sched_id: int, body: ScheduleIn, db: Session = Depends(get_db), _: User = Depends(current_user)):
    s = get_or_404(db, ScheduleEntry, sched_id)
    if body.end <= body.start:
        raise HTTPException(422, "The finish time must be after the start")
    changed = (s.user_id, s.day, s.start, s.end, s.job_id) != (body.user_id, body.day, body.start, body.end, body.job_id)
    for k, v in body.model_dump().items():
        setattr(s, k, v)
    if changed:
        s.published = False  # the person needs to see the change
    db.flush()
    out = {**ts.schedule_out(db, s), "clashes": _clashes(db, s)}
    db.commit()
    return out


@router.delete("/schedule/{sched_id}", status_code=204)
def delete_schedule(sched_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    db.delete(get_or_404(db, ScheduleEntry, sched_id))
    db.commit()


class Range(BaseModel):
    start: date
    days: int = Field(default=7, ge=1, le=31)


@router.post("/schedule/publish")
def publish(body: Range, db: Session = Depends(get_db), user: User = Depends(current_user)):
    n = 0
    for s in db.scalars(select(ScheduleEntry).where(ScheduleEntry.day >= body.start, ScheduleEntry.day < body.start + timedelta(days=body.days),
                                                    ScheduleEntry.published.is_(False))):
        s.published = True
        n += 1
    record(db, user.id, "schedule", 0, "publish", after={"start": body.start.isoformat(), "days": body.days, "entries": n})
    db.commit()
    return {"published": n}


class CopyWeek(BaseModel):
    from_start: date
    to_start: date


@router.post("/schedule/copy-week")
def copy_week(body: CopyWeek, db: Session = Depends(get_db), user: User = Depends(current_user)):
    shift = (body.to_start - body.from_start).days
    n = 0
    for s in db.scalars(select(ScheduleEntry).where(ScheduleEntry.day >= body.from_start, ScheduleEntry.day < body.from_start + timedelta(days=7))):
        db.add(ScheduleEntry(user_id=s.user_id, job_id=s.job_id, day=s.day + timedelta(days=shift), start=s.start, end=s.end, kind=s.kind,
                             notes=s.notes, created_by=user.id))
        n += 1
    db.commit()
    return {"copied": n}


# --- timesheets ---
@router.get("/timesheets")
def week(start: date | None = None, db: Session = Depends(get_db), _: User = Depends(current_user)):
    start = ts.week_start(start or date.today())
    return {"start": start.isoformat(), "days": [(start + timedelta(days=i)).isoformat() for i in range(7)],
            "people": ts.week_summary(db, start)}


@router.get("/timesheets/live")
def live(db: Session = Depends(get_db), _: User = Depends(current_user)):
    return ts.who_is_working(db)


class EntryIn(BaseModel):
    user_id: int
    job_id: int | None = None
    task: str = ""
    day: date
    start: str = Field(pattern=HHMM)
    end: str = Field(pattern=HHMM)
    break_minutes: float = Field(default=0, ge=0, le=600)
    notes: str = ""
    reason: str = ""


def _at(day: date, hhmm: str) -> datetime:
    h, m = map(int, hhmm.split(":"))
    return datetime(day.year, day.month, day.day, h, m, tzinfo=ts.TZ)


@router.post("/timesheets/entries")
def add_entry(body: EntryIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    get_or_404(db, User, body.user_id)
    start, end = _at(body.day, body.start), _at(body.day, body.end)
    if end <= start:
        end += timedelta(days=1)  # a night shift
    e = TimeEntry(user_id=body.user_id, job_id=body.job_id, task=body.task, start_at=start, end_at=end, break_minutes=body.break_minutes,
                  notes=body.notes, source="office", status="submitted", edited_reason=body.reason or "Added in the office")
    db.add(e)
    db.flush()
    record(db, user.id, "time_entry", e.id, "create", after=ts.entry_out(db, e))
    db.commit()
    return ts.entry_out(db, e)


@router.put("/timesheets/entries/{time_id}")
def edit_entry(time_id: int, body: EntryIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    e = get_or_404(db, TimeEntry, time_id)
    if not body.reason.strip():
        raise HTTPException(422, "Say why the time is being changed")
    before = ts.entry_out(db, e)
    start, end = _at(body.day, body.start), _at(body.day, body.end)
    if end <= start:
        end += timedelta(days=1)
    e.job_id, e.task, e.start_at, e.end_at, e.break_minutes, e.notes = body.job_id, body.task, start, end, body.break_minutes, body.notes
    e.edited_reason = body.reason.strip()
    if e.status == "approved":
        e.status, e.cost_rate, e.approved_by, e.approved_at = "submitted", None, None, None  # needs approving again
    record(db, user.id, "time_entry", e.id, "update", before, ts.entry_out(db, e))
    db.commit()
    return ts.entry_out(db, e)


@router.delete("/timesheets/entries/{time_id}", status_code=204)
def delete_entry(time_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    e = get_or_404(db, TimeEntry, time_id)
    record(db, user.id, "time_entry", e.id, "delete", before=ts.entry_out(db, e))
    db.delete(e)
    db.commit()


class Decide(BaseModel):
    entry_ids: list[int] = []
    user_id: int | None = None
    start: date | None = None  # with user_id: the whole week


def _pick(db: Session, body: Decide) -> list[TimeEntry]:
    if body.entry_ids:
        return [e for e in (db.get(TimeEntry, i) for i in body.entry_ids) if e is not None]
    if body.user_id and body.start:
        return ts.week_entries(db, ts.week_start(body.start), body.user_id)
    raise HTTPException(422, "Choose entries, or a person and a week")


@router.post("/timesheets/approve")
def approve(body: Decide, db: Session = Depends(get_db), user: User = Depends(current_user)):
    n = ts.approve(db, _pick(db, body), user)
    record(db, user.id, "timesheet", 0, "approve", after={"entries": n, "user_id": body.user_id})
    db.commit()
    return {"approved": n}


@router.post("/timesheets/reject")
def reject(body: Decide, db: Session = Depends(get_db), user: User = Depends(current_user)):
    n = 0
    for e in _pick(db, body):
        if e.end_at is not None:
            e.status, e.cost_rate = "rejected", None
            n += 1
    db.commit()
    return {"rejected": n}


@router.get("/timesheets/payroll.csv")
def payroll(start: date, db: Session = Depends(get_db), _: User = Depends(current_user)):
    """One row per person per day: hours by job, with the week's ordinary and overtime split. Approved time only."""
    start = ts.week_start(start)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Employee", "Date", "Job", "Task", "Start", "Finish", "Break (min)", "Hours", "Status"])
    totals = []
    for p in ts.week_summary(db, start):
        for e in p["entries"]:
            if e["status"] != "approved":
                continue
            w.writerow([p["name"], e["local_day"], f"{e['job_no']} {e['job']}".strip(), e["task"], e["start_local"], e["end_local"] or "",
                        e["break_minutes"], e["hours"], e["status"]])
        totals.append([p["name"], p["total"], p["ordinary"], p["overtime"], p["leave_hours"]])
    w.writerow([])
    w.writerow(["Employee", "Total hours", "Ordinary", "Overtime", "Approved leave hours"])
    w.writerows(totals)
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="timesheets-{start.isoformat()}.csv"'})


# --- time off ---
@router.get("/time-off")
def list_time_off(status: str = "", db: Session = Depends(get_db), _: User = Depends(current_user)):
    stmt = select(TimeOff).order_by(TimeOff.start_date.desc())
    if status:
        stmt = stmt.where(TimeOff.status == status)
    names = {u.id: u.name or u.email for u in db.scalars(select(User))}
    return [{"id": t.id, "user_id": t.user_id, "name": names.get(t.user_id, ""), "kind": t.kind, "start_date": t.start_date.isoformat(),
             "end_date": t.end_date.isoformat(), "hours": t.hours, "notes": t.notes, "status": t.status} for t in db.scalars(stmt.limit(300))]


class TimeOffDecision(BaseModel):
    status: str


@router.put("/time-off/{off_id}")
def decide_time_off(off_id: int, body: TimeOffDecision, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if body.status not in ("approved", "declined", "requested"):
        raise HTTPException(422, "Approve or decline")
    t = get_or_404(db, TimeOff, off_id)
    t.status, t.decided_by = body.status, user.id
    db.commit()
    return {"id": t.id, "status": t.status}


@router.get("/jobs/{job_id}/time")
def job_time(job_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    """Every entry on a job, with hours by person and by task."""
    from collections import defaultdict

    get_or_404(db, Job, job_id)
    names = {u.id: u.name or u.email for u in db.scalars(select(User))}
    entries = list(db.scalars(select(TimeEntry).where(TimeEntry.job_id == job_id).order_by(TimeEntry.start_at.desc())))
    by_person, by_task = defaultdict(float), defaultdict(float)
    rows = []
    for e in entries:
        o = ts.entry_out(db, e)
        rows.append({**o, "name": names.get(e.user_id, "")})
        if e.status != "rejected":
            by_person[names.get(e.user_id, "")] += o["hours"]
            by_task[e.task or "(no task)"] += o["hours"]
    return {"entries": rows[:500], "by_person": [{"name": k, "hours": round(v, 2)} for k, v in sorted(by_person.items(), key=lambda kv: -kv[1])],
            "by_task": [{"task": k, "hours": round(v, 2)} for k, v in sorted(by_task.items(), key=lambda kv: -kv[1])],
            "total": round(sum(by_person.values()), 2)}
