"""Boards: the Monday.com side. A board has groups of items (rows) with typed columns, subitems, an updates
conversation with @mentions, files, an activity log, automations ("when Status changes to Done, notify the owner
and move it to Done"), saved views (table, kanban, calendar, timeline, workload, chart) and forms that add items.

Values are stored per item as {column key: value}; `clean_value` is the one place that decides what a column accepts.
Automations run straight after the change that triggers them (and once a minute for dates and recurring ones), up to
three deep so one automation setting a status can trigger another but a loop can't run away.
"""
import re
import secrets
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (Board, BoardAutomation, BoardColumn, BoardGroup, BoardItem, Customer, ItemActivity, ItemFile, ItemUpdate, Job,
                     OutboundMessage, User)
from .plant import notify
from .timesheets import local_day

COLUMN_TYPES = ["text", "long_text", "status", "person", "date", "timeline", "number", "money", "dropdown", "checkbox", "rating",
                "progress", "job", "customer", "link", "phone", "email", "time", "tags", "files"]
STATUS = [{"key": "todo", "label": "Not started", "colour": "#c4c4c4"}, {"key": "working", "label": "Working on it", "colour": "#fdab3d"},
          {"key": "stuck", "label": "Stuck", "colour": "#e2445c"}, {"key": "done", "label": "Done", "colour": "#00c875", "done": True}]
PRIORITY = [{"key": "low", "label": "Low", "colour": "#579bfc"}, {"key": "medium", "label": "Medium", "colour": "#a25ddc"},
            {"key": "high", "label": "High", "colour": "#fdab3d"}, {"key": "critical", "label": "Critical", "colour": "#e2445c"}]
GROUP_COLOURS = ["#579bfc", "#00c875", "#fdab3d", "#a25ddc", "#e2445c", "#66ccff", "#784bd1", "#ff7575"]
TRIGGERS = ["item_created", "status_change", "column_change", "person_assigned", "date_arrives", "recurring", "subitems_done",
            "update_posted"]
ACTIONS = ["notify", "set_value", "move_group", "create_item", "create_subitems", "set_date_today", "assign", "archive", "email"]
MAX_DEPTH = 3


def _c(key, title, type_, **settings):
    return {"key": key, "title": title, "type": type_, "settings": settings}


