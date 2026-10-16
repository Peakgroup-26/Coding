"""Finance (WIP, month to date, cash flow, monthly budgets), the CRM, Xero and supplier price files."""
import csv
import io
from datetime import date, timedelta

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import crm, finance, ops, supplier_prices, xero
from ..access import can_see_job
from ..audit import record
from ..auth import current_user, require_admin
from ..db import get_db
from ..models import (BudgetMonth, CrmActivity, CrmRule, Customer, Feedback, Job, OutboundMessage, PriceBookVersion, PriceImport,
                      PriceItem, Supplier, SupplierPrice, User)
from ..pricebook_import import read_rows
from . import get_or_404

router = APIRouter(prefix="/api", tags=["finance"])
public = APIRouter(prefix="/api/public", tags=["public"])


def _jobs(db: Session, user: User, active_only: bool = False) -> list[Job]:
    stmt = select(Job).where(Job.work_status != "")
    if active_only:
        stmt = stmt.where(Job.work_status.in_(ops.ACTIVE))
    return [j for j in db.scalars(stmt) if can_see_job(user, j)]


# --- finance ---
@router.get("/finance/wip")
def wip(include_closed: bool = False, sector: str = "", db: Session = Depends(get_db), user: User = Depends(current_user)):
    jobs = [j for j in _jobs(db, user, not include_closed) if not sector or j.sector == sector or (sector == "civil" and j.kind == "civil")]
    return finance.wip(db, jobs)


