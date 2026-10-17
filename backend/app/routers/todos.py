"""Daily to-do lists (/api/field/todos): my list on the phone, and the team's lists for supervisors, foremen and the office."""
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import todos as td
from ..auth import current_user
from ..db import get_db
from ..models import DailyTask, Job, User
from . import get_or_404

router = APIRouter(prefix="/api/field", tags=["todos"])


def _maps(db: Session, tasks: list[DailyTask]) -> tuple[dict[int, User], dict[int, Job]]:
    users = {u.id: u for u in db.scalars(select(User))}
    ids = {t.job_id for t in tasks if t.job_id}
    jobs = {j.id: j for j in db.scalars(select(Job).where(Job.id.in_(ids)))} if ids else {}
    return users, jobs


@router.get("/todos")
def my_todos(day: date | None = None, db: Session = Depends(get_db), user: User = Depends(current_user)):
    day = day or td.work_day(db, user)
    tasks = td.lists(db, [user.id], day)
    users, jobs = _maps(db, tasks)
    return {"day": day.isoformat(), "tasks": [td.task_out(t, users, jobs) for t in tasks], "open": sum(1 for t in tasks if t.status == "open"),
            "leads_team": td.leads_team(db, user)}


class AddIn(BaseModel):
    texts: list[str] = Field(min_length=1, max_length=50)
    user_ids: list[int] = []
    day: date | None = None
    job_id: int | None = None


@router.post("/todos")
def add_todos(body: AddIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    day = body.day or td.today()
    if day < td.today() - timedelta(days=1):
        raise HTTPException(422, "That day has gone")
    if body.job_id:
        get_or_404(db, Job, body.job_id)
    try:
        made = td.add(db, user, body.user_ids or [user.id], body.texts, day, body.job_id)
    except PermissionError as e:
        raise HTTPException(403, str(e))
    if not made:
        raise HTTPException(422, "Write the task")
    db.commit()
    users, jobs = _maps(db, made)
    return [td.task_out(t, users, jobs) for t in made]


class StatusIn(BaseModel):
    status: str = Field(pattern="^(open|done|not_done)$")
    comment: str = Field(default="", max_length=2000)


@router.patch("/todos/{task_id}")
def set_status(task_id: int, body: StatusIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    t = get_or_404(db, DailyTask, task_id)
    try:
        td.set_status(db, user, t, body.status, body.comment)
    except PermissionError:
        raise HTTPException(404, "Not found")
    except ValueError as e:
        raise HTTPException(422, str(e))
    db.commit()
    users, jobs = _maps(db, [t])
    return td.task_out(t, users, jobs)


@router.delete("/todos/{task_id}", status_code=204)
def delete_todo(task_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    t = get_or_404(db, DailyTask, task_id)
    mine_to_remove = t.set_by == user.id or (t.user_id != user.id and td.can_set_for(db, user, t.user_id))
    if not mine_to_remove:
        raise HTTPException(403, "Someone else set this one: tick it off, or say why you couldn't finish it")
    db.delete(t)
    db.commit()


@router.get("/todos/team")
def team_todos(day: date | None = None, db: Session = Depends(get_db), user: User = Depends(current_user)):
    day = day or td.today()
    people = td.team(db, user)
    tasks = td.lists(db, [u.id for u in people], day)
    users, jobs = _maps(db, tasks)
    by: dict[int, list[dict]] = {}
    for t in tasks:
        by.setdefault(t.user_id, []).append(td.task_out(t, users, jobs))
    rows = []
    for u in people:
        ts_ = by.get(u.id, [])
        rows.append({"user_id": u.id, "name": u.name or u.email, "trade": u.trade, "phone": u.phone, "tasks": ts_,
                     "done": sum(1 for x in ts_ if x["status"] == "done"), "not_done": sum(1 for x in ts_ if x["status"] == "not_done"),
                     "open": sum(1 for x in ts_ if x["status"] == "open")})
    return {"day": day.isoformat(), "people": rows, "leads_team": td.leads_team(db, user)}


class CarryIn(BaseModel):
    from_day: date
    to_day: date
    user_ids: list[int]


@router.post("/todos/carry")
def carry(body: CarryIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    n = td.carry_over(db, user, body.from_day, body.to_day, body.user_ids)
    db.commit()
    return {"carried": n}


class ParseIn(BaseModel):
    text: str = Field(min_length=2, max_length=8000)
    day: date | None = None


@router.post("/todos/parse")
def parse(body: ParseIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """What a supervisor said, split into a list per person, for them to check before saving."""
    return td.parse_spoken(db, user, body.text, body.day)


class BatchTask(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    job_id: int | None = None


class BatchList(BaseModel):
    user_id: int
    tasks: list[BatchTask] = Field(min_length=1, max_length=50)


class BatchIn(BaseModel):
    day: date
    lists: list[BatchList] = Field(min_length=1, max_length=100)


@router.post("/todos/batch")
def add_batch(body: BatchIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if body.day < td.today() - timedelta(days=1):
        raise HTTPException(422, "That day has gone")
    made = []
    try:
        for li in body.lists:
            by_job: dict[int | None, list[str]] = {}
            for t in li.tasks:
                by_job.setdefault(t.job_id if t.job_id and db.get(Job, t.job_id) else None, []).append(t.text)
            for jid, texts in by_job.items():
                made += td.add(db, user, [li.user_id], texts, body.day, jid)
    except PermissionError as e:
        db.rollback()
        raise HTTPException(403, str(e))
    db.commit()
    return {"added": len(made), "people": len({t.user_id for t in made})}


# --- the management report (behind the To-do lists feature; on /api/field so supervisors on the phone can open it too) ---


def _range(start: date | None, end: date | None, group: str) -> tuple[date, date]:
    end = end or td.today()
    if start is None:
        start = end.replace(day=1) if group == "month" else end - timedelta(days=end.weekday())
    if start > end:
        raise HTTPException(422, "The start is after the end")
    if (end - start).days > 800:
        raise HTTPException(422, "Pick up to about two years")
    return start, end


@router.get("/todos/report")
def report(start: date | None = None, end: date | None = None, group: str = "week", db: Session = Depends(get_db),
           user: User = Depends(current_user)):
    if group not in ("week", "month"):
        raise HTTPException(422, "By week or by month")
    s, e = _range(start, end, group)
    return td.report(db, user, s, e, group)


@router.get("/todos/report.xlsx")
def report_xlsx(start: date | None = None, end: date | None = None, group: str = "week", db: Session = Depends(get_db),
                user: User = Depends(current_user)):
    from fastapi import Response

    if group not in ("week", "month"):
        raise HTTPException(422, "By week or by month")
    s, e = _range(start, end, group)
    data = td.report_xlsx(td.report(db, user, s, e, group))
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="todo-performance-{s}-to-{e}.xlsx"'})
