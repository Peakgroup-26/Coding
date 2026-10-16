from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import features
from ..access import PERMISSIONS
from ..sales import SECTORS
from ..audit import record
from ..auth import ROLES, current_user, hash_password, make_token, require_admin, verify_password
from ..db import get_db
from ..models import Position, User
from ..schemas import LoginIn, PasswordChange, UserIn, UserOut, UserPatch
from . import get_or_404

router = APIRouter(prefix="/api", tags=["auth"])
STAFF_FIELDS = ("trade", "phone", "cost_rate", "charge_rate", "colour")


def _sectors(values: list[str] | None) -> list[str] | None:
    """Residential / commercial / maintenance. Empty or all three = every sector."""
    if not values:
        return None
    bad = [v for v in values if v not in SECTORS]
    if bad:
        raise HTTPException(422, f"Unknown sector {bad[0]}")
    return None if set(values) == set(SECTORS) else sorted(set(values))


@router.post("/auth/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(func.lower(User.email) == body.email.strip().lower()))
    if not user or not user.active or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Email or password is wrong")
    from .. import config

    ttl = config.FIELD_TOKEN_TTL_DAYS * 24 if user.role == "field" else None  # phones stay signed in
    return {"token": make_token(user.id, ttl), "user": UserOut.model_validate(user)}


@router.get("/auth/me")
def me(db: Session = Depends(get_db), user: User = Depends(current_user)):
    """The signed-in person, with what they can see and change (feature -> none | view | edit)."""
    return {**UserOut.model_validate(user).model_dump(), "access": features.effective(db, user)}


@router.get("/users", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return db.scalars(select(User).order_by(User.email)).all()


@router.post("/users", response_model=UserOut)
def create_user(body: UserIn, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    if body.role not in ROLES:
        raise HTTPException(422, f"Role must be one of {', '.join(ROLES)}")
    if db.scalar(select(User).where(func.lower(User.email) == body.email.lower())):
        raise HTTPException(409, "A user with that email already exists")
    user = User(email=body.email.lower(), name=body.name, role=body.role, password_hash=hash_password(body.password),
                sectors=_sectors(body.sectors), **{k: getattr(body, k) for k in PERMISSIONS},
                **{k: getattr(body, k) for k in STAFF_FIELDS})
    db.add(user)
    db.commit()
    return user


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(user_id: int, body: UserPatch, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    user = get_or_404(db, User, user_id)
    if body.role is not None:
        if body.role not in ROLES:
            raise HTTPException(422, f"Role must be one of {', '.join(ROLES)}")
        if user.id == admin.id and body.role != "admin":
            raise HTTPException(409, "You can't remove your own admin role")
        user.role = body.role
    if body.name is not None:
        user.name = body.name
    if body.active is not None:
        if user.id == admin.id and not body.active:
            raise HTTPException(409, "You can't deactivate yourself")
        user.active = body.active
    if body.password:
        user.password_hash = hash_password(body.password)
    for k in PERMISSIONS:
        if getattr(body, k) is not None:
            setattr(user, k, getattr(body, k))
    if body.sectors is not None:
        user.sectors = _sectors(body.sectors)
    for k in STAFF_FIELDS:
        if getattr(body, k) is not None:
            setattr(user, k, getattr(body, k))
    record(db, admin.id, "user", user.id, "update", after={k: v for k, v in body.model_dump(exclude_unset=True).items() if k != "password"})
    db.commit()
    return user


@router.post("/auth/password", status_code=204)
def change_password(body: PasswordChange, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Change your own password."""
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(403, "Your current password is wrong")
    user.password_hash = hash_password(body.new_password)
    record(db, user.id, "user", user.id, "password_change")
    db.commit()


@router.get("/permissions")
def permissions(_: User = Depends(current_user)):
    return PERMISSIONS


# --- per-feature access: positions (presets) and each person's own settings ---
class PositionIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = ""
    features: dict[str, str] = {}


def position_out(db: Session, p: Position) -> dict:
    n = db.scalar(select(func.count()).select_from(User).where(User.position_id == p.id)) or 0
    return {"id": p.id, "name": p.name, "description": p.description, "features": {**{k: "edit" for k in features.KEYS}, **features.clean(p.features)},
            "people": n}


@router.get("/features")
def feature_list(_: User = Depends(require_admin)):
    return {"features": features.catalogue(), "levels": list(features.LEVELS)}


@router.get("/positions")
def list_positions(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return [position_out(db, p) for p in db.scalars(select(Position).order_by(Position.position, Position.name))]


@router.post("/positions")
def add_position(body: PositionIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    if db.scalar(select(Position).where(func.lower(Position.name) == body.name.strip().lower())):
        raise HTTPException(409, "There's already a position with that name")
    p = Position(name=body.name.strip(), description=body.description, features=features.clean(body.features),
                 position=(db.scalar(select(func.max(Position.position))) or 0) + 1)
    db.add(p)
    db.flush()
    record(db, admin.id, "position", p.id, "create", after={"name": p.name})
    db.commit()
    return position_out(db, p)


@router.put("/positions/{pos_id}")
def edit_position(pos_id: int, body: PositionIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    p = get_or_404(db, Position, pos_id)
    before = {"name": p.name, "features": p.features}
    p.name, p.description, p.features = body.name.strip(), body.description, features.clean(body.features)
    record(db, admin.id, "position", p.id, "update", before, {"name": p.name, "features": p.features})
    db.commit()
    return position_out(db, p)


@router.delete("/positions/{pos_id}", status_code=204)
def delete_position(pos_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    p = get_or_404(db, Position, pos_id)
    for u in db.scalars(select(User).where(User.position_id == p.id)):
        u.position_id = None
    record(db, admin.id, "position", p.id, "delete", before={"name": p.name})
    db.delete(p)
    db.commit()


class AccessIn(BaseModel):
    position_id: int | None = None
    features: dict[str, str] = {}  # this person's own changes from their position; leave a feature out to follow the position


@router.get("/users/{user_id}/access")
def user_access(user_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    u = get_or_404(db, User, user_id)
    return {"user_id": u.id, "position_id": u.position_id, "features": features.clean(u.features), "effective": features.effective(db, u),
            "is_admin": u.role == "admin"}


@router.put("/users/{user_id}/access")
def set_access(user_id: int, body: AccessIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    u = get_or_404(db, User, user_id)
    if body.position_id is not None:
        get_or_404(db, Position, body.position_id)
    before = {"position_id": u.position_id, "features": u.features}
    u.position_id = body.position_id
    u.features = features.clean(body.features) or None
    record(db, admin.id, "user", u.id, "access", before, {"position_id": u.position_id, "features": u.features})
    db.commit()
    return user_access(user_id, db, admin)


@router.get("/access/overview")
def access_overview(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    """Who can see what: every active person against every feature."""
    pos = {p.id: p.name for p in db.scalars(select(Position))}
    return [{"user_id": u.id, "name": u.name or u.email, "role": u.role, "position": pos.get(u.position_id or 0, ""),
             "own": sorted(features.clean(u.features)), "access": features.effective(db, u)}
            for u in db.scalars(select(User).where(User.active.is_(True)).order_by(User.name, User.email))]
