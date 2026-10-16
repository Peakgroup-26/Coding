"""Purchase orders, supplier bills, job costs, variations and invoices (office side)."""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import ops, purchasing
from ..access import can_see_job
from ..audit import record
from ..auth import current_user
from ..db import get_db
from ..models import Customer, Invoice, Job, JobCost, PoLine, PurchaseOrder, Supplier, User, Variation
from . import get_or_404

router = APIRouter(prefix="/api", tags=["purchasing"])


# --- purchase orders ---
class LineIn(BaseModel):
    code: str = ""
    description: str = ""
    qty: float = Field(default=1, ge=0)
    unit: str = "ea"
    unit_cost: float = Field(default=0, ge=0)
    received_qty: float = Field(default=0, ge=0)


class PoIn(BaseModel):
    job_id: int | None = None
    supplier_id: int | None = None
    supplier_name: str = ""
    category: str = "materials"
    status: str = "draft"
    required_date: date | None = None
    delivery: str = ""
    notes: str = ""
    lines: list[LineIn] = []


@router.get("/purchase-orders")
def list_pos(status: str = "", job_id: int | None = None, supplier_id: int | None = None, q: str = "", db: Session = Depends(get_db),
             user: User = Depends(current_user)):
    stmt = select(PurchaseOrder).order_by(PurchaseOrder.id.desc())
    if status:
        stmt = stmt.where(PurchaseOrder.status == status)
    if job_id:
        stmt = stmt.where(PurchaseOrder.job_id == job_id)
    if supplier_id:
        stmt = stmt.where(PurchaseOrder.supplier_id == supplier_id)
    pos = list(db.scalars(stmt.limit(500)))
    jobs = {j.id: j for j in db.scalars(select(Job).where(Job.id.in_({p.job_id for p in pos if p.job_id})))} if pos else {}
    out = []
    for p in pos:
        if p.job_id and not can_see_job(user, jobs[p.job_id]):
            continue
        row = purchasing.po_out(db, p, jobs)
        if q and q.lower() not in f"{row['po_no']} {row['supplier']} {row['job']} {row['job_no']} {row['bill_ref']}".lower():
            continue
        out.append(row)
    return out


