"""Who can see what.

Each user has five permissions (admins always have all of them):
  can_hydraulic   plumbing / hydraulic jobs
  can_civil       civil jobs
  can_all_jobs    other people's jobs, including previous tenders (without it: only jobs they started)
  can_past_rates  the previous civil job rates library
  can_pricing     changing price books, mappings and fitting rules (anyone can view them)

`enforce` runs on every API request. It finds the job behind any id in the URL (a job, sheet,
run, count, BOQ line, document and so on) and refuses the request if the user can't see that
job, so no route can be reached around the check. A job the user can't see answers 404, as if it
didn't exist.
"""
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from .auth import _bearer, read_token
from .db import get_db
from .models import (CivilBoqLine, CountItem, Flag, GeneratedItem, Job, JobAllowance, Level, Run, Sheet, TenderDocument,
                     TenderRequirement, User, Viewport)

PERMISSIONS = {
    "can_hydraulic": "Plumbing jobs",
    "can_civil": "Civil jobs",
    "can_all_jobs": "Everyone's jobs and previous tenders",
    "can_past_rates": "Previous civil job rates",
    "can_pricing": "Change price books, mappings and rules",
}

# URL parameter -> table whose rows belong to a job
JOB_PARAMS = {
    "job_id": Job, "sheet_id": Sheet, "run_id": Run, "count_id": CountItem, "aid": JobAllowance,
    "doc_id": TenderDocument, "req_id": TenderRequirement, "line_id": CivilBoqLine, "level_id": Level,
    "flag_id": Flag, "vp_id": Viewport,
}

# (path prefix, permission, methods it applies to; None = all)
AREAS = [
    ("/api/civil/rate-sets", "can_past_rates", None),
    ("/api/civil/rates", "can_past_rates", None),
    ("/api/price-books", "can_pricing", {"POST", "PUT", "PATCH", "DELETE"}),
    ("/api/mappings", "can_pricing", {"POST", "PUT", "PATCH", "DELETE"}),
    ("/api/rules", "can_pricing", {"POST", "PUT", "PATCH", "DELETE"}),
    ("/api/catalogue", "can_pricing", {"POST", "PUT", "PATCH", "DELETE"}),
    ("/api/benchmarks", "can_pricing", {"POST", "PUT", "PATCH", "DELETE"}),
    ("/api/settings/simpro-template", "can_pricing", {"POST", "PUT", "PATCH", "DELETE"}),
]


def has(user: User, permission: str) -> bool:
    return user.role == "admin" or bool(getattr(user, permission, False))


def can_kind(user: User, kind: str) -> bool:
    return has(user, "can_civil" if kind == "civil" else "can_hydraulic")


def can_see_job(user: User, job: Job) -> bool:
    if user.role == "admin":
        return True
    if not can_kind(user, job.kind or "hydraulic"):
        return False
    return job.created_by == user.id or bool(user.can_all_jobs)


def visible_kinds(user: User) -> list[str]:
    return [k for k in ("hydraulic", "civil") if can_kind(user, k)]


def _job_of(db: Session, obj) -> Job | None:
    if isinstance(obj, Job):
        return obj
    if isinstance(obj, Viewport):
        return db.get(Job, obj.sheet.job_id)
    job_id = getattr(obj, "job_id", None)
    return db.get(Job, job_id) if job_id else None


def enforce(request: Request, db: Session = Depends(get_db),
            creds: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> None:
    params = request.path_params
    path = request.url.path
    targets = []
    for name, model in JOB_PARAMS.items():
        if name in params:
            targets.append((model, params[name]))
    if "item_id" in params and path.startswith("/api/generated/"):
        targets.append((GeneratedItem, params["item_id"]))
    areas = [perm for prefix, perm, methods in AREAS
             if path.startswith(prefix) and (methods is None or request.method in methods)]
    if not targets and not areas:
        return
    uid = read_token(creds.credentials) if creds else None
    user = db.get(User, uid) if uid else None
    if not user or not user.active:
        raise HTTPException(401, "Not signed in")
    for perm in areas:
        if not has(user, perm):
            raise HTTPException(403, f"You don't have access to {PERMISSIONS[perm].lower()}. Ask an admin.")
    for model, raw in targets:
        try:
            obj = db.get(model, int(raw))
        except (TypeError, ValueError):
            continue
        if obj is None:
            continue  # the route answers 404 itself
        job = _job_of(db, obj)
        if job is not None and not can_see_job(user, job):
            raise HTTPException(404, f"{model.__name__} {raw} not found")
