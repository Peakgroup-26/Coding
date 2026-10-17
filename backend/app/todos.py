"""Daily to-do lists.

Everyone can keep their own list for the day. Supervisors, foremen, managers and the office can set lists for the
team (a manager for the people who report to them). Before someone clocks off, every task on their list for that
day has to be ticked off, or marked "couldn't finish" with a reason, which goes back to whoever set it.
"""
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import features
from . import timesheets as ts
from .models import DailyTask, EmployeeProfile, Job, User
from .plant import notify

LEADS = ("supervisor", "foreman", "project manager", "manager")


def _name(u: User | None) -> str:
    return (u.name or u.email) if u else ""


def leads_team(db: Session, user: User) -> bool:
    """Can set lists for other people (not just their own)."""
    if user.role == "admin" or user.trade in LEADS:
        return True
    if user.role != "field" and features.level(db, user, "todos") == "edit":
        return True
    return db.scalar(select(EmployeeProfile.id).where(EmployeeProfile.manager_id == user.id).limit(1)) is not None


def can_set_for(db: Session, user: User, target_id: int) -> bool:
    if target_id == user.id:
        return True
    if user.role == "admin" or user.trade in LEADS or (user.role != "field" and features.level(db, user, "todos") == "edit"):
        return True
    p = db.scalar(select(EmployeeProfile).where(EmployeeProfile.user_id == target_id))
    return bool(p and p.manager_id == user.id)


def team(db: Session, user: User) -> list[User]:
    """The people this person can set lists for, themselves first."""
    people = [u for u in db.scalars(select(User).where(User.active.is_(True)).order_by(User.name)) if u.id != user.id and can_set_for(db, user, u.id)]
    return [user] + people


def today() -> date:
    return ts.local_day(ts.now())


def work_day(db: Session, user: User) -> date:
    """The day whose list counts: the day they clocked on (a night shift finishing after midnight still counts yesterday)."""
    cur = ts.open_entry(db, user.id)
    return ts.local_day(cur.start_at) if cur else today()


def task_out(t: DailyTask, users: dict[int, User], jobs: dict[int, Job] | None = None) -> dict:
    j = (jobs or {}).get(t.job_id or 0)
    return {"id": t.id, "user_id": t.user_id, "user": _name(users.get(t.user_id)), "day": t.day.isoformat(), "text": t.text, "job_id": t.job_id,
            "job": f"{j.job_no or ''} {j.name}".strip() if j else "", "set_by_id": t.set_by, "set_by": _name(users.get(t.set_by or 0)),
            "status": t.status, "comment": t.comment, "done_at": t.done_at.isoformat() if t.done_at else None, "carried_from": t.carried_from}


def lists(db: Session, user_ids: list[int], day: date) -> list[DailyTask]:
    if not user_ids:
        return []
    return list(db.scalars(select(DailyTask).where(DailyTask.user_id.in_(user_ids), DailyTask.day == day)
                           .order_by(DailyTask.user_id, DailyTask.position, DailyTask.id)))


def add(db: Session, actor: User, user_ids: list[int], texts: list[str], day: date, job_id: int | None = None) -> list[DailyTask]:
    out = []
    for uid in dict.fromkeys(user_ids):
        if not can_set_for(db, actor, uid):
            raise PermissionError("You can only set to-dos for yourself and the people you look after")
        pos = len(lists(db, [uid], day))
        made = []
        for text in texts:
            text = text.strip()
            if not text:
                continue
            t = DailyTask(user_id=uid, day=day, text=text[:500], job_id=job_id, set_by=actor.id, position=pos)
            pos += 1
            db.add(t)
            made.append(t)
        db.flush()
        if made and uid != actor.id:
            when = "today" if day == today() else "tomorrow" if day == today() + timedelta(days=1) else day.strftime("%a %d/%m")
            what = made[0].text if len(made) == 1 else f"{len(made)} to-dos"
            notify(db, uid, "todo", f"{_name(actor)} set {what} for you {when}.", "/field", key=f"todo-{made[0].id}")
        out += made
    return out


def set_status(db: Session, actor: User, t: DailyTask, status: str, comment: str = "") -> DailyTask:
    if actor.id != t.user_id and not can_set_for(db, actor, t.user_id):
        raise PermissionError("That's not on your list")
    comment = comment.strip()
    if status == "not_done" and len(comment) < 3:
        raise ValueError("Say why it couldn't be finished")
    t.status = status
    t.comment = comment if status in ("done", "not_done") else ""  # a note on a finished task is optional
    t.done_at = datetime.now(timezone.utc) if status != "open" else None
    if status == "not_done" and t.set_by and t.set_by != actor.id:
        notify(db, t.set_by, "todo", f"{_name(actor)} couldn't finish \"{t.text}\": {comment}", "/todos", key=f"todo-nd-{t.id}-{int(t.done_at.timestamp())}")
    return t


def unresolved(db: Session, user: User, day: date | None = None) -> list[DailyTask]:
    """Tasks still open: neither ticked off nor explained."""
    day = day or work_day(db, user)
    return [t for t in lists(db, [user.id], day) if t.status == "open"]


def clock_off_problems(db: Session, user: User) -> list[str]:
    left = unresolved(db, user)
    if not left:
        return []
    names = ", ".join(f"\"{t.text}\"" for t in left[:3]) + (f" and {len(left) - 3} more" if len(left) > 3 else "")
    return [f"Before you clock off, tick off your to-dos or say why you couldn't finish them: {names}."]


def carry_over(db: Session, actor: User, from_day: date, to_day: date, user_ids: list[int]) -> int:
    """Put yesterday's unfinished tasks (not done, or never touched) on the new day's list."""
    n = 0
    already = {t.carried_from for t in lists(db, user_ids, to_day) if t.carried_from}
    for t in lists(db, user_ids, from_day):
        if t.status == "done" or t.id in already or not can_set_for(db, actor, t.user_id):
            continue
        db.add(DailyTask(user_id=t.user_id, day=to_day, text=t.text, job_id=t.job_id, set_by=t.set_by or actor.id, carried_from=t.id,
                         position=100 + t.position))
        n += 1
    db.flush()
    return n