@router.post("/purchase-orders")
def add_po(body: PoIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    job = get_or_404(db, Job, body.job_id) if body.job_id else None
    sup = get_or_404(db, Supplier, body.supplier_id) if body.supplier_id else None
    if body.category not in ops.CATEGORIES or body.status not in ("draft", "sent"):
        raise HTTPException(422, "Unknown category or status")
    po = purchasing.make_po(db, job=job, supplier=sup, supplier_name=body.supplier_name, lines=[l.model_dump() for l in body.lines],
                            user_id=user.id, category=body.category, status=body.status, notes=body.notes,
                            required_date=body.required_date, delivery=body.delivery)
    record(db, user.id, "purchase_order", po.id, "create", after={"job_id": po.job_id, "po_no": po.po_no})
    db.commit()
    return purchasing.po_out(db, po)


@router.get("/purchase-orders/{po_id}")
def get_po(po_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    return purchasing.po_out(db, get_or_404(db, PurchaseOrder, po_id))


@router.put("/purchase-orders/{po_id}")
def update_po(po_id: int, body: PoIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    po = get_or_404(db, PurchaseOrder, po_id)
    if body.status not in purchasing.PO_STATUSES or body.category not in ops.CATEGORIES:
        raise HTTPException(422, "Unknown status or category")
    before = purchasing.po_out(db, po)
    po.supplier_id = body.supplier_id
    po.supplier_name = (db.get(Supplier, body.supplier_id).name if body.supplier_id and db.get(Supplier, body.supplier_id)
                        else body.supplier_name)
    po.category, po.status, po.required_date, po.delivery, po.notes = body.category, body.status, body.required_date, body.delivery, body.notes
    if body.job_id != po.job_id:
        po.job_id = body.job_id
    po.lines.clear()
    db.flush()
    for l in body.lines:
        po.lines.append(PoLine(**l.model_dump()))
    if po.status == "received":
        for l in po.lines:
            l.received_qty = l.received_qty or l.qty
    record(db, user.id, "purchase_order", po.id, "update", {"job_id": po.job_id, **before}, {"job_id": po.job_id, **purchasing.po_out(db, po)})
    db.commit()
    return purchasing.po_out(db, po)


class BillIn(BaseModel):
    bill_ref: str = ""
    bill_amount: float = Field(ge=0)
    bill_date: date
    bill_due: date | None = None
    paid: date | None = None


@router.post("/purchase-orders/{po_id}/bill")
def bill_po(po_id: int, body: BillIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """The supplier's invoice for this PO. A bill more than 2% off the PO is flagged on the PO list."""
    po = get_or_404(db, PurchaseOrder, po_id)
    sup = db.get(Supplier, po.supplier_id) if po.supplier_id else None
    from ..finance import _supplier_due

    po.bill_ref, po.bill_amount, po.bill_date = body.bill_ref, body.bill_amount, body.bill_date
    po.bill_due = body.bill_due or _supplier_due(body.bill_date, sup.terms_days if sup else 30)
    po.bill_paid = body.paid
    po.status = "billed"
    for l in po.lines:
        l.received_qty = l.received_qty or l.qty
    record(db, user.id, "purchase_order", po.id, "bill", after={"job_id": po.job_id, **body.model_dump(mode="json")})
    db.commit()
    return purchasing.po_out(db, po)


@router.get("/purchase-orders/{po_id}/print")
def print_po(po_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    po = get_or_404(db, PurchaseOrder, po_id)
    o = purchasing.po_out(db, po)
    cfg = ops.settings(db)
    rows = "".join(f"<tr><td>{l['code']}</td><td>{l['description']}</td><td>{l['qty']:g} {l['unit']}</td>"
                   f"<td>${l['unit_cost']:,.2f}</td><td>${l['total']:,.2f}</td></tr>" for l in o["lines"])
    html = f"""<!doctype html><meta charset=utf-8><title>{o['po_no']}</title>
<style>body{{font:14px system-ui;margin:32px;color:#1c2430}}table{{border-collapse:collapse;width:100%}}td,th{{border-bottom:1px solid #ddd;padding:6px;text-align:left}}</style>
<h1>Purchase order {o['po_no']}</h1><p><b>{cfg['company_name']}</b></p>
<p>To: <b>{o['supplier']}</b><br>Job: {o['job_no']} {o['job']}<br>Date: {o['order_date'] or ''}<br>Required: {o['required_date'] or ''}<br>
Delivery: {o['delivery']}</p><p>Please quote <b>{o['po_no']}</b> on your invoice.</p>
<table><tr><th>Code</th><th>Description</th><th>Qty</th><th>Unit</th><th>Total</th></tr>{rows}
<tr><td colspan=4><b>Total ex GST</b></td><td><b>${o['value']:,.2f}</b></td></tr></table><p>{o['notes']}</p>
<script>window.print()</script>"""
    return Response(html, media_type="text/html")


# --- job costs ---
class CostIn(BaseModel):
    day: date
    category: str = "materials"
    description: str = ""
    qty: float = Field(default=1, ge=0)
    unit_cost: float = Field(default=0, ge=0)
    supplier: str = ""
    ref: str = ""
    due_date: date | None = None
    paid_date: date | None = None


COST_FIELDS = ["day", "category", "description", "qty", "unit_cost", "amount", "supplier", "ref", "source", "due_date", "paid_date", "user_id",
               "sell_unit", "markup_pct"]


def _cost(c: JobCost) -> dict:
    return {"id": c.id, "job_id": c.job_id, **{f: (getattr(c, f).isoformat() if isinstance(getattr(c, f), date) else getattr(c, f))
                                               for f in COST_FIELDS}}


@router.get("/jobs/{job_id}/costs")
def list_costs(job_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    get_or_404(db, Job, job_id)
    return [_cost(c) for c in db.scalars(select(JobCost).where(JobCost.job_id == job_id).order_by(JobCost.day.desc(), JobCost.id.desc()))]


@router.post("/jobs/{job_id}/costs")
def add_cost(job_id: int, body: CostIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    get_or_404(db, Job, job_id)
    if body.category not in ops.CATEGORIES or body.category == "labour":
        raise HTTPException(422, "Labour comes from timesheets. Pick materials, subcontract, plant or other.")
    c = JobCost(job_id=job_id, **body.model_dump(), amount=round(body.qty * body.unit_cost, 2), source="office", user_id=user.id)
    db.add(c)
    db.flush()
    record(db, user.id, "job_cost", c.id, "create", after=_cost(c))
    db.commit()
    return _cost(c)


@router.put("/costs/{cost_id}")
def update_cost(cost_id: int, body: CostIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    c = get_or_404(db, JobCost, cost_id)
    before = _cost(c)
    for k, v in body.model_dump().items():
        setattr(c, k, v)
    c.amount = round(c.qty * c.unit_cost, 2)
    record(db, user.id, "job_cost", c.id, "update", before, _cost(c))
    db.commit()
    return _cost(c)


@router.delete("/costs/{cost_id}", status_code=204)
def delete_cost(cost_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    c = get_or_404(db, JobCost, cost_id)
    record(db, user.id, "job_cost", c.id, "delete", before=_cost(c))
    db.delete(c)
    db.commit()


@router.get("/stock/search")
def stock_search(q: str = "", db: Session = Depends(get_db), _: User = Depends(current_user)):
    from .. import stock

    return stock.search(db, q) if len(q.strip()) >= 2 else []


class StockUse(BaseModel):
    code: str = ""
    description: str = ""
    qty: float = Field(default=1, gt=0)
    unit: str = "ea"
    supplier_id: int | None = None
    unit_cost: float | None = Field(default=None, ge=0)  # override the price-file cost
    markup_pct: float | None = Field(default=None, ge=0, le=500)  # override the margin


@router.post("/jobs/{job_id}/materials")
def office_material(job_id: int, body: StockUse, db: Session = Depends(get_db), user: User = Depends(current_user)):
    from .field import MaterialIn, add_material

    j = get_or_404(db, Job, job_id)
    c = add_material(db, j, MaterialIn(code=body.code, description=body.description, qty=body.qty, unit=body.unit, supplier_id=body.supplier_id),
                     user, unit_cost=body.unit_cost, markup_pct=body.markup_pct)
    record(db, user.id, "job_cost", c.id, "create", after=_cost(c))
    db.commit()
    return _cost(c)


# --- variations ---
class VarIn(BaseModel):
    title: str = Field(min_length=1)
    description: str = ""
    reason: str = "client request"
    status: str = "pending"
    sell: float = Field(default=0, ge=0)
    cost: float = Field(default=0, ge=0)
    hours: float = Field(default=0, ge=0)
    client_ref: str = ""
    submitted_date: date | None = None
    decided_date: date | None = None


VAR_FIELDS = ["number", "title", "description", "reason", "status", "sell", "cost", "hours", "client_ref", "submitted_date", "decided_date"]


def _var(v: Variation) -> dict:
    return {"id": v.id, "job_id": v.job_id, **{f: (getattr(v, f).isoformat() if isinstance(getattr(v, f), date) else getattr(v, f))
                                               for f in VAR_FIELDS}}


@router.get("/jobs/{job_id}/variations")
def list_vars(job_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    get_or_404(db, Job, job_id)
    return [_var(v) for v in db.scalars(select(Variation).where(Variation.job_id == job_id).order_by(Variation.number))]


def _apply_status(db: Session, v: Variation, old: str) -> None:
    if v.status == "approved" and old != "approved":
        v.decided_date = v.decided_date or date.today()
        purchasing.approve_variation(db, v)
    elif old == "approved" and v.status != "approved":
        purchasing.unapprove_variation(db, v)
    if v.status == "submitted" and not v.submitted_date:
        v.submitted_date = date.today()
    if v.status == "rejected":
        v.decided_date = v.decided_date or date.today()


@router.post("/jobs/{job_id}/variations")
def add_var(job_id: int, body: VarIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    get_or_404(db, Job, job_id)
    if body.status not in purchasing.VAR_STATUSES:
        raise HTTPException(422, "Unknown status")
    v = Variation(job_id=job_id, number=purchasing.next_variation_no(db, job_id), created_by=user.id, **body.model_dump())
    db.add(v)
    db.flush()
    _apply_status(db, v, "")
    record(db, user.id, "variation", v.id, "create", after=_var(v))
    db.commit()
    return _var(v)


@router.put("/variations/{var_id}")
def update_var(var_id: int, body: VarIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    v = get_or_404(db, Variation, var_id)
    if body.status not in purchasing.VAR_STATUSES:
        raise HTTPException(422, "Unknown status")
    before, old = _var(v), v.status
    if old == "approved":
        purchasing.unapprove_variation(db, v)  # rebuilt below with the new figures
        db.flush()
        old = ""
    for k, val in body.model_dump().items():
        setattr(v, k, val)
    _apply_status(db, v, old)
    record(db, user.id, "variation", v.id, "update", before, _var(v))
    db.commit()
    return _var(v)


# --- invoices ---
class InvLine(BaseModel):
    description: str
    qty: float = 1
    unit_price: float = 0


class InvoiceIn(BaseModel):
    job_id: int | None = None
    customer_id: int | None = None
    kind: str = "progress"
    issue_date: date | None = None
    due_date: date | None = None
    description: str = ""
    amount: float | None = Field(default=None, ge=0)  # ex GST; worked out from the lines when they're given
    percent: float | None = Field(default=None, ge=0, le=100)  # claim this % of the job's revenue (progress claims)
    lines: list[InvLine] = []
    retention: float | None = Field(default=None, ge=0)
    gst_pct: float = 10.0
    status: str = "draft"


@router.get("/invoices")
def list_invoices(status: str = "", job_id: int | None = None, db: Session = Depends(get_db), user: User = Depends(current_user)):
    stmt = select(Invoice).order_by(Invoice.id.desc())
    if status:
        stmt = stmt.where(Invoice.status == status)
    if job_id:
        stmt = stmt.where(Invoice.job_id == job_id)
    out = []
    for inv in db.scalars(stmt.limit(500)):
        if inv.job_id:
            j = db.get(Job, inv.job_id)
            if j is not None and not can_see_job(user, j):
                continue
        out.append(purchasing.invoice_out(db, inv))
    return out


@router.get("/invoices/aged")
def aged(db: Session = Depends(get_db), _: User = Depends(current_user)):
    return purchasing.aged_debtors(db)


@router.get("/invoices/suggest/{job_id}")
def suggest(job_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    """What to put on this job's next invoice: earned but not billed (fixed price), or time and materials (do-and-charge)."""
    from ..finance import entry_hours, job_financials
    from ..models import TimeEntry

    job = get_or_404(db, Job, job_id)
    f = job_financials(db, job)
    cfg = ops.settings(db)
    if job.billing == "charge":
        lines = []
        hrs = sum(entry_hours(e) for e in db.scalars(select(TimeEntry).where(TimeEntry.job_id == job.id, TimeEntry.status != "rejected")))
        if hrs:
            lines.append({"description": "Labour", "qty": round(hrs, 2), "unit_price": float(cfg.get("default_charge_rate", 110))})
        markup = 1 + float(cfg.get("charge_materials_markup_pct", 25)) / 100
        itemised = list(db.scalars(select(JobCost).where(JobCost.job_id == job.id, JobCost.sell_unit.is_not(None))))
        for c in itemised:  # stock items at their price-file sell price
            lines.append({"description": c.description, "qty": c.qty, "unit_price": c.sell_unit})
        mats = f["cost_to_date"] - next(r["actual"] for r in f["categories"] if r["category"] == "labour") - sum(c.amount for c in itemised)
        if mats > 0.005:
            lines.append({"description": "Other materials and parts", "qty": 1, "unit_price": round(mats * markup, 2)})
        already = f["invoiced"]
        return {"kind": "final", "lines": lines, "amount": round(sum(l["qty"] * l["unit_price"] for l in lines) - already, 2),
                "note": f"Already invoiced ${already:,.2f}" if already else ""}
    amount = max(0.0, f["earned"] - f["invoiced"])
    return {"kind": "progress", "percent": f["percent_complete"], "amount": round(amount, 2),
            "retention": round(amount * (job.retention_pct or 0) / 100, 2),
            "lines": [{"description": f"Progress claim: {f['percent_complete']:.0f}% complete", "qty": 1, "unit_price": round(amount, 2)}]}


@router.post("/invoices")
def add_invoice(body: InvoiceIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    job = get_or_404(db, Job, body.job_id) if body.job_id else None
    cust = db.get(Customer, body.customer_id or (job.customer_id if job else None) or 0)
    if body.status not in ("draft", "sent"):
        raise HTTPException(422, "A new invoice is a draft or sent")
    amount = body.amount
    if body.lines:
        amount = round(sum(l.qty * l.unit_price for l in body.lines), 2)
    elif body.percent is not None and job is not None:
        from ..finance import job_financials

        f = job_financials(db, job)
        amount = round(max(0.0, f["revenue"] * body.percent / 100 - f["invoiced"]), 2)
    if amount is None:
        raise HTTPException(422, "Give an amount, a % complete, or the lines")
    issue = body.issue_date or date.today()
    due = body.due_date or purchasing.due_from_terms(issue, purchasing.terms_for(db, job, cust))
    retention = body.retention if body.retention is not None else round(amount * ((job.retention_pct if job else 0) or 0) / 100, 2)
    inv = Invoice(invoice_no=purchasing.new_invoice_no(db), job_id=job.id if job else None, customer_id=cust.id if cust else None,
                  kind=body.kind, issue_date=issue, due_date=due, description=body.description, amount=amount, retention=retention,
                  gst_pct=body.gst_pct, status="draft", lines=[l.model_dump() for l in body.lines] or None, created_by=user.id)
    db.add(inv)
    db.flush()
    record(db, user.id, "invoice", inv.id, "create", after={"job_id": inv.job_id, **purchasing.invoice_out(db, inv)})
    if body.status == "sent":
        _send(db, inv, user)
    db.commit()
    return purchasing.invoice_out(db, inv)


def _send(db: Session, inv: Invoice, user: User) -> None:
    """Mark sent; push to Xero when it's connected; start the CRM follow-ups for this kind of customer."""
    from .. import crm, xero

    inv.status = "sent"
    job = db.get(Job, inv.job_id) if inv.job_id else None
    if job is not None and inv.kind == "final" and job.work_status in ("complete", "in_progress", "scheduled"):
        job.work_status = "invoiced"
    xero.push_invoice_soon(db, inv)
    crm.on_event(db, "invoice_sent", job=job, invoice=inv)


class InvoiceStatus(BaseModel):
    status: str
    paid_date: date | None = None
    paid_amount: float | None = Field(default=None, ge=0)


@router.put("/invoices/{inv_id}/status")
def invoice_status(inv_id: int, body: InvoiceStatus, db: Session = Depends(get_db), user: User = Depends(current_user)):
    inv = get_or_404(db, Invoice, inv_id)
    if body.status not in purchasing.INV_STATUSES:
        raise HTTPException(422, "Unknown status")
    before = purchasing.invoice_out(db, inv)
    if body.status == "sent" and inv.status == "draft":
        _send(db, inv, user)
    elif body.status == "paid":
        o = purchasing.invoice_out(db, inv)
        inv.status, inv.paid_date = "paid", body.paid_date or date.today()
        inv.paid_amount = body.paid_amount if body.paid_amount is not None else o["total"]
    else:
        inv.status = body.status
    record(db, user.id, "invoice", inv.id, "status", {"job_id": inv.job_id, **before}, {"job_id": inv.job_id, **purchasing.invoice_out(db, inv)})
    db.commit()
    return purchasing.invoice_out(db, inv)


@router.get("/invoices/{inv_id}/print")
def print_invoice(inv_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    inv = get_or_404(db, Invoice, inv_id)
    o = purchasing.invoice_out(db, inv)
    cfg = ops.settings(db)
    lines = o["lines"] or [{"description": o["description"] or "Works as agreed", "qty": 1, "unit_price": o["amount"]}]
    rows = "".join(f"<tr><td>{l['description']}</td><td>{l['qty']:g}</td><td>${l['unit_price']:,.2f}</td>"
                   f"<td>${l['qty'] * l['unit_price']:,.2f}</td></tr>" for l in lines)
    ret = f"<tr><td colspan=3>Less retention</td><td>-${o['retention']:,.2f}</td></tr>" if o["retention"] else ""
    html = f"""<!doctype html><meta charset=utf-8><title>{o['invoice_no']}</title>
<style>body{{font:14px system-ui;margin:32px;color:#1c2430}}table{{border-collapse:collapse;width:100%}}td,th{{border-bottom:1px solid #ddd;padding:6px;text-align:left}}</style>
<h1>Tax invoice {o['invoice_no']}</h1><p><b>{cfg['company_name']}</b></p>
<p>To: <b>{o['customer']}</b><br>Job: {o['job_no']} {o['job']}<br>Date: {o['issue_date']}<br>Due: {o['due_date']}</p>
<p>{o['description']}</p><table><tr><th>Description</th><th>Qty</th><th>Price</th><th>Amount</th></tr>{rows}{ret}
<tr><td colspan=3>GST</td><td>${o['gst']:,.2f}</td></tr><tr><td colspan=3><b>Total inc GST</b></td><td><b>${o['total']:,.2f}</b></td></tr></table>
<script>window.print()</script>"""
    return Response(html, media_type="text/html")
