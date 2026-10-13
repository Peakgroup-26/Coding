from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import ROLES, current_user, hash_password, make_token, require_admin, verify_password
from ..db import get_db
from ..models import User
from ..schemas import LoginIn, UserIn, UserOut, UserPatch
from . import get_or_404

router = APIRouter(prefix="/api", tags=["auth"])


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
    user = User(email=body.email.lower(), name=body.name, role=body.role, password_hash=hash_password(body.password))
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
    db.commit()
    return user
