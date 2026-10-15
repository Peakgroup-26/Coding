"""The chat panel and the AI's memory."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import chat
from ..ai import AIUnavailable
from ..audit import record
from ..auth import current_user, require_admin
from ..db import get_db
from ..models import AiMemory, Job, User
from . import get_or_404

router = APIRouter(prefix="/api", tags=["chat"])


class ChatIn(BaseModel):
    text: str = Field(min_length=1, max_length=8000)


@router.get("/jobs/{job_id}/chat")
def get_chat(job_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    job = get_or_404(db, Job, job_id)
    return {"enabled": chat.get_model() is not None, "messages": chat.visible(db, job)}


@router.post("/jobs/{job_id}/chat")
def send(job_id: int, body: ChatIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    job = get_or_404(db, Job, job_id)
    try:
        return chat.send(db, job, user, body.text.strip())
    except AIUnavailable as e:
        raise HTTPException(503, str(e))


@router.post("/jobs/{job_id}/chat/new")
def new_conversation(job_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    """Start a fresh conversation about this job (memories carry over; the old chat is kept in the database)."""
    job = get_or_404(db, Job, job_id)
    chat.new_session(db, job)
    db.commit()
    return {"messages": []}


# --- memory ---
def _mem_out(m: AiMemory, names: dict, jobs: dict) -> dict:
    return {"id": m.id, "scope": m.scope, "client": m.client, "job_id": m.job_id, "job": jobs.get(m.job_id or m.source_job_id, ""),
            "kind": m.kind, "text": m.text, "active": m.active, "created_by": names.get(m.created_by, ""), "created_at": m.created_at}


@router.get("/memories")
def list_memories(include_inactive: bool = False, db: Session = Depends(get_db), _: User = Depends(current_user)):
    names = {u.id: (u.name or u.email) for u in db.scalars(select(User))}
    jobs = {j.id: j.name for j in db.scalars(select(Job))}
    q = select(AiMemory).order_by(AiMemory.scope, AiMemory.id.desc())
    if not include_inactive:
        q = q.where(AiMemory.active.is_(True))
    return [_mem_out(m, names, jobs) for m in db.scalars(q)]


class MemoryIn(BaseModel):
    text: str = Field(min_length=3, max_length=1000)
    scope: str = "company"  # company | client
    client: str = ""
    kind: str = ""  # hydraulic | civil | "" for both


class MemoryPatch(BaseModel):
    text: str | None = Field(default=None, min_length=3, max_length=1000)
    active: bool | None = None
    kind: str | None = None


@router.post("/memories")
def add_memory(body: MemoryIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    if body.scope not in ("company", "client") or (body.scope == "client" and not body.client.strip()):
        raise HTTPException(422, "Choose company, or client with a client name")
    if body.kind not in ("", "hydraulic", "civil"):
        raise HTTPException(422, "kind must be hydraulic, civil or blank")
    m = AiMemory(scope=body.scope, client=body.client.strip() if body.scope == "client" else "", kind=body.kind,
                 text=" ".join(body.text.split()), created_by=admin.id)
    db.add(m)
    db.flush()
    record(db, admin.id, "memory", m.id, "create", after={"text": m.text, "scope": m.scope})
    db.commit()
    return _mem_out(m, {admin.id: admin.name or admin.email}, {})


@router.patch("/memories/{memory_id}")
def update_memory(memory_id: int, body: MemoryPatch, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    m = get_or_404(db, AiMemory, memory_id)
    before = {"text": m.text, "active": m.active, "kind": m.kind}
    if body.text is not None:
        m.text = " ".join(body.text.split())
    if body.active is not None:
        m.active = body.active
    if body.kind is not None:
        if body.kind not in ("", "hydraulic", "civil"):
            raise HTTPException(422, "kind must be hydraulic, civil or blank")
        m.kind = body.kind
    record(db, admin.id, "memory", m.id, "update", before, {"text": m.text, "active": m.active, "kind": m.kind})
    db.commit()
    return {"ok": True}


@router.delete("/memories/{memory_id}", status_code=204)
def delete_memory(memory_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    m = get_or_404(db, AiMemory, memory_id)
    record(db, admin.id, "memory", m.id, "delete", before={"text": m.text, "scope": m.scope})
    db.delete(m)
    db.commit()
