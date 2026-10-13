"""Admin-maintained lists: stages, services, materials (with waste %), count item types."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auth import current_user, require_admin
from ..db import get_db
from ..models import CountType, Material, Service, Stage, User
from ..schemas import (CountTypeIn, CountTypeOut, MaterialIn, MaterialOut, ServiceIn, ServiceOut, StageIn,
                       StageOut)
from . import get_or_404

router = APIRouter(prefix="/api", tags=["settings"])


@router.get("/settings")
def all_settings(db: Session = Depends(get_db), _: User = Depends(current_user)):
    return {
        "stages": [StageOut.model_validate(s) for s in db.scalars(select(Stage).order_by(Stage.order, Stage.id))],
        "services": [ServiceOut.model_validate(s) for s in db.scalars(select(Service).order_by(Service.order, Service.id))],
        "materials": [MaterialOut.model_validate(m) for m in db.scalars(select(Material).order_by(Material.name))],
        "count_types": [CountTypeOut.model_validate(c) for c in db.scalars(select(CountType).order_by(CountType.name))],
    }


def _crud(path: str, model, in_schema, out_schema):
    """Create and update endpoints for a simple admin list. Items are retired (active=false), not deleted,
    so old jobs keep their references."""

    @router.post(f"/{path}", response_model=out_schema, name=f"create_{path}")
    def create(body: in_schema, db: Session = Depends(get_db), _: User = Depends(require_admin)):
        obj = model(**body.model_dump())
        db.add(obj)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, "That name or code is already used")
        return obj

    @router.put(f"/{path}/{{item_id}}", response_model=out_schema, name=f"update_{path}")
    def update(item_id: int, body: in_schema, db: Session = Depends(get_db), _: User = Depends(require_admin)):
        obj = get_or_404(db, model, item_id)
        for k, v in body.model_dump().items():
            setattr(obj, k, v)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, "That name or code is already used")
        return obj


_crud("stages", Stage, StageIn, StageOut)
_crud("services", Service, ServiceIn, ServiceOut)
_crud("materials", Material, MaterialIn, MaterialOut)
_crud("count-types", CountType, CountTypeIn, CountTypeOut)
