from fastapi import HTTPException


def ensure_open(db, job_id: int):
    """Refuse changes to a job that a reviewer has signed off as final."""
    from ..models import Job

    job = db.get(Job, job_id)
    if job is not None and job.status == "final":
        raise HTTPException(409, "This estimate is final. A reviewer must reopen it before anything changes.")


def get_or_404(db, model, id_):
    obj = db.get(model, id_)
    if obj is None:
        raise HTTPException(404, f"{model.__name__} {id_} not found")
    return obj
