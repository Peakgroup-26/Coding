from datetime import date, datetime

from sqlalchemy import inspect
from sqlalchemy.orm import Session

from .models import AuditLog


def snapshot(obj) -> dict:
    out = {}
    for attr in inspect(obj).mapper.column_attrs:
        v = getattr(obj, attr.key)
        if isinstance(v, (datetime, date)):
            v = v.isoformat()
        out[attr.key] = v
    return out


def record(db: Session, user_id: int | None, entity: str, entity_id: int, action: str, before=None, after=None):
    db.add(AuditLog(user_id=user_id, entity=entity, entity_id=entity_id, action=action, before=before, after=after))
