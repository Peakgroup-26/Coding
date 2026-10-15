"""Sales tracking: the three sectors, the lead -> quote -> job pipeline, and the sales dashboard.

Every job sits in one sector (residential, commercial, maintenance) and moves through:
  lead        an enquiry, maybe with no plans yet
  quoting     plans are in and it's being estimated
  quote_sent  the quote has gone back to the client (quote_sent_date)
  won / lost / withdrawn   the outcome (decided_date)

The stage is worked out from the job, so it can't drift from what's actually happened. Dates are
filled in when things happen (a lead dated the day it's entered, a quote dated when marked sent,
an outcome dated when recorded) and people can correct any of them.
"""
import statistics
from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import AppSetting, CivilBoqLine, DrawingFile, Job, User

SECTORS = {"residential": ("Residential", "RES"), "commercial": ("Commercial", "COM"), "maintenance": ("Maintenance", "MNT")}
STAGES = ["lead", "quoting", "quote_sent", "won", "lost", "withdrawn"]
STAGE_LABELS = {"lead": "Lead", "quoting": "Quoting", "quote_sent": "Quote sent", "won": "Won", "lost": "Lost", "withdrawn": "Withdrawn"}
DEFAULT_SOURCES = ["Builder (repeat)", "Builder (new)", "Website", "Referral", "Tender portal", "Phone / walk-in", "Real estate / strata", "Other"]
DEFAULT_WORK_TYPES = {
    "residential": ["New house", "Duplex / townhouses", "Renovation / extension", "Bathroom / kitchen", "Pool / landscaping", "Other"],
    "commercial": ["Apartments / units", "Retail / shopping centre", "Office", "Childcare / school", "Medical / aged care",
                   "Industrial / warehouse", "Hospitality", "Fit-out", "Other"],
    "maintenance": ["Blocked drain", "Leak / burst pipe", "Hot water", "Gas", "Fixtures / tapware", "Backflow / testing",
                    "Roof / stormwater", "Scheduled service", "Other"],
}
DEFAULT_LOST_REASONS = ["Price too high", "Went with another plumber", "Builder lost the job", "Project didn't go ahead",
                        "Timing / couldn't start in time", "No response", "Scope or spec mismatch", "Other"]
# Rough job size: (key, label). Picked when the lead comes in; the real price goes in when the quote is sent.
VALUE_BANDS = [("<5k", "Under $5k"), ("5k-20k", "$5k – $20k"), ("20k-50k", "$20k – $50k"), ("50k-150k", "$50k – $150k"),
               ("150k-500k", "$150k – $500k"), ("500k-1m", "$500k – $1M"), ("1m+", "Over $1M"), ("unknown", "Not sure")]
BAND_LABELS = dict(VALUE_BANDS)


def stage(db: Session, job: Job) -> str:
    if job.tender_result in ("won", "lost", "withdrawn"):
        return job.tender_result
    if job.quote_sent_date:
        return "quote_sent"
    has_work = job.autopilot is not None or db.scalar(select(DrawingFile.id).where(DrawingFile.job_id == job.id).limit(1)) is not None \
        or db.scalar(select(CivilBoqLine.id).where(CivilBoqLine.job_id == job.id).limit(1)) is not None
    return "quoting" if has_work else "lead"


def lead_date(job: Job) -> date | None:
    return job.lead_date or (job.created_at.date() if job.created_at else None)


def next_quote_no(db: Session, sector: str) -> str:
    """RES-2026-0007: per sector, per year."""
    prefix = f"{SECTORS.get(sector, SECTORS['commercial'])[1]}-{date.today().year}-"
    taken = db.scalars(select(Job.quote_no).where(Job.quote_no.like(prefix + "%")))
    n = max([int(q[len(prefix):]) for q in taken if q[len(prefix):].isdigit()], default=0) + 1
    return f"{prefix}{n:04d}"


def prepare_new(db: Session, job: Job) -> None:
    """Fill in what a new job needs for tracking."""
    if job.sector not in SECTORS:
        job.sector = "commercial"
    if not job.lead_date:
        job.lead_date = date.today()
    if not job.quote_no:
        job.quote_no = next_quote_no(db, job.sector)


def _stored(db: Session) -> dict:
    s = db.get(AppSetting, "sales")
    return (s.value or {}) if s else {}


def sources(db: Session) -> list[str]:
    return list(_stored(db).get("lead_sources") or DEFAULT_SOURCES)


