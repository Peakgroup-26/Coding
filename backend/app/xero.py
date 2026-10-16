"""Xero: a live two-way link with the company's Xero file.

Connect once (an admin signs in to Xero from Admin portal → Integrations). From then on, every few minutes:
  * customers  -> Xero contacts (matched by name, created if missing)
  * invoices   -> Xero sales invoices when sent here (numbered the same, job number in the reference)
  * payments   <- Xero: invoices paid in Xero are marked paid here, with the date and amount
  * bills      <- Xero: supplier bills quoting one of our PO numbers bill that PO; bills quoting a job number
                  become a cost on that job; anything else is overheads and stays in Xero
  * sales invoices raised straight in Xero with a job number in the reference are brought in as that job's revenue
  * bank       <- Xero: the bank balance becomes the cash flow forecast's opening balance
Tokens are kept on the server only. Nothing is ever deleted in Xero.
"""
import base64
import logging
import re
import secrets
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import config, ops
from .models import AppSetting, Customer, Integration, Invoice, Job, JobCost, PurchaseOrder, Supplier

log = logging.getLogger(__name__)
AUTH_URL = "https://login.xero.com/identity/connect/authorize"
TOKEN_URL = "https://identity.xero.com/connect/token"
CONNECTIONS_URL = "https://api.xero.com/connections"
API = "https://api.xero.com/api.xro/2.0"
DEFAULTS = {"sales_account": "200", "retention_account": "", "invoice_status": "AUTHORISED", "tax_type": "OUTPUT",
            "push_invoices": True, "pull_payments": True, "pull_bills": True, "pull_sales": True, "pull_bank": True}
_transport: httpx.BaseTransport | None = None  # tests swap in a fake Xero


class XeroError(Exception):
    pass


def configured() -> bool:
    return bool(config.XERO_CLIENT_ID and config.XERO_CLIENT_SECRET)


def record(db: Session) -> Integration:
    i = db.scalar(select(Integration).where(Integration.name == "xero"))
    if i is None:
        i = Integration(name="xero", settings=dict(DEFAULTS), log=[])
        db.add(i)
        db.flush()
    return i


def opts(i: Integration) -> dict:
    return {**DEFAULTS, **(i.settings or {})}


def redirect_uri() -> str:
    return f"{config.PUBLIC_URL}/api/public/xero-callback"


def auth_url(db: Session) -> str:
    if not configured():
        raise XeroError("Add XERO_CLIENT_ID and XERO_CLIENT_SECRET to .env first (see deploy/XERO.md)")
    state = secrets.token_urlsafe(24)
    s = db.get(AppSetting, "xero_state") or AppSetting(key="xero_state", value={})
    s.value = {"state": state, "at": datetime.now(timezone.utc).isoformat()}
    db.merge(s)
    return AUTH_URL + "?" + urlencode({"response_type": "code", "client_id": config.XERO_CLIENT_ID, "redirect_uri": redirect_uri(),
                                       "scope": config.XERO_SCOPES, "state": state})


def _client() -> httpx.Client:
    return httpx.Client(timeout=30, transport=_transport)


def _basic() -> str:
    return "Basic " + base64.b64encode(f"{config.XERO_CLIENT_ID}:{config.XERO_CLIENT_SECRET}".encode()).decode()


def _save_tokens(i: Integration, tok: dict) -> None:
    i.access_token = tok["access_token"]
    i.refresh_token = tok.get("refresh_token", i.refresh_token)
    i.expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(tok.get("expires_in", 1800)) - 60)


