"""Purchase orders, job costs, variations and invoices: the numbers and the rules."""
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import ops
from .models import BudgetLine, Customer, Invoice, Job, PoLine, PurchaseOrder, Supplier, Variation

PO_STATUSES = ["draft", "sent", "received", "billed", "cancelled"]
VAR_STATUSES = ["pending", "submitted", "approved", "rejected"]
INV_STATUSES = ["draft", "sent", "paid", "void"]


def new_po_no(db: Session, job: Job | None) -> str:
    """J26-0012-PO3 on a job (suppliers quote it back on their invoice, which is how bills find their job); PO-00041 for stock."""
    if job is not None and job.job_no:
        return f"{job.job_no}-PO{ops.next_number(db, f'po-{job.id}')}"
    return f"PO-{ops.next_number(db, 'po-stock'):05d}"


def make_po(db: Session, *, job: Job | None, supplier: Supplier | None, supplier_name: str, lines: list[dict], user_id: int | None,
            category: str = "materials", status: str = "draft", notes: str = "", required_date: date | None = None,
            delivery: str = "") -> PurchaseOrder:
    po = PurchaseOrder(po_no=new_po_no(db, job), job_id=job.id if job else None, supplier_id=supplier.id if supplier else None,
                       supplier_name=supplier.name if supplier else supplier_name, category=category, status=status, notes=notes,
                       order_date=date.today(), required_date=required_date, delivery=delivery, created_by=user_id)
    for l in lines:
        po.lines.append(PoLine(code=l.get("code", ""), description=l.get("description", ""), qty=float(l.get("qty") or 1),
                               unit=l.get("unit") or "ea", unit_cost=float(l.get("unit_cost") or 0)))
    db.add(po)
    db.flush()
    return po


def po_out(db: Session, po: PurchaseOrder, jobs: dict | None = None) -> dict:
    from .finance import po_value

    job = (jobs or {}).get(po.job_id) if jobs is not None else (db.get(Job, po.job_id) if po.job_id else None)
    return {"id": po.id, "po_no": po.po_no, "job_id": po.job_id, "job_no": job.job_no if job else "", "job": job.name if job else "",
            "supplier_id": po.supplier_id, "supplier": po.supplier_name, "category": po.category, "status": po.status,
            "order_date": po.order_date.isoformat() if po.order_date else None,
            "required_date": po.required_date.isoformat() if po.required_date else None, "delivery": po.delivery, "notes": po.notes,
            "bill_ref": po.bill_ref, "bill_amount": po.bill_amount, "bill_date": po.bill_date.isoformat() if po.bill_date else None,
            "bill_due": po.bill_due.isoformat() if po.bill_due else None, "bill_paid": po.bill_paid.isoformat() if po.bill_paid else None,
            "value": round(po_value(po), 2), "created_by": po.created_by, "xero_id": po.xero_id,
            "bill_variance": round((po.bill_amount or 0) - po_value(po), 2) if po.bill_amount is not None else None,
            "lines": [{"id": l.id, "code": l.code, "description": l.description, "qty": l.qty, "unit": l.unit, "unit_cost": l.unit_cost,
                       "received_qty": l.received_qty, "total": round(l.qty * l.unit_cost, 2)} for l in po.lines]}


def next_variation_no(db: Session, job_id: int) -> int:
    return (db.scalar(select(func.max(Variation.number)).where(Variation.job_id == job_id)) or 0) + 1


def approve_variation(db: Session, v: Variation) -> None:
    """An approved variation adds to the job's budget (its cost, and its hours as labour)."""
    if db.scalar(select(BudgetLine.id).where(BudgetLine.job_id == v.job_id, BudgetLine.source == "variation",
                                             BudgetLine.description.like(f"V{v.number} %"))):
        return
    rate = float(ops.settings(db)["default_cost_rate"])
    if v.hours:
        db.add(BudgetLine(job_id=v.job_id, category="labour", description=f"V{v.number} {v.title}"[:255], hours=v.hours,
                          cost=round(v.hours * rate, 2), source="variation"))
    if v.cost:
        db.add(BudgetLine(job_id=v.job_id, category="materials", description=f"V{v.number} {v.title}"[:255], cost=v.cost,
                          source="variation"))


def unapprove_variation(db: Session, v: Variation) -> None:
    for b in db.scalars(select(BudgetLine).where(BudgetLine.job_id == v.job_id, BudgetLine.source == "variation",
                                                 BudgetLine.description.like(f"V{v.number} %"))):
        db.delete(b)


def new_invoice_no(db: Session) -> str:
    return f"{ops.settings(db)['invoice_prefix']}{ops.next_number(db, 'invoice'):05d}"


def terms_for(db: Session, job: Job | None, customer: Customer | None) -> int:
    if job is not None and job.payment_terms_days is not None:
        return job.payment_terms_days
    if customer is not None:
        return customer.terms_days
    return int(ops.settings(db)["default_terms_days"])


def invoice_out(db: Session, inv: Invoice) -> dict:
    job = db.get(Job, inv.job_id) if inv.job_id else None
    cust = db.get(Customer, inv.customer_id) if inv.customer_id else None
    gst = round((inv.amount - inv.retention) * inv.gst_pct / 100, 2)
    return {"id": inv.id, "invoice_no": inv.invoice_no, "job_id": inv.job_id, "job_no": job.job_no if job else "",
            "job": job.name if job else "", "customer_id": inv.customer_id, "customer": cust.name if cust else (job.client if job else ""),
            "kind": inv.kind, "issue_date": inv.issue_date.isoformat(), "due_date": inv.due_date.isoformat(), "description": inv.description,
            "amount": inv.amount, "retention": inv.retention, "gst": gst, "total": round(inv.amount - inv.retention + gst, 2),
            "status": inv.status, "paid_date": inv.paid_date.isoformat() if inv.paid_date else None, "paid_amount": inv.paid_amount,
            "xero_id": inv.xero_id, "lines": inv.lines or [],
            "overdue": inv.status == "sent" and inv.due_date < date.today(),
            "days_overdue": (date.today() - inv.due_date).days if inv.status == "sent" and inv.due_date < date.today() else 0}


def aged_debtors(db: Session) -> dict:
    buckets = {"current": 0.0, "1-30": 0.0, "31-60": 0.0, "61-90": 0.0, "90+": 0.0}
    rows = []
    for inv in db.scalars(select(Invoice).where(Invoice.status == "sent")):
        o = invoice_out(db, inv)
        owing = o["total"] - (inv.paid_amount or 0)
        d = o["days_overdue"]
        key = "current" if d <= 0 else "1-30" if d <= 30 else "31-60" if d <= 60 else "61-90" if d <= 90 else "90+"
        buckets[key] += owing
        rows.append({**o, "owing": round(owing, 2), "bucket": key})
    return {"buckets": {k: round(v, 2) for k, v in buckets.items()}, "rows": sorted(rows, key=lambda r: -r["days_overdue"]),
            "total": round(sum(buckets.values()), 2)}


def due_from_terms(issue: date, terms: int) -> date:
    return issue + timedelta(days=terms)
