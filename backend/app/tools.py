"""Tools: every tool, who has it right now, and every hand-over.

Anyone can see the list and who has each tool, and tap their name to ring them. Moving a tool is two-sided so both people
agree: the giver says "I'm giving it to Sam" and Sam confirms "Got it", or Sam asks for it / says "I've got it" and the
holder confirms. The office can assign tools straight to someone, and anyone holding a tool can drop it back at the yard.
Electrical tools carry a test-and-tag date and get reminders.
"""
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Tool, ToolMove, User
from .plant import notify

STATUSES = {"available": "In the yard", "with_person": "With someone", "repair": "Being repaired", "lost": "Missing", "retired": "Retired"}
CATEGORIES = ["Power tool", "Press tool", "Drain camera", "Jetter", "Pipe locator", "Laser / level", "Gas detector", "Test gauge",
              "Pipe threader / cutter", "Welder", "Ladder", "Generator", "Hand tools", "Other"]


def now() -> datetime:
    return datetime.now(timezone.utc)


def _name(u: User | None) -> str:
    return (u.name or u.email) if u else ""


def tool_out(db: Session, t: Tool, users: dict[int, User] | None = None, today: date | None = None) -> dict:
    users = users if users is not None else {u.id: u for u in db.scalars(select(User))}
    today = today or date.today()
    h = users.get(t.holder_id or 0)
    pending = [move_out(m, users) for m in db.scalars(select(ToolMove).where(ToolMove.tool_id == t.id, ToolMove.status == "pending"))]
    return {"id": t.id, "name": t.name, "category": t.category, "asset_no": t.asset_no, "make": t.make, "model": t.model, "serial": t.serial,
            "value": t.value, "status": t.status, "status_label": STATUSES.get(t.status, t.status), "holder_id": t.holder_id, "holder": _name(h),
            "holder_phone": h.phone if h else "", "job_id": t.job_id, "location": t.location,
            "test_tag_due": t.test_tag_due.isoformat() if t.test_tag_due else None,
            "test_tag_overdue": bool(t.test_tag_due and t.test_tag_due < today),
            "service_due": t.service_due.isoformat() if t.service_due else None, "has_photo": bool(t.photo_key), "notes": t.notes,
            "updated_at": t.updated_at.isoformat() if t.updated_at else None, "pending": pending}


def move_out(m: ToolMove, users: dict[int, User]) -> dict:
    return {"id": m.id, "tool_id": m.tool_id, "kind": m.kind, "from_user_id": m.from_user_id, "from": _name(users.get(m.from_user_id or 0)),
            "to_user_id": m.to_user_id, "to": _name(users.get(m.to_user_id or 0)), "location": m.location, "status": m.status,
            "started_by": m.started_by, "note": m.note, "at": m.created_at.isoformat(), "done_at": m.done_at.isoformat() if m.done_at else None}


def _apply(t: Tool, to_user_id: int | None, location: str = "") -> None:
    t.holder_id = to_user_id
    t.status = "with_person" if to_user_id else "available"
    if location or not to_user_id:
        t.location = location or t.location or "Yard"
    t.updated_at = now()


def request(db: Session, t: Tool, user: User, note: str = "") -> ToolMove:
    """'I need it': the holder is told, with the requester's number, and confirms once they've handed it over."""
    if t.holder_id == user.id:
        raise ValueError("You've already got it")
    m = db.scalar(select(ToolMove).where(ToolMove.tool_id == t.id, ToolMove.to_user_id == user.id, ToolMove.status == "pending"))
    if m is None:
        m = ToolMove(tool_id=t.id, kind="request", from_user_id=t.holder_id, to_user_id=user.id, status="pending", started_by=user.id, note=note)
        db.add(m)
        db.flush()
    who = f"{_name(user)}{f' ({user.phone})' if user.phone else ''}"
    if t.holder_id:
        notify(db, t.holder_id, "tool", f"{who} needs the {t.name}. Give them a call to meet up, then confirm the hand-over in Tools.",
               "/field/tools", key=f"toolreq-{m.id}")
    return m


def _pending_handover(db: Session, t: Tool, to_user_id: int) -> ToolMove | None:
    return db.scalar(select(ToolMove).where(ToolMove.tool_id == t.id, ToolMove.kind == "handover", ToolMove.to_user_id == to_user_id,
                                            ToolMove.from_user_id == t.holder_id, ToolMove.status == "pending"))


def give(db: Session, t: Tool, actor: User, to: User, note: str = "", lat=None, lng=None) -> ToolMove:
    """The holder hands it to someone: it moves when they confirm they've got it."""
    if to.id == t.holder_id:
        raise ValueError(f"{_name(to)} already has it")
    m = _pending_handover(db, t, to.id)
    if m:
        return m
    m = ToolMove(tool_id=t.id, kind="handover", from_user_id=t.holder_id, to_user_id=to.id, status="pending", started_by=actor.id, note=note,
                 lat=lat, lng=lng)
    db.add(m)
    db.flush()
    notify(db, to.id, "tool", f"{_name(actor)} is handing you the {t.name}. Tap to confirm you've got it.", "/field/tools", key=f"toolgive-{m.id}")
    return m