TEMPLATES = {
    "blank": {"name": "New board", "groups": ["To do", "Done"],
              "columns": [_c("owner", "Owner", "person"), _c("status", "Status", "status", labels=STATUS), _c("due", "Due", "date")],
              "automations": []},
    "office": {"name": "Office tasks", "groups": ["This week", "Next week", "Done"],
               "columns": [_c("owner", "Owner", "person"), _c("status", "Status", "status", labels=STATUS),
                           _c("priority", "Priority", "status", labels=PRIORITY), _c("due", "Due", "date"), _c("notes", "Notes", "text")],
               "automations": [{"name": "Done goes to Done", "trigger": {"type": "status_change", "column": "status", "to": "done"},
                                "actions": [{"type": "move_group", "group": "Done"}]},
                               {"name": "Remind the owner the day before it's due",
                                "trigger": {"type": "date_arrives", "column": "due", "offset_days": -1},
                                "actions": [{"type": "notify", "to": "column:owner", "text": "Due tomorrow: {item}"}]}]},
    "tenders": {"name": "Tender pipeline", "groups": ["Open tenders", "Submitted", "Closed"],
                "columns": [_c("estimator", "Estimator", "person"),
                            _c("stage", "Stage", "status", labels=[
                                {"key": "received", "label": "Received", "colour": "#c4c4c4"},
                                {"key": "pricing", "label": "Pricing", "colour": "#fdab3d"},
                                {"key": "submitted", "label": "Submitted", "colour": "#579bfc"},
                                {"key": "won", "label": "Won", "colour": "#00c875", "done": True},
                                {"key": "lost", "label": "Lost", "colour": "#e2445c", "done": True}]),
                            _c("builder", "Builder", "text"), _c("value", "Value", "money"), _c("due", "Closes", "date"),
                            _c("job", "Job", "job")],
                "automations": [{"name": "Submitted moves to Submitted", "trigger": {"type": "status_change", "column": "stage", "to": "submitted"},
                                 "actions": [{"type": "move_group", "group": "Submitted"}]},
                                {"name": "Won or lost moves to Closed", "trigger": {"type": "status_change", "column": "stage", "to": "won"},
                                 "actions": [{"type": "move_group", "group": "Closed"},
                                             {"type": "notify", "to": "owner", "text": "Won: {item} ({column:value})"}]},
                                {"name": "Two days before it closes", "trigger": {"type": "date_arrives", "column": "due", "offset_days": -2},
                                 "actions": [{"type": "notify", "to": "column:estimator", "text": "{item} closes in 2 days"}]}]},
    "programme": {"name": "Project programme", "groups": ["Preconstruction", "Rough-in", "Fit-off", "Handover"],
                  "columns": [_c("owner", "Owner", "person"), _c("status", "Status", "status", labels=STATUS),
                              _c("when", "Timeline", "timeline"), _c("trade", "Trade", "dropdown",
                                                                      options=["Plumbing", "Drainage", "Gas", "Civil", "Fire", "Builder"]),
                              _c("progress", "Progress", "progress"), _c("job", "Job", "job")],
                  "automations": [{"name": "All subitems done = Done", "trigger": {"type": "subitems_done"},
                                   "actions": [{"type": "set_value", "column": "status", "value": "done"}]}]},
    "safety": {"name": "Safety: incidents & hazards", "groups": ["New", "Being fixed", "Closed"],
               "columns": [_c("reported_by", "Reported by", "person"), _c("severity", "Severity", "status", labels=PRIORITY),
                           _c("when", "Date", "date"), _c("site", "Site / job", "job"), _c("action_by", "Action owner", "person"),
                           _c("status", "Status", "status", labels=STATUS), _c("photos", "Photos", "files")],
               "automations": [{"name": "Tell the board owner about every new report", "trigger": {"type": "item_created"},
                                "actions": [{"type": "notify", "to": "owner", "text": "New safety report: {item}"},
                                            {"type": "set_date_today", "column": "when"}]},
                               {"name": "Critical: tell the action owner", "trigger": {"type": "status_change", "column": "severity", "to": "critical"},
                                "actions": [{"type": "notify", "to": "column:action_by", "text": "CRITICAL safety item: {item}"}]},
                               {"name": "Closed when done", "trigger": {"type": "status_change", "column": "status", "to": "done"},
                                "actions": [{"type": "move_group", "group": "Closed"}]}]},
    "requests": {"name": "Vehicle, tool & PPE requests", "groups": ["Requested", "Ordered", "Handed over"],
                 "columns": [_c("requested_by", "Requested by", "person"), _c("status", "Status", "status", labels=STATUS),
                             _c("needed", "Needed by", "date"), _c("cost", "Cost", "money"), _c("notes", "Notes", "long_text")],
                 "automations": [{"name": "Done = handed over", "trigger": {"type": "status_change", "column": "status", "to": "done"},
                                  "actions": [{"type": "move_group", "group": "Handed over"},
                                              {"type": "notify", "to": "column:requested_by", "text": "Your request is ready: {item}"}]}]},
    "marketing": {"name": "Marketing calendar", "groups": ["Ideas", "This month", "Published"],
                  "columns": [_c("owner", "Owner", "person"), _c("channel", "Channel", "tags",
                                                                  options=["Facebook", "Instagram", "LinkedIn", "Website", "Email", "Van signage"]),
                              _c("status", "Status", "status", labels=STATUS), _c("publish", "Publish date", "date"),
                              _c("link", "Link", "link")],
                  "automations": []},
    "weekly": {"name": "Weekly yard checklist", "groups": ["This week"],
               "columns": [_c("owner", "Owner", "person"), _c("status", "Status", "status", labels=STATUS), _c("due", "Due", "date")],
               "automations": [{"name": "Every Monday: new yard check", "trigger": {"type": "recurring", "every": "week", "weekday": 0},
                                "actions": [{"type": "create_item", "name": "Yard and store check", "group": "This week"}]}]},
}


# --- values ---
def labels_of(col: BoardColumn) -> list[dict]:
    return (col.settings or {}).get("labels") or (STATUS if col.type == "status" else [])


def done_keys(col: BoardColumn) -> set[str]:
    return {lab["key"] for lab in labels_of(col) if lab.get("done")}


class ValueError_(ValueError):
    pass