def lost_reasons(db: Session) -> list[str]:
    return list(_stored(db).get("lost_reasons") or DEFAULT_LOST_REASONS)


def work_types(db: Session) -> dict[str, list[str]]:
    saved = _stored(db).get("work_types") or {}
    return {k: list(saved.get(k) or v) for k, v in DEFAULT_WORK_TYPES.items()}


def clients(jobs: list[Job]) -> list[dict]:
    """Clients already on jobs, busiest first, each with the contacts used for them: the drop-down for a new lead."""
    by: dict[str, dict] = {}
    for j in jobs:
        name = (j.client or "").strip()
        if not name:
            continue
        c = by.setdefault(name.lower(), {"name": name, "jobs": 0, "contacts": [], "sectors": set()})
        c["jobs"] += 1
        c["sectors"].add(j.sector)
        if j.contact and j.contact not in c["contacts"]:
            c["contacts"].append(j.contact)
    return [{**c, "sectors": sorted(c["sectors"])} for c in sorted(by.values(), key=lambda c: (-c["jobs"], c["name"].lower()))]


def _days(a: date | None, b: date | None) -> int | None:
    return (b - a).days if a and b and b >= a else None


def _stats(values: list[int]) -> dict:
    v = [x for x in values if x is not None]
    if not v:
        return {"count": 0, "average": None, "median": None}
    return {"count": len(v), "average": round(sum(v) / len(v), 1), "median": statistics.median(v)}


def _pct(a: int, b: int) -> float | None:
    return round(100 * a / b, 1) if b else None