def finish_connect(db: Session, code: str, state: str) -> Integration:
    s = db.get(AppSetting, "xero_state")
    if not s or not s.value or s.value.get("state") != state:
        raise XeroError("That Xero sign-in link has expired. Start again from Integrations.")
    i = record(db)
    with _client() as c:
        r = c.post(TOKEN_URL, headers={"Authorization": _basic()},
                   data={"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri()})
        if r.status_code != 200:
            raise XeroError(f"Xero didn't accept the sign-in ({r.status_code})")
        _save_tokens(i, r.json())
        conns = c.get(CONNECTIONS_URL, headers={"Authorization": f"Bearer {i.access_token}"}).json()
    orgs = [x for x in conns if x.get("tenantType") == "ORGANISATION"]
    if not orgs:
        raise XeroError("No Xero organisation was connected")
    i.tenant_id, i.tenant_name = orgs[0]["tenantId"], orgs[0].get("tenantName", "")
    i.status, i.last_error = "connected", ""
    db.delete(s)
    db.flush()
    return i


def _token(db: Session, i: Integration, c: httpx.Client) -> str:
    exp = i.expires_at if (i.expires_at is None or i.expires_at.tzinfo) else i.expires_at.replace(tzinfo=timezone.utc)
    if exp is None or exp <= datetime.now(timezone.utc):
        r = c.post(TOKEN_URL, headers={"Authorization": _basic()}, data={"grant_type": "refresh_token", "refresh_token": i.refresh_token})
        if r.status_code != 200:
            i.status, i.last_error = "error", "Xero sign-in has expired. Reconnect from Integrations."
            raise XeroError(i.last_error)
        _save_tokens(i, r.json())
    return i.access_token


def _api(db: Session, i: Integration, c: httpx.Client, method: str, path: str, **kw) -> dict:
    headers = {"Authorization": f"Bearer {_token(db, i, c)}", "xero-tenant-id": i.tenant_id, "Accept": "application/json",
               **kw.pop("headers", {})}
    r = c.request(method, API + path, headers=headers, **kw)
    if r.status_code == 429:
        raise XeroError("Xero asked us to slow down; trying again next round")
    if r.status_code >= 400:
        raise XeroError(f"Xero {method} {path} said {r.status_code}: {r.text[:300]}")
    return r.json() if r.content else {}


def _xdate(v: str | None) -> date | None:
    """Xero dates come as '2026-10-15T00:00:00' or '/Date(1760486400000+0000)/'."""
    if not v:
        return None
    m = re.match(r"/Date\((\d+)", v)
    if m:
        return datetime.fromtimestamp(int(m.group(1)) / 1000, timezone.utc).date()
    return date.fromisoformat(v[:10])


def push_invoice_soon(db: Session, inv: Invoice) -> None:
    """Invoices are pushed on the next sync round (within a minute when the background tasks are on)."""
    return None


def _contact_id(db: Session, i: Integration, c: httpx.Client, cust: Customer) -> str:
    if cust.xero_id:
        return cust.xero_id
    name = cust.name.replace('"', "")
    found = _api(db, i, c, "GET", "/Contacts", params={"where": f'Name=="{name}"'}).get("Contacts", [])
    if found:
        cust.xero_id = found[0]["ContactID"]
    else:
        body = {"Contacts": [{"Name": cust.name, "EmailAddress": cust.email or None, "TaxNumber": cust.abn or None,
                              "Phones": [{"PhoneType": "DEFAULT", "PhoneNumber": cust.phone}] if cust.phone else []}]}
        cust.xero_id = _api(db, i, c, "POST", "/Contacts", json=body)["Contacts"][0]["ContactID"]
    return cust.xero_id


def _push_invoices(db: Session, i: Integration, c: httpx.Client) -> int:
    o = opts(i)
    n = 0
    for inv in db.scalars(select(Invoice).where(Invoice.xero_id == "", Invoice.status.in_(("sent", "paid")))):
        job = db.get(Job, inv.job_id) if inv.job_id else None
        cust = db.get(Customer, inv.customer_id) if inv.customer_id else None
        if cust is None and job is not None and job.client:
            cust = ops.find_or_make_customer(db, job.client)
            inv.customer_id = cust.id if cust else None
        if cust is None:
            continue
        lines = [{"Description": l["description"], "Quantity": l["qty"], "UnitAmount": l["unit_price"], "AccountCode": o["sales_account"],
                  "TaxType": o["tax_type"]} for l in (inv.lines or [])] or \
                [{"Description": inv.description or (f"{job.job_no} {job.name}" if job else "Works"), "Quantity": 1, "UnitAmount": inv.amount,
                  "AccountCode": o["sales_account"], "TaxType": o["tax_type"]}]
        if inv.retention:
            lines.append({"Description": "Less retention", "Quantity": 1, "UnitAmount": -inv.retention,
                          "AccountCode": o["retention_account"] or o["sales_account"], "TaxType": o["tax_type"]})
        body = {"Invoices": [{"Type": "ACCREC", "Contact": {"ContactID": _contact_id(db, i, c, cust)}, "InvoiceNumber": inv.invoice_no,
                              "Reference": " ".join(x for x in ((job.job_no if job else ""), (job.order_no if job else "")) if x),
                              "Date": inv.issue_date.isoformat(), "DueDate": inv.due_date.isoformat(), "LineAmountTypes": "Exclusive",
                              "Status": o["invoice_status"], "LineItems": lines}]}
        res = _api(db, i, c, "POST", "/Invoices", json=body)
        inv.xero_id = res["Invoices"][0]["InvoiceID"]
        n += 1
    return n


def _pull_payments(db: Session, i: Integration, c: httpx.Client) -> int:
    ids = {inv.xero_id: inv for inv in db.scalars(select(Invoice).where(Invoice.xero_id != "", Invoice.status == "sent"))}
    n = 0
    keys = list(ids)
    for k in range(0, len(keys), 40):
        for x in _api(db, i, c, "GET", "/Invoices", params={"IDs": ",".join(keys[k:k + 40])}).get("Invoices", []):
            inv = ids.get(x["InvoiceID"])
            if inv is None:
                continue
            paid = float(x.get("AmountPaid") or 0)
            if x.get("Status") == "PAID":
                inv.status, inv.paid_date, inv.paid_amount = "paid", _xdate(x.get("FullyPaidOnDate")) or date.today(), paid
                n += 1
            elif paid and paid != inv.paid_amount:
                inv.paid_amount = paid
            if x.get("Status") in ("VOIDED", "DELETED"):
                inv.status = "void"
    return n


PO_RE = re.compile(r"\b([A-Z]{1,4}\d{2}-\d{4}-PO\d+|PO-\d{5})\b", re.I)


def _since(i: Integration) -> str:
    last = i.last_sync or (datetime.now(timezone.utc) - timedelta(days=60))
    last = last if last.tzinfo else last.replace(tzinfo=timezone.utc)
    return (last - timedelta(minutes=5)).strftime("%a, %d %b %Y %H:%M:%S GMT")


def _pull_bills(db: Session, i: Integration, c: httpx.Client) -> int:
    n = 0
    jobs_by_no = {j.job_no.upper(): j for j in db.scalars(select(Job).where(Job.job_no != ""))}
    res = _api(db, i, c, "GET", "/Invoices", params={"where": 'Type=="ACCPAY"', "page": 1}, headers={"If-Modified-Since": _since(i)})
    for x in res.get("Invoices", []):
        if x.get("Status") in ("DRAFT", "DELETED", "VOIDED"):
            continue
        text = f"{x.get('Reference', '')} {x.get('InvoiceNumber', '')}"
        sub = float(x.get("SubTotal") or 0)
        when = _xdate(x.get("DateString") or x.get("Date")) or date.today()
        due = _xdate(x.get("DueDateString") or x.get("DueDate"))
        paid = _xdate(x.get("FullyPaidOnDate")) if x.get("Status") == "PAID" else None
        m = PO_RE.search(text)
        po = db.scalar(select(PurchaseOrder).where(PurchaseOrder.po_no == m.group(1).upper())) if m else None
        if po is None and m:
            po = db.scalar(select(PurchaseOrder).where(PurchaseOrder.po_no.ilike(m.group(1))))
        if po is not None:
            if po.xero_id != x["InvoiceID"] or po.bill_paid != paid or po.bill_amount != sub:
                po.xero_id, po.bill_ref, po.bill_amount, po.bill_date, po.bill_due, po.bill_paid = (
                    x["InvoiceID"], x.get("InvoiceNumber", ""), sub, when, due, paid)
                po.status = "billed"
                n += 1
            continue
        job = next((j for no, j in jobs_by_no.items() if no and no in text.upper()), None)
        if job is None:
            continue
        cost = db.scalar(select(JobCost).where(JobCost.xero_id == x["InvoiceID"]))
        sup = (x.get("Contact") or {}).get("Name", "")
        if cost is None:
            cost = JobCost(job_id=job.id, day=when, category="materials", description=f"Bill {x.get('InvoiceNumber', '')} from {sup}"[:500],
                           qty=1, unit_cost=sub, amount=sub, supplier=sup, ref=x.get("InvoiceNumber", ""), source="xero",
                           xero_id=x["InvoiceID"], due_date=due, paid_date=paid)
            sup_rec = db.scalar(select(Supplier).where(Supplier.name == sup))
            if sup_rec is not None and sup_rec.kind in ("subcontractor", "plant"):
                cost.category = "subcontract" if sup_rec.kind == "subcontractor" else "plant"
            db.add(cost)
            n += 1
        else:
            cost.amount = cost.unit_cost = sub
            cost.paid_date, cost.due_date = paid, due
    return n


def _pull_sales(db: Session, i: Integration, c: httpx.Client) -> int:
    """Sales invoices raised in Xero (not here) that name a job number: counted as that job's revenue."""
    n = 0
    jobs_by_no = {j.job_no.upper(): j for j in db.scalars(select(Job).where(Job.job_no != ""))}
    known = {x for x in db.scalars(select(Invoice.xero_id).where(Invoice.xero_id != ""))}
    res = _api(db, i, c, "GET", "/Invoices", params={"where": 'Type=="ACCREC"', "page": 1}, headers={"If-Modified-Since": _since(i)})
    for x in res.get("Invoices", []):
        if x["InvoiceID"] in known or x.get("Status") in ("DRAFT", "DELETED", "VOIDED", "SUBMITTED"):
            continue
        text = f"{x.get('Reference', '')} {x.get('InvoiceNumber', '')}".upper()
        job = next((j for no, j in jobs_by_no.items() if no and no in text), None)
        if job is None:
            continue
        when = _xdate(x.get("DateString") or x.get("Date")) or date.today()
        db.add(Invoice(invoice_no=x.get("InvoiceNumber") or "XERO", job_id=job.id, customer_id=job.customer_id, kind="progress",
                       issue_date=when, due_date=_xdate(x.get("DueDateString") or x.get("DueDate")) or when,
                       description=f"From Xero: {x.get('Reference', '')}", amount=float(x.get("SubTotal") or 0),
                       status="paid" if x.get("Status") == "PAID" else "sent", paid_amount=float(x.get("AmountPaid") or 0),
                       paid_date=_xdate(x.get("FullyPaidOnDate")), xero_id=x["InvoiceID"]))
        n += 1
    return n


def _pull_bank(db: Session, i: Integration, c: httpx.Client) -> float | None:
    rep = _api(db, i, c, "GET", "/Reports/BankSummary").get("Reports", [])
    if not rep:
        return None
    total = 0.0
    for section in rep[0].get("Rows", []):
        for row in section.get("Rows", []) or []:
            cells = row.get("Cells") or []
            if row.get("RowType") == "Row" and len(cells) >= 5:
                try:
                    total += float(cells[-1].get("Value") or 0)
                except ValueError:
                    pass
    s = db.get(AppSetting, "ops") or AppSetting(key="ops", value={})
    s.value = {**(s.value or {}), "opening_bank_balance": round(total, 2), "opening_balance_date": date.today().isoformat(),
               "opening_balance_source": "Xero"}
    db.merge(s)
    return total


def sync(db: Session, full: bool = True) -> dict:
    """One round. Each part runs on its own so one failure doesn't stop the rest."""
    i = record(db)
    if i.status not in ("connected", "error") or not i.refresh_token:
        return {"skipped": "not connected"}
    o = opts(i)
    result, errors = {}, []
    parts = [("invoices_pushed", o["push_invoices"], _push_invoices)]
    if full:
        parts += [("payments", o["pull_payments"], _pull_payments), ("bills", o["pull_bills"], _pull_bills),
                  ("sales", o["pull_sales"], _pull_sales), ("bank_balance", o["pull_bank"], _pull_bank)]
    with _client() as c:
        for name, on, fn in parts:
            if not on:
                continue
            try:
                result[name] = fn(db, i, c)
                db.flush()
            except XeroError as e:
                errors.append(f"{name}: {e}")
            except Exception as e:  # noqa: BLE001 - keep going with the other parts
                log.exception("Xero %s failed", name)
                errors.append(f"{name}: {e}")
    if full:
        i.last_sync = datetime.now(timezone.utc)
    i.last_error = "; ".join(errors)
    if not any("sign-in has expired" in e for e in errors):
        i.status = "connected"
    i.log = ([{"at": datetime.now(timezone.utc).isoformat(), **result, "errors": errors}] + (i.log or []))[:30]
    return {**result, "errors": errors}


def status(db: Session) -> dict:
    i = record(db)
    return {"configured": configured(), "status": i.status, "organisation": i.tenant_name,
            "last_sync": i.last_sync.isoformat() if i.last_sync else None, "last_error": i.last_error, "settings": opts(i),
            "log": (i.log or [])[:10], "redirect_uri": redirect_uri(), "scopes": config.XERO_SCOPES}


def disconnect(db: Session) -> None:
    i = record(db)
    i.status, i.access_token, i.refresh_token, i.tenant_id, i.tenant_name = "disconnected", "", "", "", ""
