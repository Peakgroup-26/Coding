"""Boards (Monday.com style) at /api/boards, My work at /api/my-work, the phone's /api/field/my-work and public board forms."""
import io
import mimetypes
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import boards as bd
from .. import config, hr, storage
from ..auth import current_user
from ..db import get_db
from ..models import (Board, BoardAutomation, BoardColumn, BoardForm, BoardGroup, BoardItem, BoardView, ItemActivity, ItemFile, ItemUpdate,
                      User)
from . import get_or_404

router = APIRouter(prefix="/api", tags=["boards"])
field = APIRouter(prefix="/api/field/my-work", tags=["boards"])
public = APIRouter(prefix="/api/public/forms", tags=["public"])


def _board(db: Session, board_id: int, user: User) -> Board:
    b = db.get(Board, board_id)
    if b is None or not bd.can_see(user, b) or user.role == "field":
        raise HTTPException(404, "Board not found")
    return b


def _item(db: Session, item_id: int, user: User) -> tuple[BoardItem, Board]:
    it = db.get(BoardItem, item_id)
    if it is None:
        raise HTTPException(404, "Item not found")
    return it, _board(db, it.board_id, user)


def _err(fn):
    try:
        return fn()
    except (bd.ValueError_, ValueError, TypeError, KeyError) as e:
        raise HTTPException(422, str(e) or "That value doesn't fit this column")


# --- boards ---
@router.get("/boards")
def list_boards(db: Session = Depends(get_db), user: User = Depends(current_user)):
    counts = dict(db.execute(select(BoardItem.board_id, func.count()).where(BoardItem.archived.is_(False), BoardItem.parent_id.is_(None))
                             .group_by(BoardItem.board_id)).all())
    last = dict(db.execute(select(BoardItem.board_id, func.max(BoardItem.updated_at)).group_by(BoardItem.board_id)).all())
    names = {u.id: u.name or u.email for u in db.scalars(select(User))}
    return [{"id": b.id, "name": b.name, "description": b.description, "template": b.template, "private": b.private,
             "owner": names.get(b.owner_id or 0, ""), "items": counts.get(b.id, 0), "job_id": b.job_id, "archived": b.archived,
             "updated_at": last[b.id].isoformat() if last.get(b.id) else b.created_at.isoformat()}
            for b in db.scalars(select(Board).order_by(Board.archived, Board.name)) if bd.can_see(user, b)]


@router.get("/boards/templates")
def templates(_: User = Depends(current_user)):
    return [{"key": k, "name": t["name"], "groups": t["groups"], "columns": [c["title"] for c in t["columns"]],
             "automations": [a["name"] for a in t["automations"]]} for k, t in bd.TEMPLATES.items()]


class BoardIn(BaseModel):
    template: str = "blank"
    name: str = ""
    job_id: int | None = None