def dashboard(db: Session, jobs: list[Job], months: int = 12, today: date | None = None) -> dict:
    """Leads, conversion, time to convert, value, sources, estimators, trend and follow-ups.

    Conversion is by cohort: of the leads that came in during the period, how many had a quote sent
    and how many were won (so a lead from last week that's still being quoted counts as not yet).
    The win rate of decided quotes is shown separately.
    """
    today = today or date.today()
    start = date(today.year, today.month, 1)
    for _ in range(months - 1):
        start = (start - timedelta(days=1)).replace(day=1)
    stages = {j.id: stage(db, j) for j in jobs}
    names = {u.id: (u.name or u.email) for u in db.scalars(select(User))}
    cohort = [j for j in jobs if (lead_date(j) or today) >= start]

    quoted = [j for j in cohort if j.quote_sent_date]
    won = [j for j in cohort if j.tender_result == "won"]
    decided = [j for j in jobs if j.tender_result in ("won", "lost") and j.decided_date and j.decided_date >= start]
    decided_won = [j for j in decided if j.tender_result == "won"]

    lead_to_quote = [_days(lead_date(j), j.quote_sent_date) for j in quoted]
    quote_to_win = [_days(j.quote_sent_date, j.decided_date) for j in won]
    lead_to_win = [_days(lead_date(j), j.decided_date) for j in won]
    quote_to_loss = [_days(j.quote_sent_date, j.decided_date) for j in cohort if j.tender_result == "lost"]

    def group(key) -> list[dict]:
        g: dict[str, dict] = defaultdict(lambda: {"leads": 0, "quoted": 0, "won": 0, "lost": 0, "won_value": 0.0, "quoted_value": 0.0,
                                                  "_l2q": []})
        for j in cohort:
            r = g[key(j) or "(not set)"]
            r["leads"] += 1
            if j.quote_sent_date:
                r["quoted"] += 1
                r["quoted_value"] += j.tender_value or 0.0
                r["_l2q"].append(_days(lead_date(j), j.quote_sent_date))
            if j.tender_result == "won":
                r["won"] += 1
                r["won_value"] += j.tender_value or 0.0
            if j.tender_result == "lost":
                r["lost"] += 1
        out = []
        for k, r in g.items():
            l2q = _stats(r.pop("_l2q"))
            out.append({"name": k, **r, "quote_rate_pct": _pct(r["quoted"], r["leads"]), "win_rate_pct": _pct(r["won"], r["won"] + r["lost"]),
                        "lead_to_quote_days": l2q["average"]})
        return sorted(out, key=lambda x: -x["leads"])

    months_out: dict[str, dict] = {}
    m = start
    while m <= today:
        months_out[m.strftime("%Y-%m")] = {"month": m.strftime("%Y-%m"), "leads": 0, "quotes_sent": 0, "won": 0, "lost": 0, "won_value": 0.0}
        m = (m + timedelta(days=32)).replace(day=1)
    for j in jobs:
        for when, field in ((lead_date(j), "leads"), (j.quote_sent_date, "quotes_sent")):
            if when and when.strftime("%Y-%m") in months_out:
                months_out[when.strftime("%Y-%m")][field] += 1
        if j.decided_date and j.tender_result in ("won", "lost") and j.decided_date.strftime("%Y-%m") in months_out:
            months_out[j.decided_date.strftime("%Y-%m")][j.tender_result] += 1
            if j.tender_result == "won":
                months_out[j.decided_date.strftime("%Y-%m")]["won_value"] += j.tender_value or 0.0

    def brief(j: Job, age_from: date | None) -> dict:
        return {"job_id": j.id, "name": j.name, "quote_no": j.quote_no, "sector": j.sector, "client": j.client, "value": j.tender_value,
                "stage": stages[j.id], "days": _days(age_from, today), "due_date": j.due_date.isoformat() if j.due_date else None,
                "estimator": names.get(j.created_by, ""), "contact": j.contact}

    open_quotes = sorted((brief(j, j.quote_sent_date) for j in jobs if stages[j.id] == "quote_sent"), key=lambda x: -(x["days"] or 0))
    to_quote = sorted((brief(j, lead_date(j)) for j in jobs if stages[j.id] in ("lead", "quoting")),
                      key=lambda x: (x["due_date"] or "9999", -(x["days"] or 0)))
    for t in to_quote:
        t["overdue"] = bool(t["due_date"] and t["due_date"] < today.isoformat())

    pipeline = defaultdict(lambda: {"count": 0, "value": 0.0})
    for j in jobs:
        pipeline[stages[j.id]]["count"] += 1
        pipeline[stages[j.id]]["value"] += j.tender_value or 0.0

    return {
        "period": {"from": start.isoformat(), "to": today.isoformat(), "months": months},
        "leads": len(cohort), "quotes_sent": len(quoted), "won": len(won),
        "lost": sum(1 for j in cohort if j.tender_result == "lost"),
        "conversion": {"lead_to_quote_pct": _pct(len(quoted), len(cohort)), "quote_to_win_pct": _pct(len(won), len(quoted)),
                       "lead_to_win_pct": _pct(len(won), len(cohort)), "win_rate_decided_pct": _pct(len(decided_won), len(decided))},
        "days": {"lead_to_quote": _stats(lead_to_quote), "quote_to_win": _stats(quote_to_win), "lead_to_win": _stats(lead_to_win),
                 "quote_to_loss": _stats(quote_to_loss)},
        "value": {"quoted": round(sum(j.tender_value or 0 for j in quoted), 2), "won": round(sum(j.tender_value or 0 for j in won), 2),
                  "average_won": round(sum(j.tender_value or 0 for j in won) / len(won), 2) if won else None,
                  "open_quotes": round(sum(x["value"] or 0 for x in open_quotes), 2)},
        "pipeline": {s: pipeline[s] for s in STAGES},
        "by_source": group(lambda j: j.lead_source),
        "by_estimator": group(lambda j: names.get(j.created_by, "")),
        "by_sector": group(lambda j: SECTORS.get(j.sector, ("",))[0]),
        "by_work_type": group(lambda j: j.work_type),
        "by_size": sorted(group(lambda j: BAND_LABELS.get(j.value_band, "")),
                          key=lambda g: [lbl for _, lbl in VALUE_BANDS].index(g["name"]) if g["name"] in BAND_LABELS.values() else 99),
        "by_client": group(lambda j: (j.client or "").strip())[:15],
        "lost_reasons": _reasons([j for j in jobs if j.tender_result in ("lost", "withdrawn") and j.decided_date and j.decided_date >= start]),
        "monthly": list(months_out.values()),
        "open_quotes": open_quotes[:50],
        "to_quote": to_quote[:50],
    }


def _reasons(lost: list[Job]) -> list[dict]:
    counts: dict[str, list[Job]] = defaultdict(list)
    for j in lost:
        counts[j.outcome_reason or "(not given)"].append(j)
    return sorted(({"reason": k, "count": len(v), "value": round(sum(j.tender_value or 0 for j in v), 2),
                    "pct": _pct(len(v), len(lost))} for k, v in counts.items()), key=lambda x: -x["count"])


def count_by_sector(db: Session, jobs: list[Job]) -> dict:
    out = {s: 0 for s in SECTORS}
    for j in jobs:
        out[j.sector if j.sector in out else "commercial"] += 1
    return out
