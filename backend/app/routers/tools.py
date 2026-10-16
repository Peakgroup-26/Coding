"""Tools (the register at /api/tools, everyone's side at /api/field/tools) and the live vehicle map (/api/vehicles)."""
import csv
import io
import uuid
from datetime import date

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .. import config, features, geotab, storage
from .. import tools as tl
from ..auth import current_user
from ..db import get_db
from ..models import Plant, Tool, ToolMove, User
from . import get_or_404

router = APIRouter(prefix="/api", tags=["tools"])
field = APIRouter(prefix="/api/field", tags=["tools"])


def _users(db: Session) -> dict[int, User]:
    return {u.id: u for u in db.scalars(select(User))}


def _office(db: Session, user: User) -> bool:
    return features.level(db, user, "tools") == "edit" and user.role != "field"


# --- the register ---
class ToolIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    category: str = ""
    asset_no: str = ""
    make: str = ""
    model: str = ""
    serial: str = ""
    value: float | None = None
    location: str = "Yard"
    test_tag_due: date | None = None
    service_due: date | None = None
    notes: str = ""
    status: str | None = Field(default=None, pattern="^(available|with_person|repair|lost|retired)$")


@router.get("/tools")
def list_tools(q: str = "", status: str = "", holder_id: int | None = None, db: Session = Depends(get_db), _: User = Depends(current_user)):
    stmt = select(Tool).order_by(Tool.name)
    if q:
        stmt = stmt.where(or_(Tool.name.ilike(f"%{q}%"), Tool.asset_no.ilike(f"%{q}%"), Tool.serial.ilike(f"%{q}%"), Tool.category.ilike(f"%{q}%")))
    if status:
        stmt = stmt.where(Tool.status == status)
    if holder_id:
        stmt = stmt.where(Tool.holder_id == holder_id)
    users = _users(db)
    today = date.today()
    return {"tools": [tl.tool_out(db, t, users, today) for t in db.scalars(stmt)], "categories": tl.CATEGORIES, "statuses": tl.STATUSES}


@router.post("/tools")
def add_tool(body: ToolIn, db: Session = Depends(get_db), _: User = Depends(current_user)):
    t = Tool(**{k: v for k, v in body.model_dump().items() if k != "status"}, status=body.status or "available")
    db.add(t)
    db.commit()
    return tl.tool_out(db, t)


@router.put("/tools/{tool_id}")
def edit_tool(tool_id: int, body: ToolIn, db: Session = Depends(get_db), _: User = Depends(current_user)):
    t = get_or_404(db, Tool, tool_id)
    for k, v in body.model_dump().items():
        if k == "status" and v is None:
            continue
        setattr(t, k, v)
    if t.status in ("available", "retired", "lost") and t.holder_id and body.status:
        t.holder_id = None
    db.commit()
    return tl.tool_out(db, t)


class AssignIn(BaseModel):
    user_id: int | None = None
    location: str = ""


