"""CRM: customer types, follow-ups after invoices and completed jobs, feedback forms, Google reviews and NPS.

How it flows:
  1. An invoice is sent (or a job completed). Each active rule whose trigger, client type and department
     match queues a message for `delay_days` later (sent at 9am Brisbane time).
  2. If the rule asks for feedback, the message carries a private link to a two-minute form: the NPS question
     (0-10, "how likely are you to recommend us?"), a few 1-5 ratings and a comment.
  3. A promoter (9-10) on a rule that asks for reviews is then offered the Google review link. A detractor
     (0-6) alerts the admins and puts a "call them" task on the customer.
  4. Monthly rules send a "how did we go on your job this month?" check-in to commercial / civil clients
     with work in the past month, so builders get scored month by month.
NPS = % promoters - % detractors, by department, client type, customer and month.
"""
import secrets
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import config, messaging, ops
from .models import (CrmActivity, CrmRule, Customer, CustomerContact, Feedback, Invoice, Job, OutboundMessage, TimeEntry, User)
from .timesheets import TZ

CLIENT_TYPES = {
    "residential": "Residential (homeowner)", "maintenance": "Maintenance customer", "strata": "Strata / real estate",
    "builder": "Builder", "commercial": "Commercial client", "civil": "Civil client", "government": "Government / council",
    "other": "Other",
}
TRIGGERS = {"invoice_sent": "Any invoice sent", "final_invoice_sent": "Final / service invoice sent", "job_complete": "Job completed",
            "monthly": "Monthly check-in"}
DEPARTMENTS = {"residential": "Residential", "commercial": "Commercial", "maintenance": "Maintenance", "civil": "Civil"}
# Which department a customer's feedback counts towards when it isn't about a particular job.
DEPT_FOR_TYPE = {"residential": "residential", "maintenance": "maintenance", "strata": "maintenance", "builder": "commercial",
                 "commercial": "commercial", "government": "commercial", "civil": "civil", "other": "commercial"}
RATINGS = {"quality": "Quality of work", "communication": "Communication", "timeliness": "On time", "cleanliness": "Tidy site",
           "value": "Value for money"}

DEFAULT_RULES = [
    {"name": "Thanks + Google review (homeowners & maintenance)", "trigger": "invoice_sent",
     "client_types": ["residential", "maintenance", "strata"], "delay_days": 2, "channel": "email", "ask_feedback": True, "ask_review": True,
     "subject": "Thanks from {company}",
     "body": "Hi {first_name},\n\nThanks for having us out for {job}. We'd love to know how we went: it takes two minutes.\n\n"
             "{feedback_link}\n\nThanks,\nThe team at {company}"},
    {"name": "Builder feedback after final invoice", "trigger": "final_invoice_sent", "client_types": ["builder"], "delay_days": 3,
     "channel": "email", "ask_feedback": True, "ask_review": True,
     "subject": "How did we go on {job}?",
     "body": "Hi {first_name},\n\nThanks for the work on {job} ({job_no}). Could you tell us how we went? Your feedback goes straight "
             "to our managers.\n\n{feedback_link}\n\nThanks,\n{company}"},
    {"name": "Monthly check-in (commercial & civil)", "trigger": "monthly", "client_types": ["commercial", "civil", "government", "builder"],
     "departments": ["commercial", "civil"], "delay_days": 0, "channel": "email", "ask_feedback": True, "ask_review": False,
     "min_days_between": 25,
     "subject": "How did we go this month?",
     "body": "Hi {first_name},\n\nA quick one: how did {company} go on your jobs last month? Two minutes, and it helps us keep "
             "standards up.\n\n{feedback_link}\n\nThanks,\n{company}"},
]


def seed_rules(db: Session) -> None:
    if db.scalar(select(CrmRule.id).limit(1)):
        return
    for r in DEFAULT_RULES:
        db.add(CrmRule(**r))
    db.flush()


def nine_am(d: date) -> datetime:
    return datetime.combine(d, time(9, 0), tzinfo=TZ).astimezone(timezone.utc)


def contact_for(db: Session, c: Customer, job: Job | None) -> tuple[str, str, str]:
    """(name, email, phone): the job's contact, else the first contact, else the customer record."""
    first = db.scalar(select(CustomerContact).where(CustomerContact.customer_id == c.id).order_by(CustomerContact.id))
    name = (job.contact if job and job.contact and "@" not in job.contact else "") or (first.name if first else "") or c.name
    email = (first.email if first and first.email else "") or c.email
    if job and job.contact and "@" in job.contact:
        email = next((w.strip(",;") for w in job.contact.split() if "@" in w), email)
    phone = (first.phone if first and first.phone else "") or c.phone
    return name, email, phone