def take(db: Session, t: Tool, user: User, note: str = "", lat=None, lng=None) -> ToolMove:
    """'I've got it now' from the person who picked it up: the holder (if anyone) confirms; from the yard it's straight away."""
    if t.holder_id == user.id:
        raise ValueError("You've already got it")
    m = _pending_handover(db, t, user.id)
    if m:
        return m  # tapped twice: still waiting on the same confirmation
    m = ToolMove(tool_id=t.id, kind="handover", from_user_id=t.holder_id, to_user_id=user.id, status="pending", started_by=user.id, note=note,
                 lat=lat, lng=lng)
    db.add(m)
    db.flush()
    if not t.holder_id:
        finish(db, t, m)
    else:
        notify(db, t.holder_id, "tool", f"{_name(user)} says they've got the {t.name} from you. Tap to confirm.", "/field/tools", key=f"tooltake-{m.id}")
    return m


def finish(db: Session, t: Tool, m: ToolMove) -> None:
    m.status, m.done_at = "done", now()
    _apply(t, m.to_user_id)
    for other in db.scalars(select(ToolMove).where(ToolMove.tool_id == t.id, ToolMove.status == "pending", ToolMove.id != m.id)):
        if other.to_user_id == m.to_user_id or other.from_user_id != m.to_user_id:
            other.status = "cancelled"  # the old requests are out of date now it's moved
        else:
            other.from_user_id = m.to_user_id  # still wanted: the new holder is the one to ask


def confirm(db: Session, m: ToolMove, user: User, office: bool = False) -> None:
    """The other person agrees. For a request, the holder confirms once they've handed it over."""
    t = db.get(Tool, m.tool_id)
    if m.status != "pending":
        raise ValueError("That's already been dealt with")
    allowed = {m.from_user_id, m.to_user_id} - {m.started_by}
    if user.id not in allowed and not office:
        raise PermissionError("It's for the other person to confirm")
    finish(db, t, m)
    other = m.started_by if m.started_by != user.id else (m.to_user_id if m.to_user_id != user.id else m.from_user_id)
    if other:
        notify(db, other, "tool", f"The {t.name} is now with {_name(db.get(User, m.to_user_id))}.", "/field/tools", key=f"tooldone-{m.id}")


def decline(db: Session, m: ToolMove, user: User) -> None:
    if user.id not in (m.from_user_id, m.to_user_id, m.started_by):
        raise PermissionError("Not yours to decline")
    m.status, m.done_at = ("cancelled" if user.id == m.started_by else "declined"), now()


def return_to_yard(db: Session, t: Tool, user: User, location: str = "Yard", office: bool = False) -> ToolMove:
    if t.holder_id not in (user.id, None) and not office:
        raise PermissionError("Only the person who has it (or the office) can drop it back")
    m = ToolMove(tool_id=t.id, kind="return", from_user_id=t.holder_id, to_user_id=None, location=location, status="done", started_by=user.id,
                 done_at=now())
    db.add(m)
    _apply(t, None, location)
    for other in db.scalars(select(ToolMove).where(ToolMove.tool_id == t.id, ToolMove.status == "pending")):
        other.from_user_id = None  # it's in the yard now: whoever wanted it can grab it
    db.flush()
    return m


def assign(db: Session, t: Tool, actor: User, to_user_id: int | None, location: str = "") -> ToolMove:
    """The office sets who has it straight away (stocktake, new tool, someone leaving)."""
    m = ToolMove(tool_id=t.id, kind="assign", from_user_id=t.holder_id, to_user_id=to_user_id, location=location, status="done",
                 started_by=actor.id, done_at=now())
    db.add(m)
    _apply(t, to_user_id, location)
    if to_user_id and to_user_id != actor.id:
        notify(db, to_user_id, "tool", f"The {t.name} is now down to you in Tools.", "/field/tools", key=f"toolassign-{m.id}")
    db.flush()
    return m


def daily(db: Session, today: date | None = None) -> int:
    """Test-and-tag due within 14 days (to the holder and the office), and hand-overs left unconfirmed for 2 days."""
    today = today or date.today()
    n = 0
    office = [u.id for u in db.scalars(select(User).where(User.active.is_(True), User.role == "admin"))]
    for t in db.scalars(select(Tool).where(Tool.test_tag_due.is_not(None), Tool.test_tag_due <= today + timedelta(days=14),
                                           Tool.status.not_in(("retired", "lost")))):
        when = "is overdue for" if t.test_tag_due < today else f"is due for test and tag on {t.test_tag_due:%d/%m}"
        for uid in ({t.holder_id} if t.holder_id else set()) | set(office):
            if notify(db, uid, "tool", f"The {t.name} ({t.asset_no or 'no tag no.'}) {when} test and tag." if "overdue" in when
                      else f"The {t.name} ({t.asset_no or 'no tag no.'}) {when}.", "/tools", key=f"tt-{t.id}-{t.test_tag_due}-{uid}"):
                n += 1
    stale = now() - timedelta(days=2)
    for m in db.scalars(select(ToolMove).where(ToolMove.status == "pending", ToolMove.created_at < stale)):
        t = db.get(Tool, m.tool_id)
        for uid in {m.from_user_id, m.to_user_id} - {None}:
            notify(db, uid, "tool", f"The {t.name if t else 'tool'} hand-over hasn't been confirmed yet.", "/field/tools", key=f"toolstale-{m.id}-{uid}")
    return n