@router.post("/tools/{tool_id}/assign")
def assign(tool_id: int, body: AssignIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    t = get_or_404(db, Tool, tool_id)
    if body.user_id:
        get_or_404(db, User, body.user_id)
    tl.assign(db, t, user, body.user_id, body.location)
    db.commit()
    return tl.tool_out(db, t)


@router.get("/tools/{tool_id}/history")
def history(tool_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    get_or_404(db, Tool, tool_id)
    users = _users(db)
    return [tl.move_out(m, users) for m in db.scalars(select(ToolMove).where(ToolMove.tool_id == tool_id).order_by(ToolMove.created_at.desc()))]


@router.post("/tools/{tool_id}/photo")
async def tool_photo(tool_id: int, file: UploadFile = File(...), db: Session = Depends(get_db), _: User = Depends(current_user)):
    t = get_or_404(db, Tool, tool_id)
    data = await file.read(config.MAX_UPLOAD_BYTES + 1)
    if len(data) > config.MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Photo too large")
    if t.photo_key:
        storage.delete(t.photo_key)
    t.photo_key = f"tools/{t.id}/{uuid.uuid4().hex}.jpg"
    storage.save_bytes(t.photo_key, data)
    db.commit()
    return {"ok": True}


@router.post("/tools/import")
async def import_tools(file: UploadFile = File(...), db: Session = Depends(get_db), _: User = Depends(current_user)):
    """CSV: name, category, asset_no, make, model, serial, value, location, test_tag_due (YYYY-MM-DD or DD/MM/YYYY)."""
    text = (await file.read()).decode("utf-8-sig", errors="replace")
    added = updated = 0
    for row in csv.DictReader(io.StringIO(text)):
        row = {(k or "").strip().lower().replace(" ", "_"): (v or "").strip() for k, v in row.items()}
        if not row.get("name"):
            continue
        t = db.scalar(select(Tool).where(Tool.asset_no == row["asset_no"])) if row.get("asset_no") else None
        if t is None:
            t = Tool(name=row["name"])
            db.add(t)
            added += 1
        else:
            updated += 1
        for k in ("name", "category", "asset_no", "make", "model", "serial", "location"):
            if row.get(k):
                setattr(t, k, row[k])
        if row.get("value"):
            try:
                t.value = float(row["value"].replace("$", "").replace(",", ""))
            except ValueError:
                pass
        if row.get("test_tag_due"):
            v = row["test_tag_due"]
            try:
                t.test_tag_due = date.fromisoformat(v) if "-" in v else date(int(v.split("/")[2]), int(v.split("/")[1]), int(v.split("/")[0]))
            except (ValueError, IndexError):
                pass
    db.commit()
    return {"added": added, "updated": updated}


# --- everyone's side (the phone, and the office's Tools page uses it too) ---
@field.get("/tools")
def field_tools(db: Session = Depends(get_db), user: User = Depends(current_user)):
    users = _users(db)
    today = date.today()
    tools = [tl.tool_out(db, t, users, today) for t in db.scalars(select(Tool).where(Tool.status != "retired").order_by(Tool.name))]
    pend = list(db.scalars(select(ToolMove).where(ToolMove.status == "pending", or_(ToolMove.to_user_id == user.id, ToolMove.from_user_id == user.id))))
    return {"tools": tools, "me": user.id,
            "to_confirm": [{**tl.move_out(m, users), "tool": db.get(Tool, m.tool_id).name} for m in pend if m.started_by != user.id],
            "waiting": [{**tl.move_out(m, users), "tool": db.get(Tool, m.tool_id).name} for m in pend if m.started_by == user.id],
            "people": [{"user_id": u.id, "name": u.name or u.email, "phone": u.phone} for u in users.values() if u.active],
            "office": _office(db, user)}


@field.get("/tools/{tool_id}/photo")
def field_tool_photo(tool_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    t = get_or_404(db, Tool, tool_id)
    if not t.photo_key:
        raise HTTPException(404, "No photo")
    return Response(storage.read_bytes(t.photo_key), media_type="image/jpeg", headers={"Cache-Control": "private, max-age=600"})


class MoveIn(BaseModel):
    note: str = ""
    to_user_id: int | None = None
    location: str = "Yard"
    lat: float | None = None
    lng: float | None = None


def _do(fn):
    try:
        return fn()
    except ValueError as e:
        raise HTTPException(409, str(e))
    except PermissionError as e:
        raise HTTPException(403, str(e))


@field.post("/tools/{tool_id}/request")
def request_tool(tool_id: int, body: MoveIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    t = get_or_404(db, Tool, tool_id)
    _do(lambda: tl.request(db, t, user, body.note))
    db.commit()
    return tl.tool_out(db, t)


@field.post("/tools/{tool_id}/give")
def give_tool(tool_id: int, body: MoveIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    t = get_or_404(db, Tool, tool_id)
    if t.holder_id not in (user.id, None) and not _office(db, user):
        raise HTTPException(403, "Only the person who has it (or the office) can hand it on")
    to = get_or_404(db, User, body.to_user_id or 0)
    _do(lambda: tl.give(db, t, user, to, body.note, body.lat, body.lng))
    db.commit()
    return tl.tool_out(db, t)


@field.post("/tools/{tool_id}/take")
def take_tool(tool_id: int, body: MoveIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    t = get_or_404(db, Tool, tool_id)
    if t.status in ("repair", "lost", "retired"):
        raise HTTPException(409, f"It's marked as {tl.STATUSES[t.status].lower()}. Check with the office.")
    _do(lambda: tl.take(db, t, user, body.note, body.lat, body.lng))
    db.commit()
    return tl.tool_out(db, t)


@field.post("/tools/{tool_id}/return")
def return_tool(tool_id: int, body: MoveIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    t = get_or_404(db, Tool, tool_id)
    _do(lambda: tl.return_to_yard(db, t, user, body.location or "Yard", _office(db, user)))
    db.commit()
    return tl.tool_out(db, t)


class ReportIn(BaseModel):
    kind: str = Field(pattern="^(repair|lost)$")
    note: str = ""


@field.post("/tools/{tool_id}/report")
def report_tool(tool_id: int, body: ReportIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    from ..plant import notify

    t = get_or_404(db, Tool, tool_id)
    t.status = body.kind
    db.add(ToolMove(tool_id=t.id, kind=body.kind, from_user_id=t.holder_id, to_user_id=None, status="done", started_by=user.id, note=body.note))
    for a in db.scalars(select(User).where(User.role == "admin", User.active.is_(True))):
        notify(db, a.id, "tool", f"{user.name or user.email}: the {t.name} {'needs repair' if body.kind == 'repair' else 'is missing'}. {body.note}",
               "/tools", key=f"toolrep-{t.id}-{body.kind}-{a.id}-{t.updated_at.timestamp():.0f}")
    db.commit()
    return tl.tool_out(db, t)


@field.post("/tool-moves/{move_id}/confirm")
def confirm_move(move_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    m = get_or_404(db, ToolMove, move_id)
    _do(lambda: tl.confirm(db, m, user, _office(db, user)))
    db.commit()
    return tl.tool_out(db, db.get(Tool, m.tool_id))


@field.post("/tool-moves/{move_id}/decline")
def decline_move(move_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    m = get_or_404(db, ToolMove, move_id)
    _do(lambda: tl.decline(db, m, user))
    db.commit()
    return {"ok": True}


# --- vehicles (Geotab) ---
@router.get("/vehicles/live")
def vehicles_live(fresh: bool = False, db: Session = Depends(get_db), _: User = Depends(current_user)):
    if not geotab.ready():
        return {"connected": False, "vehicles": [], "message": "Geotab isn't connected yet. Add GEOTAB_DATABASE, GEOTAB_USERNAME and "
                                                               "GEOTAB_PASSWORD to the server's .env (see deploy/GEOTAB.md)."}
    try:
        return geotab.live(db, fresh)
    except geotab.GeotabError as e:
        return {"connected": False, "vehicles": [], "message": f"Couldn't reach Geotab: {e}"}
    except Exception as e:  # noqa: BLE001 - a network problem shouldn't break the page
        return {"connected": False, "vehicles": [], "message": f"Couldn't reach Geotab ({type(e).__name__})"}


class LinkIn(BaseModel):
    geotab_id: str = ""


@router.put("/vehicles/link/{plant_id}")
def link_vehicle(plant_id: int, body: LinkIn, db: Session = Depends(get_db), _: User = Depends(current_user)):
    p = get_or_404(db, Plant, plant_id)
    p.geotab_id = body.geotab_id.strip()
    db.commit()
    return {"id": p.id, "geotab_id": p.geotab_id}


@router.get("/vehicles/plant")
def vehicle_plant(db: Session = Depends(get_db), _: User = Depends(current_user)):
    return [{"id": p.id, "name": p.name, "rego": p.rego, "kind": p.kind, "geotab_id": p.geotab_id}
            for p in db.scalars(select(Plant).where(Plant.status != "sold").order_by(Plant.kind, Plant.name))]