def render(text: str, ctx: dict) -> str:
    out = text or ""
    for k, v in ctx.items():
        out = out.replace("{" + k + "}", str(v or ""))
    return out


def _matches(rule: CrmRule, c: Customer, job: Job | None) -> bool:
    if rule.client_types and c.kind not in rule.client_types:
        return False
    if rule.departments and ops.department(job) not in rule.departments:
        return False
    return True


def _recently(db: Session, rule: CrmRule, c: Customer, now: datetime) -> bool:
    if not rule.min_days_between:
        return False
    since = now - timedelta(days=rule.min_days_between)
    return db.scalar(select(OutboundMessage.id).where(OutboundMessage.customer_id == c.id, OutboundMessage.rule_id == rule.id,
                                                      OutboundMessage.created_at >= since,
                                                      OutboundMessage.status.in_(("queued", "sent")))) is not None


def queue(db: Session, rule: CrmRule, c: Customer, job: Job | None, invoice: Invoice | None = None, *, kind: str = "job",
          period: str = "", send_on: date | None = None, delay_days: int | None = None) -> OutboundMessage | None:
    name, email, phone = contact_for(db, c, job)
    to = phone if rule.channel == "sms" else email
    if not to:
        db.add(CrmActivity(customer_id=c.id, kind="task", text=f"No {'mobile' if rule.channel == 'sms' else 'email'} for "
                                                                f"{c.name}: \"{rule.name}\" wasn't sent", job_id=job.id if job else None))
        return None
    fb = None
    if rule.ask_feedback or rule.ask_review:
        fb = Feedback(token=secrets.token_urlsafe(24), customer_id=c.id, job_id=job.id if job else None, kind=kind,
                      department=ops.department(job) or DEPT_FOR_TYPE.get(c.kind, "commercial"),
                      period=period, contact_name=name)
        db.add(fb)
        db.flush()
    cfg = ops.settings(db)
    link = f"{config.PUBLIC_URL}/feedback/{fb.token}" if fb else ""
    ctx = {"first_name": name.split()[0] if name else "there", "customer": c.name, "job": job.name if job else "your job",
           "job_no": job.job_no if job else "", "company": cfg["company_name"], "feedback_link": link,
           "review_link": cfg.get("google_review_url") or "", "invoice_no": invoice.invoice_no if invoice else ""}
    delay = rule.delay_days if delay_days is None else delay_days
    when = nine_am((send_on or date.today()) + timedelta(days=delay)) if delay else datetime.now(timezone.utc)
    if when < datetime.now(timezone.utc):
        when = datetime.now(timezone.utc)
    m = OutboundMessage(customer_id=c.id, job_id=job.id if job else None, invoice_id=invoice.id if invoice else None, rule_id=rule.id,
                        feedback_id=fb.id if fb else None, channel=rule.channel, to=to, subject=render(rule.subject, ctx),
                        body=render(rule.body, ctx), send_at=when)
    db.add(m)
    db.flush()
    return m


def on_event(db: Session, trigger: str, job: Job | None = None, invoice: Invoice | None = None) -> list[OutboundMessage]:
    """An invoice went out or a job was completed: queue whatever the rules say."""
    cust_id = (invoice.customer_id if invoice else None) or (job.customer_id if job else None)
    c = db.get(Customer, cust_id) if cust_id else None
    if c is None or c.no_marketing:
        return []
    now = datetime.now(timezone.utc)
    triggers = [trigger]
    if trigger == "invoice_sent" and invoice is not None and invoice.kind in ("final", "service"):
        triggers.append("final_invoice_sent")
    out = []
    for rule in db.scalars(select(CrmRule).where(CrmRule.active.is_(True), CrmRule.trigger.in_(triggers))):
        if not _matches(rule, c, job) or _recently(db, rule, c, now):
            continue
        m = queue(db, rule, c, job, invoice)
        if m:
            out.append(m)
    return out