def clean_value(db: Session, col: BoardColumn, v):
    """What a column accepts. None / "" clears it."""
    if v in (None, "", []):
        return None
    t = col.type
    if t in ("text", "phone"):
        return str(v)[:500]
    if t == "long_text":
        return str(v)[:10000]
    if t == "email":
        s = str(v).strip()
        if "@" not in s:
            raise ValueError_("That isn't an email address")
        return s[:255]
    if t == "status":
        keys = {lab["key"] for lab in labels_of(col)}
        if v not in keys:
            raise ValueError_(f"{col.title} must be one of {', '.join(lab['label'] for lab in labels_of(col))}")
        return v
    if t == "person":
        ids = [int(x) for x in (v if isinstance(v, list) else [v])]
        found = set(db.scalars(select(User.id).where(User.id.in_(ids))))
        return [i for i in ids if i in found] or None
    if t == "date":
        return date.fromisoformat(str(v)[:10]).isoformat()
    if t == "timeline":
        s, e = date.fromisoformat(str(v["start"])[:10]), date.fromisoformat(str(v["end"])[:10])
        if e < s:
            raise ValueError_("The end is before the start")
        return {"start": s.isoformat(), "end": e.isoformat()}
    if t in ("number", "money"):
        return float(v)
    if t == "progress":
        return max(0, min(100, int(float(v))))
    if t == "rating":
        r = int(v)
        if not 1 <= r <= 5:
            raise ValueError_("1 to 5 stars")
        return r
    if t == "checkbox":
        return bool(v)
    if t == "dropdown":
        opts = (col.settings or {}).get("options") or []
        if opts and v not in opts:
            raise ValueError_(f"{col.title} must be one of {', '.join(opts)}")
        return str(v)
    if t == "tags":
        vals = [str(x)[:50] for x in (v if isinstance(v, list) else [v])]
        return vals
    if t == "job":
        j = db.get(Job, int(v))
        if j is None:
            raise ValueError_("No such job")
        return j.id
    if t == "customer":
        c = db.get(Customer, int(v))
        if c is None:
            raise ValueError_("No such customer")
        return c.id
    if t == "link":
        url = v.get("url") if isinstance(v, dict) else str(v)
        if not re.match(r"^https?://", url or ""):
            url = "https://" + (url or "")
        return {"url": url[:1000], "text": (v.get("text") if isinstance(v, dict) else "") or ""}
    if t == "time":
        return {"seconds": float(v.get("seconds", 0)) if isinstance(v, dict) else float(v), "running_since": None, "by": None}
    if t == "files":
        return None  # files live in item_files
    raise ValueError_(f"Unknown column type {t}")


def show(db: Session, col: BoardColumn, v, names: dict[int, str] | None = None) -> str:
    """A value as text, for activity, exports and notification messages."""
    if v in (None, "", []):
        return ""
    if col.type == "status":
        return next((lab["label"] for lab in labels_of(col) if lab["key"] == v), str(v))
    if col.type == "person":
        names = names or {u.id: u.name or u.email for u in db.scalars(select(User).where(User.id.in_(v)))}
        return ", ".join(names.get(i, "?") for i in v)
    if col.type == "timeline":
        return f"{v['start']} – {v['end']}"
    if col.type == "money":
        return f"${v:,.2f}"
    if col.type == "tags":
        return ", ".join(v)
    if col.type == "link":
        return v.get("text") or v.get("url", "")
    if col.type == "job":
        j = db.get(Job, v)
        return f"{j.job_no or j.quote_no or ''} {j.name}".strip() if j else ""
    if col.type == "customer":
        c = db.get(Customer, v)
        return c.name if c else ""
    if col.type == "checkbox":
        return "Yes" if v else "No"
    if col.type == "time":
        return f"{(v.get('seconds') or 0) / 3600:.2f} h"
    return str(v)


# --- boards ---
def can_see(user: User, b: Board) -> bool:
    if user.role == "admin" or not b.private or b.owner_id == user.id:
        return True
    return user.id in (b.members or [])


def from_template(db: Session, key: str, user: User, name: str = "", job_id: int | None = None) -> Board:
    t = TEMPLATES.get(key)
    if t is None:
        raise ValueError_("Unknown template")
    b = Board(name=name or t["name"], owner_id=user.id, members=[user.id], template=key, job_id=job_id)
    db.add(b)
    db.flush()
    groups = {}
    for i, g in enumerate(t["groups"]):
        bg = BoardGroup(board_id=b.id, title=g, colour=GROUP_COLOURS[i % len(GROUP_COLOURS)], position=i)
        db.add(bg)
        db.flush()
        groups[g] = bg.id
    for i, c in enumerate(t["columns"]):
        db.add(BoardColumn(board_id=b.id, key=c["key"], title=c["title"], type=c["type"], settings=dict(c["settings"]), position=i))
    for a in t["automations"]:
        actions = []
        for act in a["actions"]:
            act = dict(act)
            if "group" in act:
                act["group_id"] = groups.get(act.pop("group"))
            actions.append(act)
        db.add(BoardAutomation(board_id=b.id, name=a["name"], trigger=dict(a["trigger"]), actions=actions))
    db.flush()
    return b


def duplicate(db: Session, b: Board, user: User, with_items: bool) -> Board:
    nb = Board(name=f"{b.name} (copy)", description=b.description, owner_id=user.id, private=b.private, members=list(b.members or []),
               template=b.template)
    db.add(nb)
    db.flush()
    gmap = {}
    for g in db.scalars(select(BoardGroup).where(BoardGroup.board_id == b.id)):
        ng = BoardGroup(board_id=nb.id, title=g.title, colour=g.colour, position=g.position)
        db.add(ng)
        db.flush()
        gmap[g.id] = ng.id
    for c in db.scalars(select(BoardColumn).where(BoardColumn.board_id == b.id)):
        db.add(BoardColumn(board_id=nb.id, key=c.key, title=c.title, type=c.type, settings=dict(c.settings or {}), position=c.position))
    for a in db.scalars(select(BoardAutomation).where(BoardAutomation.board_id == b.id)):
        acts = [{**x, "group_id": gmap.get(x.get("group_id"))} if "group_id" in x else dict(x) for x in a.actions or []]
        db.add(BoardAutomation(board_id=nb.id, name=a.name, trigger=dict(a.trigger or {}), actions=acts, active=a.active))
    if with_items:
        imap = {}
        items = list(db.scalars(select(BoardItem).where(BoardItem.board_id == b.id, BoardItem.archived.is_(False)).order_by(BoardItem.parent_id.is_not(None), BoardItem.id)))
        for it in items:
            ni = BoardItem(board_id=nb.id, group_id=gmap.get(it.group_id), parent_id=imap.get(it.parent_id), name=it.name,
                           values=dict(it.values or {}), position=it.position, created_by=user.id)
            db.add(ni)
            db.flush()
            imap[it.id] = ni.id
    db.flush()
    return nb


