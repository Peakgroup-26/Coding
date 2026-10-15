"""The AI's memory: things it has learnt that should carry into later work.

  company  applies to every job (e.g. "Peak prices acoustic drainage as Rehau Raupiano Plus")
  client   applies to one client's or consultant's jobs (e.g. "ABC Consultants draw sewer in brown")
  job      applies to this job only

Memories come from the chat (the AI saves one when someone states a preference or corrects it)
or are typed in by a person. They are fed to the chat and to the autopilot's AI reads. Everyone
can see them; admins can edit or switch them off in the admin portal.
"""
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .models import AiMemory, Job

MAX_MEMORIES_IN_PROMPT = 120


def for_job(db: Session, job: Job) -> list[AiMemory]:
    """The memories that apply to a job: company-wide, this client's, and this job's own."""
    kind = job.kind or "hydraulic"
    q = select(AiMemory).where(
        AiMemory.active.is_(True),
        or_(AiMemory.kind == "", AiMemory.kind == kind),
        or_(AiMemory.scope == "company",
            (AiMemory.scope == "client") & (AiMemory.client == (job.client or "")) & (AiMemory.client != ""),
            (AiMemory.scope == "job") & (AiMemory.job_id == job.id)),
    ).order_by(AiMemory.scope, AiMemory.id)
    return list(db.scalars(q))[:MAX_MEMORIES_IN_PROMPT]


def as_text(memories: list[AiMemory]) -> str:
    labels = {"company": "All jobs", "client": "This client", "job": "This job"}
    return "\n".join(f"- [memory {m.id}, {labels.get(m.scope, m.scope)}] {m.text}" for m in memories)


def remember(db: Session, job: Job, text: str, scope: str, user_id: int | None) -> AiMemory:
    if scope not in ("company", "client", "job"):
        raise ValueError("scope must be company, client or job")
    if scope == "client" and not job.client:
        scope = "job"  # no client on this job to file it under
    text = " ".join(text.split())[:1000]
    existing = db.scalar(select(AiMemory).where(AiMemory.active.is_(True), AiMemory.scope == scope, AiMemory.text == text,
                                                AiMemory.client == (job.client if scope == "client" else ""),
                                                AiMemory.job_id == (job.id if scope == "job" else None)))
    if existing:
        return existing
    m = AiMemory(scope=scope, client=job.client if scope == "client" else "", job_id=job.id if scope == "job" else None,
                 kind=job.kind or "hydraulic", text=text, source_job_id=job.id, created_by=user_id)
    db.add(m)
    db.flush()
    return m