def monthly(db: Session, today: date | None = None) -> int:
    """From the 1st of the month: a check-in to every customer whose type a monthly rule covers and who had work last month."""
    today = today or datetime.now(TZ).date()
    first = today.replace(day=1)
    last_start = (first - timedelta(days=1)).replace(day=1)
    period = last_start.strftime("%Y-%m")
    lo = datetime.combine(last_start, time.min, tzinfo=TZ).astimezone(timezone.utc)
    hi = datetime.combine(first, time.min, tzinfo=TZ).astimezone(timezone.utc)
    worked = {e.job_id for e in db.scalars(select(TimeEntry).where(TimeEntry.start_at >= lo, TimeEntry.start_at < hi)) if e.job_id}
    jobs = [j for j in db.scalars(select(Job).where(Job.id.in_(worked)))] if worked else []
    n = 0
    for rule in db.scalars(select(CrmRule).where(CrmRule.active.is_(True), CrmRule.trigger == "monthly")):
        done = set()
        for j in jobs:
            c = db.get(Customer, j.customer_id) if j.customer_id else None
            if c is None or c.no_marketing or c.id in done or not _matches(rule, c, j):
                continue
            done.add(c.id)
            if db.scalar(select(Feedback.id).where(Feedback.customer_id == c.id, Feedback.kind == "monthly", Feedback.period == period)):
                continue
            if queue(db, rule, c, j, kind="monthly", period=period, send_on=today):
                n += 1
    return n