@router.post("/boards")
def add_board(body: BoardIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    b = _err(lambda: bd.from_template(db, body.template, user, body.name.strip(), body.job_id))
    db.commit()
    return bd.board_out(db, b)


@router.get("/boards/{board_id}")
def get_board(board_id: int, archived: bool = False, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return bd.board_out(db, _board(db, board_id, user), archived)


class BoardPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    private: bool | None = None
    members: list[int] | None = None
    job_id: int | None = None
    archived: bool | None = None


@router.patch("/boards/{board_id}")
def edit_board(board_id: int, body: BoardPatch, db: Session = Depends(get_db), user: User = Depends(current_user)):
    b = _board(db, board_id, user)
    data = body.model_dump(exclude_unset=True)
    if "private" in data and b.owner_id not in (user.id, None) and user.role != "admin":
        raise HTTPException(403, "Only the board's owner can change who sees it")
    for k, v in data.items():
        setattr(b, k, v)
    if b.private and b.owner_id and b.owner_id not in (b.members or []):
        b.members = [*(b.members or []), b.owner_id]
    db.commit()
    return bd.board_out(db, b)


@router.delete("/boards/{board_id}", status_code=204)
def delete_board(board_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    b = _board(db, board_id, user)
    if b.owner_id not in (user.id, None) and user.role != "admin":
        raise HTTPException(403, "Only the board's owner can delete it")
    for f in db.scalars(select(ItemFile).join(BoardItem, ItemFile.item_id == BoardItem.id).where(BoardItem.board_id == b.id)):
        storage.delete(f.key)
    db.delete(b)
    db.commit()


class DuplicateIn(BaseModel):
    with_items: bool = True


@router.post("/boards/{board_id}/duplicate")
def duplicate(board_id: int, body: DuplicateIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    nb = bd.duplicate(db, _board(db, board_id, user), user, body.with_items)
    db.commit()
    return {"id": nb.id}


@router.get("/boards/{board_id}/summary")
def board_summary(board_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return bd.summary(db, _board(db, board_id, user))


@router.get("/boards/{board_id}/export.xlsx")
def export(board_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    from openpyxl import Workbook
    from openpyxl.styles import Font

    b = _board(db, board_id, user)
    cols = bd.columns(db, b.id)
    names = {u.id: u.name or u.email for u in db.scalars(select(User))}
    groups = {g.id: g.title for g in db.scalars(select(BoardGroup).where(BoardGroup.board_id == b.id))}
    wb = Workbook()
    ws = wb.active
    ws.title = b.name[:31] or "Board"
    ws.append(["Group", "Item", "Subitem of", *[c.title for c in cols if c.type != "files"]])
    for cell in ws[1]:
        cell.font = Font(bold=True)
    items = list(db.scalars(select(BoardItem).where(BoardItem.board_id == b.id, BoardItem.archived.is_(False))
                            .order_by(BoardItem.group_id, BoardItem.position)))
    byid = {i.id: i for i in items}
    for it in sorted(items, key=lambda i: (groups.get(i.group_id or byid.get(i.parent_id, i).group_id, ""), i.parent_id or i.id, i.parent_id is not None, i.position)):
        parent = byid.get(it.parent_id)
        ws.append([groups.get(it.group_id or (parent.group_id if parent else 0), ""), it.name, parent.name if parent else "",
                   *[(it.values or {}).get(c.key) if c.type in ("number", "money", "progress", "rating") else bd.show(db, c, (it.values or {}).get(c.key), names)
                     for c in cols if c.type != "files"]])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    safe = "".join(ch if ch.isalnum() or ch in " -_" else "_" for ch in b.name)[:60] or "board"
    return StreamingResponse(buf, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": f'attachment; filename="{safe}.xlsx"'})


# --- columns and groups ---
class ColumnIn(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    type: str = "text"
    settings: dict = {}


@router.post("/boards/{board_id}/columns")
def add_column(board_id: int, body: ColumnIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    b = _board(db, board_id, user)
    if body.type not in bd.COLUMN_TYPES:
        raise HTTPException(422, f"Column type must be one of {', '.join(bd.COLUMN_TYPES)}")
    settings = dict(body.settings)
    if body.type == "status" and not settings.get("labels"):
        settings["labels"] = bd.STATUS
    last = db.scalar(select(func.max(BoardColumn.position)).where(BoardColumn.board_id == b.id)) or 0
    c = BoardColumn(board_id=b.id, key=bd.new_key(db, b.id, body.title), title=body.title, type=body.type, settings=settings, position=last + 1)
    db.add(c)
    db.commit()
    return {"id": c.id, "key": c.key}


class ColumnPatch(BaseModel):
    title: str | None = None
    settings: dict | None = None
    position: int | None = None


@router.patch("/boards/columns/{col_id}")
def edit_column(col_id: int, body: ColumnPatch, db: Session = Depends(get_db), user: User = Depends(current_user)):
    c = get_or_404(db, BoardColumn, col_id)
    _board(db, c.board_id, user)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(c, k, v)
    db.commit()
    return {"id": c.id}


@router.delete("/boards/columns/{col_id}", status_code=204)
def delete_column(col_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    c = get_or_404(db, BoardColumn, col_id)
    _board(db, c.board_id, user)
    for it in db.scalars(select(BoardItem).where(BoardItem.board_id == c.board_id)):
        if c.key in (it.values or {}):
            it.values = {k: v for k, v in it.values.items() if k != c.key}
    db.delete(c)
    db.commit()


class GroupIn(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    colour: str = ""
    position: int | None = None


@router.post("/boards/{board_id}/groups")
def add_group(board_id: int, body: GroupIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    b = _board(db, board_id, user)
    n = db.scalar(select(func.count()).select_from(BoardGroup).where(BoardGroup.board_id == b.id)) or 0
    g = BoardGroup(board_id=b.id, title=body.title, colour=body.colour or bd.GROUP_COLOURS[n % len(bd.GROUP_COLOURS)],
                   position=body.position if body.position is not None else -1)  # new groups go on top, as in Monday
    db.add(g)
    db.commit()
    return {"id": g.id}


@router.patch("/boards/groups/{group_id}")
def edit_group(group_id: int, body: GroupIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    g = get_or_404(db, BoardGroup, group_id)
    _board(db, g.board_id, user)
    g.title = body.title
    if body.colour:
        g.colour = body.colour
    if body.position is not None:
        g.position = body.position
    db.commit()
    return {"id": g.id}


@router.delete("/boards/groups/{group_id}", status_code=204)
def delete_group(group_id: int, move_to: int | None = None, db: Session = Depends(get_db), user: User = Depends(current_user)):
    g = get_or_404(db, BoardGroup, group_id)
    _board(db, g.board_id, user)
    for it in db.scalars(select(BoardItem).where(BoardItem.group_id == g.id)):
        if move_to:
            it.group_id = move_to
        else:
            db.delete(it)
    db.delete(g)
    db.commit()


# --- items ---
class ItemIn(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    group_id: int | None = None
    parent_id: int | None = None
    values: dict = {}


@router.post("/boards/{board_id}/items")
def add_item(board_id: int, body: ItemIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    b = _board(db, board_id, user)
    if body.parent_id:
        p = db.get(BoardItem, body.parent_id)
        if p is None or p.board_id != b.id or p.parent_id:
            raise HTTPException(422, "Subitems go one level deep")
    it = _err(lambda: bd.create_item(db, b, body.name, user.id, body.group_id, body.values, body.parent_id))
    db.commit()
    return bd.item_out(db, it)


@router.get("/boards/items/{item_id}")
def item_detail(item_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    it, b = _item(db, item_id, user)
    return _detail(db, it, b)


def _detail(db: Session, it: BoardItem, b: Board) -> dict:
    names = {u.id: u.name or u.email for u in db.scalars(select(User))}
    return {**bd.item_out(db, it), "board_id": b.id, "board": b.name,
            "subitems": [bd.item_out(db, s) for s in db.scalars(select(BoardItem).where(BoardItem.parent_id == it.id, BoardItem.archived.is_(False))
                                                                .order_by(BoardItem.position))],
            "updates": [{"id": u.id, "user_id": u.user_id, "by": names.get(u.user_id or 0, "Automation"), "body": u.body,
                         "mentions": u.mentions, "reply_to": u.reply_to, "likes": len(u.liked_by or []),
                         "at": u.created_at.isoformat()}
                        for u in db.scalars(select(ItemUpdate).where(ItemUpdate.item_id == it.id).order_by(ItemUpdate.created_at.desc()))],
            "file_list": [{"id": f.id, "filename": f.filename, "mime": f.mime, "size": f.size, "by": names.get(f.user_id or 0, ""),
                           "is_image": (f.mime or "").startswith("image/"), "at": f.created_at.isoformat()}
                          for f in db.scalars(select(ItemFile).where(ItemFile.item_id == it.id).order_by(ItemFile.created_at.desc()))],
            "activity": [{"by": names.get(a.user_id or 0, "Automation"), "what": a.what, "old": a.old, "new": a.new,
                          "at": a.created_at.isoformat()}
                         for a in db.scalars(select(ItemActivity).where(ItemActivity.item_id == it.id, ~ItemActivity.what.like("auto:%"))
                                             .order_by(ItemActivity.created_at.desc()).limit(100))]}


class ItemPatch(BaseModel):
    name: str | None = None
    values: dict | None = None
    group_id: int | None = None
    position: float | None = None
    depends_on: list[int] | None = None
    archived: bool | None = None


def _patch(db: Session, it: BoardItem, body: ItemPatch, user: User) -> None:
    if body.name is not None:
        bd.set_value(db, it, "name", body.name, user.id)
    for k, v in (body.values or {}).items():
        _err(lambda k=k, v=v: bd.set_value(db, it, k, v, user.id))
    if body.group_id is not None or body.position is not None:
        _err(lambda: bd.move(db, it, body.group_id, body.position, user.id))
    if body.depends_on is not None:
        it.depends_on = [i for i in body.depends_on if i != it.id]
    if body.archived is not None:
        it.archived = body.archived
        bd.log(db, it, user.id, "archived" if body.archived else "restored")


@router.patch("/boards/items/{item_id}")
def edit_item(item_id: int, body: ItemPatch, db: Session = Depends(get_db), user: User = Depends(current_user)):
    it, _b = _item(db, item_id, user)
    _patch(db, it, body, user)
    db.commit()
    return bd.item_out(db, it)


@router.delete("/boards/items/{item_id}", status_code=204)
def delete_item(item_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    it, _b = _item(db, item_id, user)
    for f in db.scalars(select(ItemFile).where(ItemFile.item_id == it.id)):
        storage.delete(f.key)
    db.delete(it)
    db.commit()


class BulkIn(BaseModel):
    item_ids: list[int]
    values: dict | None = None
    group_id: int | None = None
    archive: bool = False
    delete: bool = False


@router.post("/boards/{board_id}/bulk")
def bulk(board_id: int, body: BulkIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    b = _board(db, board_id, user)
    items = [i for i in db.scalars(select(BoardItem).where(BoardItem.id.in_(body.item_ids))) if i.board_id == b.id]
    for it in items:
        if body.delete:
            db.delete(it)
            continue
        _patch(db, it, ItemPatch(values=body.values, group_id=body.group_id, archived=True if body.archive else None), user)
    db.commit()
    return {"changed": len(items)}


class UpdateIn(BaseModel):
    body: str = Field(min_length=1, max_length=10000)
    mentions: list[int] = []
    reply_to: int | None = None


@router.post("/boards/items/{item_id}/updates")
def add_update(item_id: int, body: UpdateIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    it, _b = _item(db, item_id, user)
    up = bd.post_update(db, it, user, body.body, list(body.mentions), body.reply_to)
    db.commit()
    return {"id": up.id, "mentions": up.mentions}


@router.post("/boards/updates/{update_id}/like")
def like(update_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    up = get_or_404(db, ItemUpdate, update_id)
    _item(db, up.item_id, user)
    liked = list(up.liked_by or [])
    up.liked_by = [x for x in liked if x != user.id] if user.id in liked else [*liked, user.id]
    db.commit()
    return {"likes": len(up.liked_by)}


@router.post("/boards/items/{item_id}/files")
async def add_files(item_id: int, files: list[UploadFile] = File(...), db: Session = Depends(get_db), user: User = Depends(current_user)):
    it, _b = _item(db, item_id, user)
    out = await _store(db, it, files, user)
    db.commit()
    return out


async def _store(db: Session, it: BoardItem, files: list[UploadFile], user: User) -> list[int]:
    out = []
    for f in files:
        data = await f.read(config.MAX_UPLOAD_BYTES + 1)
        if len(data) > config.MAX_UPLOAD_BYTES:
            raise HTTPException(413, f"{f.filename} is too large")
        name = f.filename or "file"
        key = f"boards/{it.board_id}/{it.id}/{uuid.uuid4().hex}-{''.join(c if c.isalnum() or c in '.-_' else '_' for c in name)[:120]}"
        storage.save_bytes(key, data)
        x = ItemFile(item_id=it.id, filename=name, key=key, mime=f.content_type or mimetypes.guess_type(name)[0] or "", size=len(data),
                     user_id=user.id)
        db.add(x)
        db.flush()
        bd.log(db, it, user.id, "file", "", name)
        out.append(x.id)
    return out


@router.get("/boards/files/{file_id}")
def get_file(file_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    f = get_or_404(db, ItemFile, file_id)
    _item(db, f.item_id, user)
    return Response(storage.read_bytes(f.key), media_type=f.mime or "application/octet-stream",
                    headers={"Content-Disposition": f'inline; filename="{"".join(c if c.isalnum() or c in ".-_ " else "_" for c in f.filename)}"'})


@router.delete("/boards/files/{file_id}", status_code=204)
def delete_file(file_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    f = get_or_404(db, ItemFile, file_id)
    _item(db, f.item_id, user)
    storage.delete(f.key)
    db.delete(f)
    db.commit()


class TimerIn(BaseModel):
    column: str
    start: bool


@router.post("/boards/items/{item_id}/timer")
def timer(item_id: int, body: TimerIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    it, _b = _item(db, item_id, user)
    v = _err(lambda: bd.timer(db, it, body.column, user, body.start))
    db.commit()
    return v


# --- automations, views, forms ---
class AutomationIn(BaseModel):
    name: str = ""
    trigger: dict
    actions: list[dict]
    active: bool = True


def _check_automation(db: Session, b: Board, body: AutomationIn) -> None:
    if body.trigger.get("type") not in bd.TRIGGERS:
        raise HTTPException(422, f"Trigger must be one of {', '.join(bd.TRIGGERS)}")
    if not body.actions:
        raise HTTPException(422, "Add at least one action")
    keys = {c.key for c in bd.columns(db, b.id)}
    if body.trigger.get("column") and body.trigger["column"] not in keys:
        raise HTTPException(422, "That column isn't on this board")
    for a in body.actions:
        if a.get("type") not in bd.ACTIONS:
            raise HTTPException(422, f"Action must be one of {', '.join(bd.ACTIONS)}")
        if a.get("column") and a["column"] not in keys:
            raise HTTPException(422, "That column isn't on this board")


@router.post("/boards/{board_id}/automations")
def add_automation(board_id: int, body: AutomationIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    b = _board(db, board_id, user)
    _check_automation(db, b, body)
    a = BoardAutomation(board_id=b.id, **body.model_dump())
    db.add(a)
    db.commit()
    return {"id": a.id}


@router.put("/boards/automations/{auto_id}")
def edit_automation(auto_id: int, body: AutomationIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    a = get_or_404(db, BoardAutomation, auto_id)
    b = _board(db, a.board_id, user)
    _check_automation(db, b, body)
    for k, v in body.model_dump().items():
        setattr(a, k, v)
    db.commit()
    return {"id": a.id}


@router.delete("/boards/automations/{auto_id}", status_code=204)
def delete_automation(auto_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    a = get_or_404(db, BoardAutomation, auto_id)
    _board(db, a.board_id, user)
    db.delete(a)
    db.commit()


class ViewIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    type: str = Field(default="table", pattern="^(table|kanban|calendar|timeline|workload|chart)$")
    settings: dict = {}


@router.post("/boards/{board_id}/views")
def add_view(board_id: int, body: ViewIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    b = _board(db, board_id, user)
    v = BoardView(board_id=b.id, **body.model_dump())
    db.add(v)
    db.commit()
    return {"id": v.id}


@router.put("/boards/views/{view_id}")
def edit_view(view_id: int, body: ViewIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    v = get_or_404(db, BoardView, view_id)
    _board(db, v.board_id, user)
    for k, val in body.model_dump().items():
        setattr(v, k, val)
    db.commit()
    return {"id": v.id}


@router.delete("/boards/views/{view_id}", status_code=204)
def delete_view(view_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    v = get_or_404(db, BoardView, view_id)
    _board(db, v.board_id, user)
    db.delete(v)
    db.commit()


class FormIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    intro: str = ""
    columns: list[str] = []
    group_id: int | None = None
    public: bool = True
    active: bool = True


@router.post("/boards/{board_id}/forms")
def add_form(board_id: int, body: FormIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    b = _board(db, board_id, user)
    f = BoardForm(board_id=b.id, token=bd.new_token(), **body.model_dump())
    db.add(f)
    db.commit()
    return {"id": f.id, "token": f.token}


@router.put("/boards/forms/{form_id}")
def edit_form(form_id: int, body: FormIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    f = get_or_404(db, BoardForm, form_id)
    _board(db, f.board_id, user)
    for k, v in body.model_dump().items():
        setattr(f, k, v)
    db.commit()
    return {"id": f.id, "token": f.token}


@router.delete("/boards/forms/{form_id}", status_code=204)
def delete_form(form_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    f = get_or_404(db, BoardForm, form_id)
    _board(db, f.board_id, user)
    db.delete(f)
    db.commit()


# --- My work ---
@router.get("/my-work")
def my_work(db: Session = Depends(get_db), user: User = Depends(current_user)):
    out = {"items": bd.my_items(db, user), **hr.my_hr(db, user)}
    db.commit()
    return out


@field.get("")
def field_work(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return my_work(db, user)


def _assigned(db: Session, item_id: int, user: User) -> tuple[BoardItem, Board]:
    it = db.get(BoardItem, item_id)
    b = db.get(Board, it.board_id) if it else None
    if it is None or b is None or not bd.can_see(user, b):
        raise HTTPException(404, "Item not found")
    if user.role == "field":
        pcols = [c.key for c in bd.columns(db, b.id) if c.type == "person"]
        if user.id not in (b.members or []) and not any(user.id in ((it.values or {}).get(k) or []) for k in pcols):
            raise HTTPException(404, "Item not found")
    return it, b


@field.get("/items/{item_id}")
def field_item(item_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    it, b = _assigned(db, item_id, user)
    cols = bd.columns(db, b.id)
    return {**_detail(db, it, b), "columns": [{"key": c.key, "title": c.title, "type": c.type, "settings": c.settings or {}} for c in cols],
            "shown": {c.key: bd.show(db, c, (it.values or {}).get(c.key)) for c in cols}}


@field.patch("/items/{item_id}")
def field_edit(item_id: int, body: ItemPatch, db: Session = Depends(get_db), user: User = Depends(current_user)):
    it, _b = _assigned(db, item_id, user)
    _patch(db, it, ItemPatch(values=body.values), user)  # the boys change values (status, notes); the office moves and renames
    db.commit()
    return bd.item_out(db, it)


@field.post("/items/{item_id}/updates")
def field_update(item_id: int, body: UpdateIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    it, _b = _assigned(db, item_id, user)
    up = bd.post_update(db, it, user, body.body, list(body.mentions), body.reply_to)
    db.commit()
    return {"id": up.id}


@field.post("/items/{item_id}/files")
async def field_files(item_id: int, files: list[UploadFile] = File(...), db: Session = Depends(get_db), user: User = Depends(current_user)):
    it, _b = _assigned(db, item_id, user)
    out = await _store(db, it, files, user)
    db.commit()
    return out


@field.get("/files/{file_id}")
def field_file(file_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    f = get_or_404(db, ItemFile, file_id)
    _assigned(db, f.item_id, user)
    return Response(storage.read_bytes(f.key), media_type=f.mime or "application/octet-stream")


# --- public forms ---
def _form(db: Session, token: str) -> tuple[BoardForm, Board]:
    f = db.scalar(select(BoardForm).where(BoardForm.token == token))
    b = db.get(Board, f.board_id) if f else None
    if f is None or b is None or not f.active or not f.public or b.archived:
        raise HTTPException(404, "This form isn't open")
    return f, b


@public.get("/{token}")
def form(token: str, db: Session = Depends(get_db)):
    from .. import ops

    f, b = _form(db, token)
    cols = {c.key: c for c in bd.columns(db, b.id)}
    return {"title": f.title, "intro": f.intro, "company": ops.settings(db)["company_name"],
            "fields": [{"key": k, "title": cols[k].title, "type": cols[k].type,
                        "options": (cols[k].settings or {}).get("options") or [],
                        "labels": [{"key": lab["key"], "label": lab["label"]} for lab in bd.labels_of(cols[k])]}
                       for k in f.columns if k in cols and cols[k].type in ("text", "long_text", "status", "date", "number", "money",
                                                                           "dropdown", "checkbox", "rating", "link", "phone", "email", "tags")]}


class FormAnswer(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    values: dict = {}
    website: str = ""  # hidden field: only bots fill it in


@public.post("/{token}")
def submit_form(token: str, body: FormAnswer, db: Session = Depends(get_db)):
    f, b = _form(db, token)
    if body.website:
        return {"ok": True}
    allowed = set(f.columns)
    values = {k: v for k, v in body.values.items() if k in allowed}
    it = _err(lambda: bd.create_item(db, b, body.name, None, f.group_id, values))
    bd.log(db, it, None, "form", "", f.title)
    db.commit()
    return {"ok": True}
