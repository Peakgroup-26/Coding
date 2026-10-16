"""Who can see what.

Each user has these permissions (admins always have all of them):
  can_hydraulic   plumbing / hydraulic jobs
  can_civil       civil jobs
  can_all_jobs    other people's jobs, including previous tenders (without it: only jobs they started)
  can_past_rates  the previous civil job rates library
  can_pricing     changing price books, mappings, fitting rules and productivity rates (anyone can view them)
  can_ops         live jobs, scheduling, timesheet approval, purchasing, customers and the CRM
  can_finance     WIP, budgets, cash flow, invoices, supplier prices and the Xero connection

Role "field" is for the people on the tools: they only get the phone app (/api/field/...), their own
time and schedule, the live jobs they work on, and the documents marked for the field.

`enforce` runs on every API request. It finds the job behind any id in the URL (a job, sheet,
run, count, BOQ line, document and so on) and refuses the request if the user can't see that
job, so no route can be reached around the check. A job the user can't see answers 404, as if it
didn't exist.
"""
import re

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from .auth import _bearer, read_token
from .db import get_db
from .models import (BudgetLine, CivilBoqLine, CountItem, DailyLog, Document, Flag, FormResponse, GeneratedItem, Invoice,
                     Job, JobAllowance, JobCost, Level, ProjectItem, PurchaseOrder, Run, ScheduleEntry, Sheet, TenderDocument,
                     TenderRequirement, TimeEntry, User, Variation, Viewport)

PERMISSIONS = {
    "can_hydraulic": "Plumbing jobs",
    "can_civil": "Civil jobs",
    "can_all_jobs": "Everyone's jobs and previous tenders",
    "can_past_rates": "Previous civil job rates",
    "can_pricing": "Change price books, mappings and rules",
    "can_ops": "Live jobs, scheduling, purchasing, customers and CRM",
    "can_finance": "Finance: WIP, budgets, cash flow, invoices, supplier prices, Xero",
}

# URL parameter -> table whose rows belong to a job
JOB_PARAMS = {
    "job_id": Job, "sheet_id": Sheet, "run_id": Run, "count_id": CountItem, "aid": JobAllowance,
    "doc_id": TenderDocument, "req_id": TenderRequirement, "line_id": CivilBoqLine, "level_id": Level,
    "flag_id": Flag, "vp_id": Viewport,
    "budget_id": BudgetLine, "sched_id": ScheduleEntry, "time_id": TimeEntry, "po_id": PurchaseOrder, "cost_id": JobCost,
    "var_id": Variation, "inv_id": Invoice, "document_id": Document, "pitem_id": ProjectItem, "log_id": DailyLog,
    "resp_id": FormResponse,
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
    ("/api/productivity", "can_pricing", {"POST", "PUT", "PATCH", "DELETE"}),
    ("/api/work", "can_ops", None),
    ("/api/customers", "can_ops", None),
    ("/api/sites", "can_ops", None),
    ("/api/suppliers", "can_ops", {"POST", "PUT", "PATCH", "DELETE"}),
    ("/api/schedule", "can_ops", None),
    ("/api/timesheets", "can_ops", None),
    ("/api/time-off", "can_ops", None),
    ("/api/purchase-orders", "can_ops", None),
    ("/api/assets", "can_ops", None),
    ("/api/maintenance", "can_ops", None),
    ("/api/forms", "can_ops", {"POST", "PUT", "PATCH", "DELETE"}),
    ("/api/crm", "can_ops", None),
    ("/api/finance", "can_finance", None),
    ("/api/invoices", "can_finance", None),
    ("/api/budget-months", "can_finance", None),
    ("/api/supplier-prices", "can_finance", None),
    ("/api/integrations", "can_finance", None),
    ("/api/costs", "can_ops", None),
    ("/api/variations", "can_ops", None),
    ("/api/budget/", "can_ops", None),
    ("/api/items", "can_ops", None),
    ("/api/plant", "can_ops", None),
    ("/api/form-templates", "can_ops", None),
    ("/api/files", "can_ops", None),
]
# A job's delivery side (/api/jobs/12/costs and so on) needs can_ops as well as access to the job.
JOB_OPS = re.compile(r"^/api/jobs/\d+/(costs|budget|variations|work|docs|items|diary|forms|time)\b")

# The only API paths a "field" user can reach.
FIELD_PATHS = ("/api/field/", "/api/auth/", "/api/settings", "/api/assistant")


def has(user: User, permission: str) -> bool:
    return user.role == "admin" or bool(getattr(user, permission, False))


def can_kind(user: User, kind: str) -> bool:
    return has(user, "can_civil" if kind == "civil" else "can_hydraulic")


def can_sector(user: User, sector: str) -> bool:
    """Residential / commercial / maintenance. No list set = every sector."""
    return user.role == "admin" or not user.sectors or sector in user.sectors


def can_see_job(user: User, job: Job) -> bool:
    if user.role == "admin":
        return True
    if user.role == "field":
        return bool(job.work_status)  # live jobs only; never quotes, tenders or prices
    if not can_kind(user, job.kind or "hydraulic") or not can_sector(user, job.sector or "commercial"):
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
    if JOB_OPS.match(path):
        areas.append("can_ops")
    uid = read_token(creds.credentials) if creds else None
    user = db.get(User, uid) if uid else None
    if user is not None and user.role == "field" and not path.startswith(FIELD_PATHS):
        raise HTTPException(403, "This part of the app is for the office.")
    if not targets and not areas:
        return
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