def send_due(db: Session, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    sent = failed = 0
    for m in db.scalars(select(OutboundMessage).where(OutboundMessage.status == "queued", OutboundMessage.send_at <= now)):
        try:
            if m.channel == "sms":
                messaging.send_sms(m.to, f"{m.body}")
            else:
                messaging.send_email(m.to, m.subject, m.body)
            m.status, m.sent_at, m.error = "sent", now, ""
            if m.customer_id:
                db.add(CrmActivity(customer_id=m.customer_id, kind="email" if m.channel == "email" else "note",
                                   text=f"Sent: {m.subject or m.body[:80]}", job_id=m.job_id))
            sent += 1
        except messaging.NotConfigured as e:
            m.error = str(e)  # stays queued until email / SMS is set up
        except Exception as e:  # noqa: BLE001 - a bad address mustn't stop the rest
            m.status, m.error = "failed", str(e)[:500]
            failed += 1
    return {"sent": sent, "failed": failed}


# --- feedback answers ---
def answer(db: Session, fb: Feedback, score: int, ratings: dict, comment: str) -> dict:
    fb.score = max(0, min(10, int(score)))
    fb.ratings = {k: max(1, min(5, int(v))) for k, v in (ratings or {}).items() if k in RATINGS and v}
    fb.comment = (comment or "")[:4000]
    fb.responded_at = datetime.now(timezone.utc)
    c = db.get(Customer, fb.customer_id) if fb.customer_id else None
    job = db.get(Job, fb.job_id) if fb.job_id else None
    if c is not None:
        db.add(CrmActivity(customer_id=c.id, kind="note", job_id=fb.job_id,
                           text=f"Feedback: {fb.score}/10" + (f" – \"{fb.comment[:300]}\"" if fb.comment else "")))
    if fb.score <= 6 and c is not None:
        from .plant import notify

        db.add(CrmActivity(customer_id=c.id, kind="task", job_id=fb.job_id, due_date=date.today() + timedelta(days=2),
                           text=f"Call {fb.contact_name or c.name} about their {fb.score}/10 feedback"))
        for u in db.scalars(select(User).where(User.role == "admin", User.active.is_(True))):
            notify(db, u.id, "feedback", f"Low score {fb.score}/10 from {c.name}{' on ' + job.name if job else ''}. Give them a call.",
                   f"/customers/{c.id}", key=f"fb-{fb.id}-{u.id}")
    review = ""
    rule_wants_review = db.scalar(select(OutboundMessage.rule_id).where(OutboundMessage.feedback_id == fb.id))
    rule = db.get(CrmRule, rule_wants_review) if rule_wants_review else None
    if fb.score >= 9 and rule is not None and rule.ask_review:
        review = ops.settings(db).get("google_review_url") or ""
    return {"thanks": True, "review_url": review}


def nps_of(scores: list[int]) -> float | None:
    if not scores:
        return None
    pro = sum(1 for s in scores if s >= 9)
    det = sum(1 for s in scores if s <= 6)
    return round(100 * (pro - det) / len(scores), 1)


def nps_report(db: Session, months: int = 12, today: date | None = None) -> dict:
    today = today or date.today()
    start = (today.replace(day=1) - timedelta(days=31 * (months - 1))).replace(day=1)
    lo = datetime.combine(start, time.min, tzinfo=timezone.utc)
    all_fb = list(db.scalars(select(Feedback).where(Feedback.created_at >= lo)))
    answered = [f for f in all_fb if f.score is not None]
    customers = {c.id: c for c in db.scalars(select(Customer))}

    def block(items: list[Feedback], sent: list[Feedback]) -> dict:
        scores = [f.score for f in items]
        ratings = defaultdict(list)
        for f in items:
            for k, v in (f.ratings or {}).items():
                ratings[k].append(v)
        return {"responses": len(items), "sent": len(sent), "response_rate": round(100 * len(items) / len(sent), 1) if sent else None,
                "nps": nps_of(scores), "promoters": sum(1 for s in scores if s >= 9), "passives": sum(1 for s in scores if 7 <= s <= 8),
                "detractors": sum(1 for s in scores if s <= 6), "avg_score": round(sum(scores) / len(scores), 1) if scores else None,
                "ratings": {k: round(sum(v) / len(v), 2) for k, v in ratings.items()}}

    by_dept, by_type, by_cust, by_month = defaultdict(list), defaultdict(list), defaultdict(list), defaultdict(list)
    sent_dept, sent_type, sent_cust, sent_month = defaultdict(list), defaultdict(list), defaultdict(list), defaultdict(list)
    for f in all_fb:
        c = customers.get(f.customer_id)
        month = (f.period or f.created_at.strftime("%Y-%m"))
        for d, k in ((sent_dept, f.department or "other"), (sent_type, c.kind if c else "other"), (sent_cust, f.customer_id),
                     (sent_month, month)):
            d[k].append(f)
        if f.score is not None:
            for d, k in ((by_dept, f.department or "other"), (by_type, c.kind if c else "other"), (by_cust, f.customer_id),
                         (by_month, month)):
                d[k].append(f)
    monthly_dept = defaultdict(lambda: defaultdict(list))
    for f in answered:
        monthly_dept[(f.period or f.created_at.strftime("%Y-%m"))][f.department or "other"].append(f.score)
    return {
        "overall": block(answered, all_fb),
        "by_department": [{"key": k, "label": DEPARTMENTS.get(k, k.title()), **block(by_dept.get(k, []), v)} for k, v in sent_dept.items()],
        "by_client_type": [{"key": k, "label": CLIENT_TYPES.get(k, k), **block(by_type.get(k, []), v)} for k, v in sent_type.items()],
        "by_customer": sorted(({"customer_id": k, "name": customers[k].name if k in customers else "", "kind": customers[k].kind if k in customers else "",
                                **block(by_cust.get(k, []), v)} for k, v in sent_cust.items() if k), key=lambda r: (r["nps"] is None, r["nps"] or 0)),
        "by_month": [{"month": m, **block(by_month.get(m, []), sent_month[m]),
                      "departments": {d: nps_of(s) for d, s in monthly_dept.get(m, {}).items()}} for m in sorted(sent_month)],
        "recent": [{"id": f.id, "customer": customers[f.customer_id].name if f.customer_id in customers else "", "customer_id": f.customer_id,
                    "job_id": f.job_id, "score": f.score, "comment": f.comment, "department": f.department, "kind": f.kind, "period": f.period,
                    "at": f.responded_at.isoformat() if f.responded_at else None, "followed_up": f.followed_up}
                   for f in sorted(answered, key=lambda f: f.responded_at or f.created_at, reverse=True)[:50]],
    }


def customer_summary(db: Session, c: Customer) -> dict:
    fbs = list(db.scalars(select(Feedback).where(Feedback.customer_id == c.id).order_by(Feedback.created_at.desc())))
    acts = db.scalars(select(CrmActivity).where(CrmActivity.customer_id == c.id).order_by(CrmActivity.created_at.desc()).limit(100))
    users = {u.id: u.name or u.email for u in db.scalars(select(User))}
    invs = list(db.scalars(select(Invoice).where(Invoice.customer_id == c.id)))
    return {
        "nps": nps_of([f.score for f in fbs if f.score is not None]),
        "feedback": [{"id": f.id, "kind": f.kind, "period": f.period, "score": f.score, "ratings": f.ratings, "comment": f.comment,
                      "sent": f.created_at.isoformat(), "responded_at": f.responded_at.isoformat() if f.responded_at else None,
                      "job_id": f.job_id} for f in fbs[:50]],
        "activities": [{"id": a.id, "kind": a.kind, "text": a.text, "due_date": a.due_date.isoformat() if a.due_date else None, "done": a.done,
                        "user": users.get(a.user_id, ""), "at": a.created_at.isoformat(), "job_id": a.job_id} for a in acts],
        "invoiced_total": round(sum(i.amount for i in invs if i.status in ("sent", "paid")), 2),
        "owing": round(sum(i.amount - i.retention + (i.amount - i.retention) * i.gst_pct / 100 - (i.paid_amount or 0)
                           for i in invs if i.status == "sent"), 2),
        "messages": [{"id": m.id, "subject": m.subject, "channel": m.channel, "status": m.status, "send_at": m.send_at.isoformat(),
                      "error": m.error} for m in db.scalars(select(OutboundMessage).where(OutboundMessage.customer_id == c.id)
                                                            .order_by(OutboundMessage.send_at.desc()).limit(30))],
    }
