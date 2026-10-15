from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..access import PERMISSIONS
from ..sales import SECTORS
from ..audit import record
from ..auth import ROLES, current_user, hash_password, make_token, require_admin, verify_password
from ..db import get_db
from ..models import User
from ..schemas import LoginIn, PasswordChange, UserIn, UserOut, UserPatch
from . import get_or_404

router = APIRouter(prefix="/api", tags=["auth"])


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
    return {"token": make_token(user.id), "user": UserOut.model_validate(user)}


@router.get("/auth/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return user


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
                sectors=_sectors(body.sectors), **{k: getattr(body, k) for k in PERMISSIONS})
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