def columns(db: Session, board_id: int) -> list[BoardColumn]:
    return list(db.scalars(select(BoardColumn).where(BoardColumn.board_id == board_id).order_by(BoardColumn.position, BoardColumn.id)))


def new_key(db: Session, board_id: int, title: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")[:30] or "col"
    taken = set(db.scalars(select(BoardColumn.key).where(BoardColumn.board_id == board_id)))
    key, n = base, 2
    while key in taken or key in ("name", "group"):
        key, n = f"{base}_{n}", n + 1
    return key


def log(db: Session, item: BoardItem, user_id: int | None, what: str, old: str = "", new: str = "") -> None:
    db.add(ItemActivity(item_id=item.id, user_id=user_id, what=what, old=old[:2000], new=new[:2000]))


def subitems_progress(db: Session, item: BoardItem, cols: list[BoardColumn]) -> int | None:
    subs = list(db.scalars(select(BoardItem).where(BoardItem.parent_id == item.id, BoardItem.archived.is_(False))))
    if not subs:
        return None
    sc = main_status(cols)
    if sc is None:
        return None
    done = done_keys(sc)
    return round(100 * sum(1 for s in subs if (s.values or {}).get(sc.key) in done) / len(subs))


def main_status(cols: list[BoardColumn]) -> BoardColumn | None:
    """The status column that says whether an item is finished: the first with a 'done' label (not Priority or Severity)."""
    return next((c for c in cols if c.type == "status" and done_keys(c)), None)


def is_done(item: BoardItem, cols: list[BoardColumn]) -> bool:
    sc = main_status(cols)
    return bool(sc and (item.values or {}).get(sc.key) in done_keys(sc))


# --- changing items (everything goes through here so the log and automations always run) ---
def create_item(db: Session, b: Board, name: str, user_id: int | None, group_id: int | None = None, values: dict | None = None,
                parent_id: int | None = None, depth: int = 0) -> BoardItem:
    if group_id is None and parent_id is None:
        g = db.scalar(select(BoardGroup).where(BoardGroup.board_id == b.id).order_by(BoardGroup.position, BoardGroup.id).limit(1))
        group_id = g.id if g else None
    last = db.scalar(select(BoardItem.position).where(BoardItem.board_id == b.id, BoardItem.group_id == group_id,
                                                      BoardItem.parent_id == parent_id if parent_id else BoardItem.parent_id.is_(None))
                     .order_by(BoardItem.position.desc()).limit(1)) or 0
    cols = {c.key: c for c in columns(db, b.id)}
    clean = {}
    for k, v in (values or {}).items():
        if k in cols and v not in (None, "", []):
            clean[k] = clean_value(db, cols[k], v)
    item = BoardItem(board_id=b.id, group_id=group_id, parent_id=parent_id, name=name[:300], values=clean, position=last + 1,
                     created_by=user_id)
    db.add(item)
    db.flush()
    log(db, item, user_id, "created")
    for k, v in clean.items():
        if cols[k].type == "person":
            for uid in v:
                if uid != user_id:
                    notify(db, uid, "board", f"You've been assigned: {item.name} ({b.name})", f"/boards/{b.id}?item={item.id}",
                           key=f"assign-{item.id}-{k}-{uid}")
    if parent_id is None:
        run(db, b, "item_created", item, user_id, depth=depth)
    else:
        parent = db.get(BoardItem, parent_id)
        if parent:
            _after_sub_change(db, b, parent, user_id, depth)
    return item


def set_value(db: Session, item: BoardItem, key: str, raw, user_id: int | None, depth: int = 0) -> None:
    b = db.get(Board, item.board_id)
    cols = {c.key: c for c in columns(db, b.id)}
    if key == "name":
        old, item.name = item.name, str(raw)[:300]
        log(db, item, user_id, "name", old, item.name)
        item.updated_at = datetime.now(timezone.utc)
        return
    col = cols.get(key)
    if col is None:
        raise ValueError_("No such column")
    new = clean_value(db, col, raw)
    vals = dict(item.values or {})
    old = vals.get(key)
    if old == new:
        return
    if new is None:
        vals.pop(key, None)
    else:
        vals[key] = new
    item.values = vals
    item.updated_at = datetime.now(timezone.utc)
    log(db, item, user_id, col.title, show(db, col, old), show(db, col, new))
    if col.type == "person":
        for uid in set(new or []) - set(old or []):
            if uid != user_id:
                notify(db, uid, "board", f"You've been assigned: {item.name} ({b.name})", f"/boards/{b.id}?item={item.id}",
                       key=f"assign-{item.id}-{key}-{uid}-{datetime.now(timezone.utc).timestamp():.0f}")
        if set(new or []) - set(old or []):
            run(db, b, "person_assigned", item, user_id, column=key, depth=depth)
    if col.type == "status":
        run(db, b, "status_change", item, user_id, column=key, value=new, depth=depth)
    run(db, b, "column_change", item, user_id, column=key, value=new, depth=depth)
    if item.parent_id:
        parent = db.get(BoardItem, item.parent_id)
        if parent:
            _after_sub_change(db, b, parent, user_id, depth)


def _after_sub_change(db: Session, b: Board, parent: BoardItem, user_id: int | None, depth: int) -> None:
    cols = columns(db, b.id)
    pct = subitems_progress(db, parent, cols)
    for c in cols:
        if c.type == "progress" and pct is not None and (parent.values or {}).get(c.key) != pct:
            parent.values = {**(parent.values or {}), c.key: pct}
    if pct == 100:
        run(db, b, "subitems_done", parent, user_id, depth=depth)


def move(db: Session, item: BoardItem, group_id: int | None, position: float | None, user_id: int | None) -> None:
    if group_id is not None and group_id != item.group_id:
        old = db.get(BoardGroup, item.group_id) if item.group_id else None
        new = db.get(BoardGroup, group_id)
        if new is None or new.board_id != item.board_id:
            raise ValueError_("No such group")
        item.group_id = group_id
        log(db, item, user_id, "group", old.title if old else "", new.title)
    if position is not None:
        item.position = position


def post_update(db: Session, item: BoardItem, user: User, body: str, mentions: list[int], reply_to: int | None = None) -> ItemUpdate:
    b = db.get(Board, item.board_id)
    found = {u.id: u for u in db.scalars(select(User).where(User.active.is_(True)))}
    # @Name in the text counts as a mention too
    for uid, u in found.items():
        first = (u.name or "").split(" ")[0]
        if u.name and (f"@{u.name}" in body or (first and re.search(rf"@{re.escape(first)}\b", body))):
            mentions.append(uid)
    mentions = sorted({m for m in mentions if m in found})
    up = ItemUpdate(item_id=item.id, user_id=user.id, body=body[:10000], mentions=mentions, reply_to=reply_to)
    db.add(up)
    db.flush()
    who = user.name or user.email
    for uid in mentions:
        if uid != user.id:
            notify(db, uid, "mention", f"{who} mentioned you on {item.name}: {body[:120]}", f"/boards/{b.id}?item={item.id}",
                   key=f"mention-{up.id}-{uid}")
    for uid in subscribers(db, item) - set(mentions) - {user.id}:
        notify(db, uid, "board", f"{who} on {item.name}: {body[:120]}", f"/boards/{b.id}?item={item.id}", key=f"upd-{up.id}-{uid}")
    run(db, b, "update_posted", item, user.id)
    return up


def subscribers(db: Session, item: BoardItem) -> set[int]:
    """The people on an item: its creator, everyone in its person columns, and anyone who's written on it."""
    out = {item.created_by} if item.created_by else set()
    for c in columns(db, item.board_id):
        if c.type == "person":
            out |= set((item.values or {}).get(c.key) or [])
    out |= {u for u in db.scalars(select(ItemUpdate.user_id).where(ItemUpdate.item_id == item.id)) if u}
    return out


def timer(db: Session, item: BoardItem, key: str, user: User, start: bool) -> dict:
    col = next((c for c in columns(db, item.board_id) if c.key == key and c.type == "time"), None)
    if col is None:
        raise ValueError_("No time tracking column")
    v = dict((item.values or {}).get(key) or {"seconds": 0, "running_since": None, "by": None})
    now = datetime.now(timezone.utc)
    if start and not v.get("running_since"):
        v["running_since"], v["by"] = now.isoformat(), user.id
    elif not start and v.get("running_since"):
        v["seconds"] = float(v.get("seconds") or 0) + (now - datetime.fromisoformat(v["running_since"])).total_seconds()
        v["running_since"] = None
    item.values = {**(item.values or {}), key: v}
    log(db, item, user.id, col.title, "", "started" if start else f"stopped at {v['seconds'] / 3600:.2f} h")
    return v


# --- automations ---
def _render(db: Session, text: str, item: BoardItem, b: Board) -> str:
    cols = {c.key: c for c in columns(db, b.id)}

    def col(m):
        c = cols.get(m.group(1))
        return show(db, c, (item.values or {}).get(c.key)) if c else ""
    return re.sub(r"\{column:(\w+)\}", col, (text or "").replace("{item}", item.name).replace("{board}", b.name))


def _matches(a: BoardAutomation, event: str, column: str | None, value) -> bool:
    t = a.trigger or {}
    if t.get("type") != event:
        return False
    if event in ("status_change", "column_change", "person_assigned") and t.get("column") and t["column"] != column:
        return False
    if event == "status_change" and t.get("to") not in (None, "", "*") and t["to"] != value:
        return False
    return True


def _condition_ok(db: Session, a: BoardAutomation, item: BoardItem) -> bool:
    cond = (a.trigger or {}).get("only_if")
    if not cond:
        return True
    return (item.values or {}).get(cond.get("column")) == cond.get("equals")


def run(db: Session, b: Board, event: str, item: BoardItem, user_id: int | None, column: str | None = None, value=None,
        depth: int = 0) -> int:
    if depth >= MAX_DEPTH or item.archived:
        return 0
    n = 0
    for a in db.scalars(select(BoardAutomation).where(BoardAutomation.board_id == b.id, BoardAutomation.active.is_(True))):
        if not _matches(a, event, column, value) or not _condition_ok(db, a, item):
            continue
        try:
            for act in a.actions or []:
                do_action(db, b, a, act, item, user_id, depth + 1)
            a.runs += 1
            a.last_run, a.last_error = datetime.now(timezone.utc), ""
            n += 1
        except Exception as e:  # noqa: BLE001 - one bad automation mustn't stop the change being saved
            a.last_error = str(e)[:500]
    return n


def _people(db: Session, b: Board, act: dict, item: BoardItem) -> set[int]:
    to = act.get("to", "owner")
    if to == "owner":
        return {b.owner_id} if b.owner_id else set()
    if to == "creator":
        return {item.created_by} if item.created_by else set()
    if to == "users":
        return {int(x) for x in act.get("user_ids") or []}
    if to.startswith("column:"):
        return set((item.values or {}).get(to.split(":", 1)[1]) or [])
    if to == "subscribers":
        return subscribers(db, item)
    return set()


def do_action(db: Session, b: Board, a: BoardAutomation, act: dict, item: BoardItem, user_id: int | None, depth: int) -> None:
    t = act.get("type")
    if t == "notify":
        text = _render(db, act.get("text") or "{item}", item, b)
        for uid in _people(db, b, act, item):
            notify(db, uid, "board", text, f"/boards/{b.id}?item={item.id}",
                   key=f"auto-{a.id}-{item.id}-{uid}-{datetime.now(timezone.utc):%Y%m%d%H%M%S%f}")
    elif t == "email":
        from . import ops

        addrs = set()
        to = act.get("to", "")
        if to.startswith("column:"):
            v = (item.values or {}).get(to.split(":", 1)[1])
            if v:
                addrs.add(str(v))
        elif "@" in to:
            addrs.add(to)
        for addr in addrs:
            db.add(OutboundMessage(channel="email", to=addr, subject=_render(db, act.get("subject") or "{item}", item, b),
                                   body=_render(db, act.get("text") or "", item, b) + f"\n\n{ops.settings(db)['company_name']}",
                                   send_at=datetime.now(timezone.utc)))
    elif t == "set_value":
        set_value(db, item, act["column"], act.get("value"), None, depth)
    elif t == "set_date_today":
        if not (item.values or {}).get(act["column"]):
            set_value(db, item, act["column"], local_day(datetime.now(timezone.utc)).isoformat(), None, depth)
    elif t == "assign":
        set_value(db, item, act["column"], list(act.get("user_ids") or []), None, depth)
    elif t == "move_group":
        if act.get("group_id"):
            move(db, item, int(act["group_id"]), None, None)
    elif t == "archive":
        item.archived = True
        log(db, item, None, "archived")
    elif t == "create_item":
        target = db.get(Board, int(act["board_id"])) if act.get("board_id") else b
        if target:
            create_item(db, target, _render(db, act.get("name") or "{item}", item, b), None, act.get("group_id"),
                        depth=depth)
    elif t == "create_subitems":
        for name in act.get("names") or []:
            create_item(db, b, name, None, parent_id=item.id, depth=depth)
    else:
        raise ValueError_(f"Unknown action {t}")


def scheduled(db: Session, now: datetime | None = None) -> int:
    """Date-arrives and recurring automations. Safe to call every minute: each fires once per item and date."""
    now = now or datetime.now(timezone.utc)
    today = local_day(now)
    n = 0
    for a in db.scalars(select(BoardAutomation).where(BoardAutomation.active.is_(True))):
        t = a.trigger or {}
        b = db.get(Board, a.board_id)
        if b is None or b.archived:
            continue
        if t.get("type") == "date_arrives":
            target = today - timedelta(days=int(t.get("offset_days") or 0))  # due date that fires today
            key = t.get("column")
            for item in db.scalars(select(BoardItem).where(BoardItem.board_id == b.id, BoardItem.archived.is_(False))):
                v = (item.values or {}).get(key)
                d = v.get("end") if isinstance(v, dict) else v
                if d != target.isoformat():
                    continue
                cols = columns(db, b.id)
                if is_done(item, cols):
                    continue
                marker = f"auto:{a.id}:{today.isoformat()}"
                if db.scalar(select(ItemActivity.id).where(ItemActivity.item_id == item.id, ItemActivity.what == marker)):
                    continue
                db.add(ItemActivity(item_id=item.id, what=marker))
                try:
                    for act in a.actions or []:
                        do_action(db, b, a, act, item, None, 1)
                    a.runs += 1
                    a.last_run, a.last_error = now, ""
                    n += 1
                except Exception as e:  # noqa: BLE001
                    a.last_error = str(e)[:500]
        elif t.get("type") == "recurring":
            last = local_day(a.last_run) if a.last_run else None
            every = t.get("every", "week")
            due = (every == "day" and today.weekday() < 5) or (every == "week" and today.weekday() == int(t.get("weekday", 0))) or \
                  (every == "month" and today.day == int(t.get("day", 1)))
            if not due or last == today:
                continue
            fake = BoardItem(board_id=b.id, name=t.get("name") or a.name, values={})
            try:
                for act in a.actions or []:
                    if act.get("type") == "create_item":
                        target = db.get(Board, int(act["board_id"])) if act.get("board_id") else b
                        create_item(db, target, _render(db, act.get("name") or a.name, fake, b).replace("{date}", today.strftime("%d/%m")),
                                    None, act.get("group_id"), depth=1)
                    elif act.get("type") == "notify":
                        for uid in _people(db, b, act, fake):
                            notify(db, uid, "board", _render(db, act.get("text") or a.name, fake, b), f"/boards/{b.id}",
                                   key=f"auto-{a.id}-{today}-{uid}")
                a.runs += 1
                a.last_run, a.last_error = now, ""
                n += 1
            except Exception as e:  # noqa: BLE001
                a.last_error = str(e)[:500]
                a.last_run = now
    return n


# --- reading ---
def item_out(db: Session, it: BoardItem, files: dict[int, int] | None = None, updates: dict[int, int] | None = None) -> dict:
    return {"id": it.id, "group_id": it.group_id, "parent_id": it.parent_id, "name": it.name, "values": it.values or {},
            "depends_on": it.depends_on or [], "position": it.position, "archived": it.archived, "created_by": it.created_by,
            "created_at": it.created_at.isoformat() if it.created_at else None,
            "updated_at": it.updated_at.isoformat() if it.updated_at else None,
            "files": (files or {}).get(it.id, 0), "updates": (updates or {}).get(it.id, 0)}


def board_out(db: Session, b: Board, archived: bool = False) -> dict:
    from sqlalchemy import func

    stmt = select(BoardItem).where(BoardItem.board_id == b.id)
    if not archived:
        stmt = stmt.where(BoardItem.archived.is_(False))
    items = list(db.scalars(stmt.order_by(BoardItem.position, BoardItem.id)))
    ids = [i.id for i in items]
    files = dict(db.execute(select(ItemFile.item_id, func.count()).where(ItemFile.item_id.in_(ids)).group_by(ItemFile.item_id)).all()) if ids else {}
    updates = dict(db.execute(select(ItemUpdate.item_id, func.count()).where(ItemUpdate.item_id.in_(ids)).group_by(ItemUpdate.item_id)).all()) if ids else {}
    from .models import BoardForm, BoardView

    j = db.get(Job, b.job_id) if b.job_id else None
    return {"id": b.id, "name": b.name, "description": b.description, "owner_id": b.owner_id, "private": b.private,
            "members": b.members or [], "job_id": b.job_id, "job": f"{j.job_no or j.quote_no or ''} {j.name}".strip() if j else "",
            "template": b.template, "archived": b.archived,
            "columns": [{"id": c.id, "key": c.key, "title": c.title, "type": c.type, "settings": c.settings or {}, "position": c.position}
                        for c in columns(db, b.id)],
            "groups": [{"id": g.id, "title": g.title, "colour": g.colour, "position": g.position}
                       for g in db.scalars(select(BoardGroup).where(BoardGroup.board_id == b.id).order_by(BoardGroup.position, BoardGroup.id))],
            "items": [item_out(db, i, files, updates) for i in items],
            "automations": [{"id": a.id, "name": a.name, "trigger": a.trigger, "actions": a.actions, "active": a.active, "runs": a.runs,
                             "last_run": a.last_run.isoformat() if a.last_run else None, "last_error": a.last_error}
                            for a in db.scalars(select(BoardAutomation).where(BoardAutomation.board_id == b.id).order_by(BoardAutomation.id))],
            "views": [{"id": v.id, "name": v.name, "type": v.type, "settings": v.settings or {}}
                      for v in db.scalars(select(BoardView).where(BoardView.board_id == b.id).order_by(BoardView.id))],
            "forms": [{"id": f.id, "token": f.token, "title": f.title, "intro": f.intro, "columns": f.columns, "group_id": f.group_id,
                       "public": f.public, "active": f.active}
                      for f in db.scalars(select(BoardForm).where(BoardForm.board_id == b.id).order_by(BoardForm.id))]}


def summary(db: Session, b: Board) -> dict:
    """For the chart view and board dashboards: counts by status, totals of numbers, work per person, overdue."""
    cols = columns(db, b.id)
    items = list(db.scalars(select(BoardItem).where(BoardItem.board_id == b.id, BoardItem.archived.is_(False), BoardItem.parent_id.is_(None))))
    groups = {g.id: g.title for g in db.scalars(select(BoardGroup).where(BoardGroup.board_id == b.id))}
    names = {u.id: u.name or u.email for u in db.scalars(select(User))}
    today = local_day(datetime.now(timezone.utc)).isoformat()
    out = {"items": len(items), "status": [], "numbers": [], "people": [], "overdue": 0, "done": sum(1 for i in items if is_done(i, cols))}
    for c in cols:
        if c.type == "status":
            counts = {lab["key"]: 0 for lab in labels_of(c)}
            for i in items:
                v = (i.values or {}).get(c.key)
                counts[v or "_blank"] = counts.get(v or "_blank", 0) + 1
            out["status"].append({"column": c.key, "title": c.title, "labels": labels_of(c), "counts": counts})
        elif c.type in ("number", "money"):
            by_group: dict[str, float] = {}
            for i in items:
                v = (i.values or {}).get(c.key)
                if isinstance(v, (int, float)):
                    g = groups.get(i.group_id, "")
                    by_group[g] = by_group.get(g, 0.0) + v
            out["numbers"].append({"column": c.key, "title": c.title, "type": c.type, "total": round(sum(by_group.values()), 2),
                                   "by_group": by_group})
        elif c.type == "person":
            per: dict[int, dict] = {}
            for i in items:
                for uid in (i.values or {}).get(c.key) or []:
                    row = per.setdefault(uid, {"user_id": uid, "name": names.get(uid, "?"), "open": 0, "done": 0})
                    row["done" if is_done(i, cols) else "open"] += 1
            out["people"].append({"column": c.key, "title": c.title, "rows": sorted(per.values(), key=lambda r: -r["open"])})
    for i in items:
        if is_done(i, cols):
            continue
        for c in cols:
            v = (i.values or {}).get(c.key)
            d = v.get("end") if c.type == "timeline" and isinstance(v, dict) else (v if c.type == "date" else None)
            if d and d < today:
                out["overdue"] += 1
                break
    return out


def my_items(db: Session, user: User) -> list[dict]:
    """Everything across the boards with this person in a person column and not done, with its date."""
    out = []
    today = local_day(datetime.now(timezone.utc))
    for b in db.scalars(select(Board).where(Board.archived.is_(False))):
        if not can_see(user, b):
            continue
        cols = columns(db, b.id)
        pcols = [c.key for c in cols if c.type == "person"]
        if not pcols:
            continue
        dcols = [c for c in cols if c.type in ("date", "timeline")]
        scol = main_status(cols)
        groups = {g.id: g.title for g in db.scalars(select(BoardGroup).where(BoardGroup.board_id == b.id))}
        for it in db.scalars(select(BoardItem).where(BoardItem.board_id == b.id, BoardItem.archived.is_(False))):
            vals = it.values or {}
            if not any(user.id in (vals.get(k) or []) for k in pcols) or is_done(it, cols):
                continue
            due = None
            for c in dcols:
                v = vals.get(c.key)
                due = (v.get("end") if isinstance(v, dict) else v) if v else None
                if due:
                    break
            bucket = "no date"
            if due:
                d = date.fromisoformat(due)
                bucket = ("overdue" if d < today else "today" if d == today else "this week" if d <= today + timedelta(days=6 - today.weekday())
                          else "next week" if d <= today + timedelta(days=13 - today.weekday()) else "later")
            st = vals.get(scol.key) if scol else None
            out.append({"board_id": b.id, "board": b.name, "item_id": it.id, "name": it.name, "group": groups.get(it.group_id, ""),
                        "parent_id": it.parent_id, "due": due, "bucket": bucket, "status_column": scol.key if scol else None,
                        "status": st, "status_label": show(db, scol, st) if scol else "",
                        "labels": labels_of(scol) if scol else []})
    order = {"overdue": 0, "today": 1, "this week": 2, "next week": 3, "later": 4, "no date": 5}
    return sorted(out, key=lambda r: (order[r["bucket"]], r["due"] or "9999", r["name"]))


def new_token() -> str:
    return secrets.token_urlsafe(18)
