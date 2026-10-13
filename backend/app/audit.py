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
    job_id = entity_id if entity == "job" else next(
        (d["job_id"] for d in (after, before) if isinstance(d, dict) and d.get("job_id") is not None), None)
    db.add(AuditLog(user_id=user_id, entity=entity, entity_id=entity_id, job_id=job_id, action=action, before=before, after=after))