@router.get("/finance/wip.csv")
def wip_csv(db: Session = Depends(get_db), user: User = Depends(current_user)):
    w = finance.wip(db, _jobs(db, user, True))
    buf = io.StringIO()
    cols = ["job_no", "name", "customer", "status", "revenue", "budget_cost", "cost_to_date", "committed", "forecast_cost", "cost_to_complete",
            "forecast_margin", "forecast_margin_pct", "percent_complete", "earned", "invoiced", "over_under_billed", "retention_held"]
    wr = csv.writer(buf)
    wr.writerow(cols)
    for r in w["rows"]:
        wr.writerow([r.get(c) for c in cols])
    return Response(buf.getvalue(), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="wip.csv"'})


@router.get("/finance/month")
def month(day: date | None = None, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return finance.month_to_date(db, _jobs(db, user), day)


@router.get("/finance/cashflow")
def cashflow(weeks: int = 13, opening: float | None = None, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return finance.cashflow(db, _jobs(db, user), max(4, min(weeks, 52)), opening=opening)


@router.get("/finance/dashboard")
def dashboard(db: Session = Depends(get_db), user: User = Depends(current_user)):
    """The business at a glance: this month against forecast, WIP, cash, debtors, jobs going over, feedback."""
    from .. import purchasing

    jobs = _jobs(db, user, True)
    w = finance.wip(db, jobs)
    cf = finance.cashflow(db, jobs, 13)
    return {"month": finance.month_to_date(db, _jobs(db, user)), "wip": w["totals"],
            "over_budget": [r for r in w["rows"] if r["over_budget"]][:10],
            "low_margin": sorted([r for r in w["rows"] if r["forecast_margin_pct"] is not None], key=lambda r: r["forecast_margin_pct"])[:5],
            "cash": {"opening": cf["opening"], "lowest": cf["lowest"], "in_13w": cf["in_total"], "out_13w": cf["out_total"],
                     "weeks": cf["weeks"]},
            "debtors": purchasing.aged_debtors(db)["buckets"], "nps": crm.nps_report(db, 3)["overall"],
            "active_jobs": len(jobs)}


class BudgetMonthIn(BaseModel):
    month: str = Field(pattern=r"^\d{4}-\d{2}$")
    revenue: float = Field(default=0, ge=0)
    labour: float = Field(default=0, ge=0)
    materials: float = Field(default=0, ge=0)
    subcontract: float = Field(default=0, ge=0)
    overheads: float = Field(default=0, ge=0)
    notes: str = ""


@router.get("/budget-months")
def budget_months(start: str | None = None, months: int = 12, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """The company forecast by month, next to what the live jobs say and what actually happened."""
    first = date.fromisoformat((start or date.today().strftime("%Y-%m")) + "-01")
    keys = []
    d = first
    for _ in range(max(1, min(months, 24))):
        keys.append(d.strftime("%Y-%m"))
        d = (d + timedelta(days=32)).replace(day=1)
    jobs = _jobs(db, user)
    derived = finance.jobs_forecast(db, jobs, keys)
    out = []
    for k in keys:
        ms, me = finance._month_bounds(k)
        act = finance.month_actuals(db, jobs, ms, min(me, date.today())) if ms <= date.today() else {"totals": {}}
        out.append({"month": k, "budget": finance.budget_for(db, k), "jobs": derived.get(k, {}), "actual": act["totals"]})
    return out


@router.put("/budget-months")
def save_budget_month(body: BudgetMonthIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    b = db.scalar(select(BudgetMonth).where(BudgetMonth.month == body.month)) or BudgetMonth(month=body.month)
    for k, v in body.model_dump().items():
        setattr(b, k, v)
    db.add(b)
    record(db, user.id, "budget_month", 0, "update", after=body.model_dump())
    db.commit()
    return finance.budget_for(db, body.month)


class FillFromJobs(BaseModel):
    months: list[str]
    overheads: float | None = None


@router.post("/budget-months/fill")
def fill(body: FillFromJobs, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Start the budget from what the live jobs say (then adjust by hand)."""
    derived = finance.jobs_forecast(db, _jobs(db, user), body.months)
    for k in body.months:
        d = derived.get(k, {})
        b = db.scalar(select(BudgetMonth).where(BudgetMonth.month == k)) or BudgetMonth(month=k)
        b.revenue, b.labour, b.materials, b.subcontract = (d.get("revenue", 0), d.get("labour", 0), d.get("materials", 0) + d.get("other", 0)
                                                           + d.get("plant", 0), d.get("subcontract", 0))
        if body.overheads is not None:
            b.overheads = body.overheads
        db.add(b)
    db.commit()
    return {"filled": len(body.months)}


# --- CRM ---
@router.get("/crm/settings")
def crm_settings(db: Session = Depends(get_db), _: User = Depends(current_user)):
    from .. import messaging

    return {"client_types": crm.CLIENT_TYPES, "departments": crm.DEPARTMENTS, "triggers": crm.TRIGGERS, "ratings": crm.RATINGS,
            "email_ready": messaging.email_ready(), "sms_ready": messaging.sms_ready(),
            "google_review_url": ops.settings(db).get("google_review_url", "")}


class RuleIn(BaseModel):
    name: str = Field(min_length=1)
    trigger: str = "invoice_sent"
    client_types: list[str] = []
    departments: list[str] = []
    delay_days: int = Field(default=2, ge=0, le=60)
    channel: str = "email"
    subject: str = ""
    body: str = Field(min_length=1)
    ask_feedback: bool = True
    ask_review: bool = False
    min_days_between: int = Field(default=30, ge=0, le=365)
    active: bool = True


RULE_FIELDS = list(RuleIn.model_fields)


def _rule(r: CrmRule) -> dict:
    return {"id": r.id, **{f: getattr(r, f) for f in RULE_FIELDS}}


def _check_rule(body: RuleIn) -> None:
    if body.trigger not in crm.TRIGGERS or body.channel not in ("email", "sms"):
        raise HTTPException(422, "Unknown trigger or channel")
    if set(body.client_types) - set(crm.CLIENT_TYPES) or set(body.departments) - set(crm.DEPARTMENTS):
        raise HTTPException(422, "Unknown client type or department")
    if (body.ask_feedback or body.ask_review) and "{feedback_link}" not in body.body:
        raise HTTPException(422, "Put {feedback_link} in the message so they can answer")


@router.get("/crm/rules")
def rules(db: Session = Depends(get_db), _: User = Depends(current_user)):
    return [_rule(r) for r in db.scalars(select(CrmRule).order_by(CrmRule.id))]


@router.post("/crm/rules")
def add_rule(body: RuleIn, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    _check_rule(body)
    r = CrmRule(**body.model_dump())
    db.add(r)
    db.commit()
    return _rule(r)


@router.put("/crm/rules/{rule_id}")
def edit_rule(rule_id: int, body: RuleIn, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    _check_rule(body)
    r = get_or_404(db, CrmRule, rule_id)
    for k, v in body.model_dump().items():
        setattr(r, k, v)
    db.commit()
    return _rule(r)


@router.get("/crm/nps")
def nps(months: int = 12, db: Session = Depends(get_db), _: User = Depends(current_user)):
    return crm.nps_report(db, max(1, min(months, 36)))


@router.get("/crm/messages")
def messages(status: str = "", db: Session = Depends(get_db), _: User = Depends(current_user)):
    stmt = select(OutboundMessage).order_by(OutboundMessage.send_at.desc())
    if status:
        stmt = stmt.where(OutboundMessage.status == status)
    custs = {c.id: c.name for c in db.scalars(select(Customer))}
    return [{"id": m.id, "customer": custs.get(m.customer_id, ""), "customer_id": m.customer_id, "channel": m.channel, "to": m.to,
             "subject": m.subject, "body": m.body, "send_at": m.send_at.isoformat(), "status": m.status, "error": m.error,
             "sent_at": m.sent_at.isoformat() if m.sent_at else None} for m in db.scalars(stmt.limit(300))]


@router.post("/crm/messages/{msg_id}/cancel")
def cancel_message(msg_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    m = get_or_404(db, OutboundMessage, msg_id)
    if m.status == "queued":
        m.status = "cancelled"
    db.commit()
    return {"status": m.status}


@router.post("/crm/send-now")
def send_now(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    out = crm.send_due(db)
    db.commit()
    return out


class ActivityIn(BaseModel):
    kind: str = "note"
    text: str = Field(min_length=1)
    due_date: date | None = None
    job_id: int | None = None
    done: bool = False


@router.post("/crm/customers/{customer_id}/activities")
def add_activity(customer_id: int, body: ActivityIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    get_or_404(db, Customer, customer_id)
    a = CrmActivity(customer_id=customer_id, user_id=user.id, **body.model_dump())
    db.add(a)
    db.commit()
    return {"id": a.id}


@router.put("/crm/activities/{activity_id}")
def done_activity(activity_id: int, body: ActivityIn, db: Session = Depends(get_db), _: User = Depends(current_user)):
    a = get_or_404(db, CrmActivity, activity_id)
    a.text, a.due_date, a.done, a.kind = body.text, body.due_date, body.done, body.kind
    db.commit()
    return {"id": a.id, "done": a.done}


@router.get("/crm/tasks")
def tasks(db: Session = Depends(get_db), _: User = Depends(current_user)):
    custs = {c.id: c.name for c in db.scalars(select(Customer))}
    return [{"id": a.id, "customer_id": a.customer_id, "customer": custs.get(a.customer_id, ""), "text": a.text,
             "due_date": a.due_date.isoformat() if a.due_date else None, "job_id": a.job_id}
            for a in db.scalars(select(CrmActivity).where(CrmActivity.kind == "task", CrmActivity.done.is_(False))
                                .order_by(CrmActivity.due_date))]


@router.post("/crm/feedback/{fb_id}/followed-up")
def followed_up(fb_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    f = get_or_404(db, Feedback, fb_id)
    f.followed_up = True
    db.commit()
    return {"id": f.id}


class SendFeedback(BaseModel):
    customer_id: int
    job_id: int | None = None
    rule_id: int


@router.post("/crm/request-feedback")
def request_feedback(body: SendFeedback, db: Session = Depends(get_db), _: User = Depends(current_user)):
    """Send one rule's message to one customer now (e.g. a builder you've just finished with)."""
    c = get_or_404(db, Customer, body.customer_id)
    r = get_or_404(db, CrmRule, body.rule_id)
    j = db.get(Job, body.job_id) if body.job_id else None
    m = crm.queue(db, r, c, j, kind="monthly" if r.trigger == "monthly" else "job",
                  period=date.today().strftime("%Y-%m") if r.trigger == "monthly" else "", delay_days=0)
    if m is None:
        db.commit()
        raise HTTPException(422, f"{c.name} has no {'mobile' if r.channel == 'sms' else 'email'} on file")
    crm.send_due(db)
    db.commit()
    return {"id": m.id, "status": m.status, "error": m.error}


# --- public feedback form (no sign-in; the token is the key) ---
@public.get("/feedback/{token}")
def feedback_form(token: str, db: Session = Depends(get_db)):
    f = db.scalar(select(Feedback).where(Feedback.token == token))
    if f is None:
        raise HTTPException(404, "This link isn't valid")
    j = db.get(Job, f.job_id) if f.job_id else None
    return {"company": ops.settings(db)["company_name"], "name": f.contact_name, "kind": f.kind, "period": f.period,
            "job": j.name if j and f.kind == "job" else "", "answered": f.responded_at is not None, "ratings": crm.RATINGS}


class FeedbackIn(BaseModel):
    score: int = Field(ge=0, le=10)
    ratings: dict[str, int] = {}
    comment: str = ""


@public.post("/feedback/{token}")
def feedback_answer(token: str, body: FeedbackIn, db: Session = Depends(get_db)):
    f = db.scalar(select(Feedback).where(Feedback.token == token))
    if f is None:
        raise HTTPException(404, "This link isn't valid")
    if f.responded_at is not None:
        raise HTTPException(409, "Thanks, we already have your answer")
    out = crm.answer(db, f, body.score, body.ratings, body.comment)
    db.commit()
    return out


@public.post("/feedback/{token}/review-click", status_code=204)
def review_click(token: str, db: Session = Depends(get_db)):
    f = db.scalar(select(Feedback).where(Feedback.token == token))
    if f is not None:
        f.review_clicked = True
        db.commit()


# --- Xero ---
@router.get("/integrations")
def integrations(db: Session = Depends(get_db), _: User = Depends(current_user)):
    out = {"xero": xero.status(db)}
    db.commit()
    return out


@router.get("/integrations/xero/connect")
def xero_connect(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    try:
        url = xero.auth_url(db)
    except xero.XeroError as e:
        raise HTTPException(422, str(e))
    db.commit()
    return {"url": url}


@public.get("/xero-callback")
def xero_callback(code: str = "", state: str = "", error: str = "", db: Session = Depends(get_db)):
    return _finish_xero(code, state, error, db)


def _finish_xero(code: str, state: str, error: str, db: Session):
    if error or not code:
        return RedirectResponse(f"/admin?tab=integrations&xero_error={error or 'cancelled'}")
    try:
        xero.finish_connect(db, code, state)
        xero.sync(db)
        db.commit()
    except xero.XeroError as e:
        db.rollback()
        return RedirectResponse(f"/admin?tab=integrations&xero_error={str(e)[:200]}")
    return RedirectResponse("/admin?tab=integrations&xero=connected")


class XeroSettings(BaseModel):
    sales_account: str = "200"
    retention_account: str = ""
    invoice_status: str = "AUTHORISED"
    tax_type: str = "OUTPUT"
    push_invoices: bool = True
    pull_payments: bool = True
    pull_bills: bool = True
    pull_sales: bool = True
    pull_bank: bool = True


@router.put("/integrations/xero")
def xero_settings(body: XeroSettings, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    if body.invoice_status not in ("DRAFT", "SUBMITTED", "AUTHORISED"):
        raise HTTPException(422, "Invoices go to Xero as DRAFT, SUBMITTED or AUTHORISED")
    i = xero.record(db)
    i.settings = body.model_dump()
    db.commit()
    return xero.status(db)


@router.post("/integrations/xero/sync")
def xero_sync(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    out = xero.sync(db)
    db.commit()
    return out


@router.post("/integrations/xero/disconnect")
def xero_disconnect(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    xero.disconnect(db)
    db.commit()
    return xero.status(db)


# --- supplier price files ---
@router.post("/supplier-prices/preview")
async def preview(file: UploadFile = File(...), supplier_id: int = Form(...), db: Session = Depends(get_db), _: User = Depends(current_user)):
    """Read the file and show which columns were found, before loading it."""
    s = get_or_404(db, Supplier, supplier_id)
    rows = read_rows(file.filename or "", await file.read())
    if not rows:
        raise HTTPException(422, "The file has no rows")
    headers = list(rows[0].keys())
    return {"headers": headers, "columns": supplier_prices.detect_columns(headers, s.price_format), "sample": rows[:5], "rows": len(rows),
            "fields": list(supplier_prices.FIELDS)}


@router.post("/supplier-prices/import")
async def import_file(file: UploadFile = File(...), supplier_id: int = Form(...), columns: str = Form("{}"), effective: str = Form(""),
                      source: str = Form("file"), db: Session = Depends(get_db), user: User = Depends(current_user)):
    import json

    s = get_or_404(db, Supplier, supplier_id)
    rows = read_rows(file.filename or "", await file.read())
    if not rows:
        raise HTTPException(422, "The file has no rows")
    cols = {k: v for k, v in (json.loads(columns or "{}") or {}).items() if v} or supplier_prices.detect_columns(list(rows[0]), s.price_format)
    try:
        imp = supplier_prices.import_prices(db, s, rows, cols, filename=file.filename or "",
                                            effective=date.fromisoformat(effective) if effective else None,
                                            source=source if source in ("file", "reece_max") else "file", user_id=user.id)
    except ValueError as e:
        raise HTTPException(422, str(e))
    record(db, user.id, "supplier", s.id, "price_import", after={"rows": imp.rows, "new": imp.new_items, "up": imp.price_up,
                                                                 "down": imp.price_down})
    db.commit()
    return {"rows": imp.rows, "new_items": imp.new_items, "price_up": imp.price_up, "price_down": imp.price_down}


@router.get("/supplier-prices/imports")
def imports(db: Session = Depends(get_db), _: User = Depends(current_user)):
    sups = {s.id: s.name for s in db.scalars(select(Supplier))}
    return [{"id": i.id, "supplier": sups.get(i.supplier_id, ""), "supplier_id": i.supplier_id, "filename": i.filename,
             "effective": i.effective.isoformat(), "rows": i.rows, "new_items": i.new_items, "price_up": i.price_up, "price_down": i.price_down,
             "source": i.source, "at": i.created_at.isoformat()} for i in db.scalars(select(PriceImport).order_by(PriceImport.id.desc()).limit(100))]


@router.get("/supplier-prices/search")
def search(q: str, db: Session = Depends(get_db), _: User = Depends(current_user)):
    return supplier_prices.search(db, q) if len(q) >= 2 else []


@router.get("/supplier-prices/history")
def history(supplier_id: int, code: str, db: Session = Depends(get_db), _: User = Depends(current_user)):
    return supplier_prices.history(db, supplier_id, code)


@router.get("/supplier-prices/compare")
def compare(group: str = "", db: Session = Depends(get_db), _: User = Depends(current_user)):
    return supplier_prices.comparison(db, group)


@router.get("/supplier-prices/compare.csv")
def compare_csv(db: Session = Depends(get_db), _: User = Depends(current_user)):
    c = supplier_prices.comparison(db, limit=100000)
    sups = sorted({p["supplier"] for r in c["rows"] for p in r["prices"]})
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Product", "Brand", "Group", "Unit", "Cheapest", "Cheapest price", *sups, "Spread %", "Qty bought (12 mo)", "Saving"])
    for r in c["rows"]:
        prices = {p["supplier"]: p["price"] for p in r["prices"]}
        w.writerow([r["description"], r["brand"], r["group"], r["unit"], r["cheapest_supplier"], r["cheapest_price"],
                    *[prices.get(s, "") for s in sups], r["spread_pct"], r["qty_bought"], r["saving"]])
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="cheapest-supplier-{date.today():%Y-%m}.csv"'})


class LinkIn(BaseModel):
    supplier_id: int
    code: str
    same_as_supplier_id: int
    same_as_code: str


@router.post("/supplier-prices/link")
def link(body: LinkIn, db: Session = Depends(get_db), _: User = Depends(current_user)):
    """Two suppliers' codes are the same product."""
    other = db.scalar(select(SupplierPrice).where(SupplierPrice.supplier_id == body.same_as_supplier_id, SupplierPrice.code == body.same_as_code,
                                                  SupplierPrice.current.is_(True)))
    if other is None:
        raise HTTPException(404, "That product isn't in the other supplier's prices")
    key = other.product_key or f"L:{body.same_as_supplier_id}:{body.same_as_code}"
    if not other.product_key:
        supplier_prices.link(db, body.same_as_supplier_id, body.same_as_code, key)
    supplier_prices.link(db, body.supplier_id, body.code, key)
    db.commit()
    return {"product_key": key}


class UpdateBook(BaseModel):
    mode: str = "cheapest"  # cheapest | supplier
    supplier_id: int | None = None
    label: str = ""


@router.post("/supplier-prices/update-price-book")
def update_price_book(body: UpdateBook, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """A new price-book version with item costs from the current supplier prices (cheapest, or one supplier's).
    Items are matched by code (the price book's code is a supplier or manufacturer code). Old versions keep their prices."""
    from ..models import LabourRate, Prebuild

    if user.role != "admin" and not user.can_pricing:
        raise HTTPException(403, "You can't change price books")
    base = db.scalar(select(PriceBookVersion).order_by(PriceBookVersion.id.desc()))
    if base is None:
        raise HTTPException(409, "There's no price book yet. Import one first.")
    new = PriceBookVersion(label=body.label or f"Supplier prices {date.today():%B %Y}", notes=f"Copied from {base.label}; costs from "
                           f"{'the cheapest supplier' if body.mode == 'cheapest' else 'one supplier'}",
                           default_labour_rate_code=base.default_labour_rate_code)
    db.add(new)
    db.flush()
    changed = 0
    for it in db.scalars(select(PriceItem).where(PriceItem.version_id == base.id)):
        cost, sup = it.cost, it.supplier
        if body.mode == "supplier" and body.supplier_id:
            p = db.scalar(select(SupplierPrice).where(SupplierPrice.supplier_id == body.supplier_id, SupplierPrice.current.is_(True),
                                                      (SupplierPrice.code == it.code) | (SupplierPrice.mfr_code == it.code)))
            if p:
                cost, sup = p.price, db.get(Supplier, p.supplier_id).name
        else:
            bp = supplier_prices.best_price(db, it.code)
            if bp:
                cost, sup = bp["price"], bp["supplier"]
        changed += abs(cost - it.cost) > 0.005
        db.add(PriceItem(version_id=new.id, code=it.code, description=it.description, uom=it.uom, cost=cost, supplier=sup))
    for pb in db.scalars(select(Prebuild).where(Prebuild.version_id == base.id)):
        db.add(Prebuild(version_id=new.id, code=pb.code, description=pb.description, uom=pb.uom, labour_hours=pb.labour_hours,
                        labour_rate_code=pb.labour_rate_code, components=pb.components))
    for lr in db.scalars(select(LabourRate).where(LabourRate.version_id == base.id)):
        db.add(LabourRate(version_id=new.id, code=lr.code, description=lr.description, rate=lr.rate))
    record(db, user.id, "price_book", new.id, "from_supplier_prices", after={"base": base.id, "changed": changed})
    db.commit()
    return {"version_id": new.id, "label": new.label, "changed": changed}
