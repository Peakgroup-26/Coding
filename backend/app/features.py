"""Per-person access to each tab and feature: Hidden, View only, or Can change.

Every feature lists the API paths behind it. `access.enforce` finds the feature for each request (first match wins):
a GET needs at least "view", anything else needs "edit". A person's level for a feature is, in order: what's set on the
person, what their position (preset) says, else "edit" (so nothing changes until an admin restricts it). Admins always
have everything. The older permissions (Finance, People, plumbing / civil jobs, sectors...) still apply on top.

Paths no feature claims (signing in, settings, notifications, the staff list, the team directory, a job's header) stay
open to anyone signed in, because many pages need them.
"""
import re

from sqlalchemy.orm import Session

LEVELS = ("none", "view", "edit")

# (key, group, label, front-end routes, API path patterns)
FEATURES: list[tuple[str, str, str, list[str], list[str]]] = [
    # Work
    ("my_work", "Work", "My work", ["/my-work"], [r"^/api/my-work"]),
    ("boards", "Work", "Boards (tasks, programmes, safety, forms)", ["/boards"], [r"^/api/boards"]),
    ("director", "Work", "Director's dashboard (team and client NPS)", ["/director"], [r"^/api/director\b"]),
    ("assistant", "Work", "Ask Lorojo and the AI chat", [], [r"^/api/assistant", r"^/api/jobs/\d+/chat", r"^/api/memories"]),
    # Estimating
    ("tenders", "Estimating", "Tenders & quotes: drawings, take-off, fittings, pricing, check-measure",
     ["/", "/jobs"], [r"^/api/jobs/\d+/(add-plans|ai-read|ai-stats|allowances|approve-all|audit|autopilot|checks|counts|documents|export\.xlsx|files|"
                      r"finalise|fittings-summary|flags|generate|generated|golden-report|levels|markup\.pdf|pricing|pricing-settings|reference|"
                      r"reopen|requirements|runs|sheets|simpro\.csv|stage-matrix|totals|dimensions)\b",
                      r"^/api/(sheets|runs|counts|levels|viewports|generated|flags|allowances|requirements|documents|ai|quick-start)\b",
                      r"^/api/jobs$"]),
    ("civil", "Estimating", "Civil BOQ", [], [r"^/api/jobs/\d+/civil\b", r"^/api/civil/lines"]),
    ("workbook", "Estimating", "Estimating workbook, subbie quotes, versions, tender cash flow", [],
     [r"^/api/jobs/\d+/(workbook|packages|versions|programme)\b", r"^/api/(workbook|packages|package-quotes|estimate-versions)\b"]),
    ("rate_library", "Estimating", "Rate library (resources and build-ups)", ["/rate-library"], [r"^/api/(resources|rate-buildups)\b"]),
    ("sales", "Estimating", "Sales dashboard and leads", ["/sales"], [r"^/api/sales/dashboard", r"^/api/leads\b", r"^/api/jobs/\d+/(sales|tender-result)\b"]),
    ("civil_rates", "Estimating", "Civil rates library", ["/civil-rates"], [r"^/api/civil/(rate-sets|rates)"]),
    ("price_books", "Estimating", "Price books, catalogue, benchmarks, productivity", ["/price-books"],
     [r"^/api/(price-books|catalogue|benchmarks|productivity)"]),
    ("rules", "Estimating", "Fitting rules", ["/rules"], [r"^/api/rules\b"]),
    ("mappings", "Estimating", "Price mappings", ["/mappings"], [r"^/api/mappings\b"]),
    ("reports", "Estimating", "Job reports and the reports dashboard", ["/reports"],
     [r"^/api/reports\b", r"^/api/jobs/\d+/(reports|reports\.xlsx|program)\b"]),
    # Operations
    ("live_jobs", "Operations", "Live jobs: job hub, budgets, RFIs, diary, forms, job documents", ["/work"],
     [r"^/api/work\b", r"^/api/jobs/\d+/(work|start-work|budget|items|diary|forms|docs|time)\b", r"^/api/(items|budget)\b"]),
    ("schedule", "Operations", "Schedule", ["/schedule"], [r"^/api/schedule\b"]),
    ("timesheets", "Operations", "Timesheets and leave approval", ["/timesheets"], [r"^/api/timesheets\b", r"^/api/time-off\b"]),
    ("purchasing", "Operations", "Purchasing: POs, bills, costs, variations, stock", ["/purchasing"],
     [r"^/api/(purchase-orders|costs|variations|stock)\b", r"^/api/jobs/\d+/(costs|variations|materials)\b", r"^/api/suppliers\b"]),
    ("plant", "Operations", "Plant and vehicles", ["/plant"], [r"^/api/plant"]),
    ("maintenance", "Operations", "Maintenance planner (assets)", ["/maintenance"], [r"^/api/(assets|maintenance)\b"]),
    ("documents", "Operations", "Company documents and forms", ["/documents"], [r"^/api/(files|form-templates|forms)\b"]),
    ("tools", "Operations", "Tools register (add tools, assign, test and tag)", ["/tools"], [r"^/api/tools\b"]),
    ("vehicles_map", "Operations", "Vehicle map (Geotab)", ["/vehicles"], [r"^/api/vehicles\b"]),
    # Safety
    ("safety", "Safety", "Safety: dashboard, SWMS, incidents and hazards, actions, toolbox talks, site pre-starts", ["/safety"],
     [r"^/api/safety\b", r"^/api/jobs/\d+/(swms|prestarts)\b", r"^/api/job-swms\b"]),
    ("itp", "Safety", "ITPs (inspection and test plans) on jobs", [], [r"^/api/jobs/\d+/itps\b", r"^/api/(job-itps|itp-templates)\b"]),
    # Customers
    ("customers", "Customers", "Customers and sites", ["/customers"], [r"^/api/(customers|sites)\b"]),
    ("crm", "Customers", "Feedback and follow-ups (CRM, NPS)", ["/crm"], [r"^/api/crm\b"]),
    # Money
    ("finance", "Money", "Finance dashboard, WIP, cash flow, budgets", ["/finance"], [r"^/api/(finance|budget-months)\b"]),
    ("invoices", "Money", "Invoices and debtors", [], [r"^/api/invoices\b"]),
    ("supplier_prices", "Money", "Supplier price files and cheapest-supplier report", [], [r"^/api/supplier-prices\b"]),
    ("xero", "Money", "Xero connection", [], [r"^/api/integrations\b"]),
    # People
    ("hr_licences", "People", "Licences, tickets and training", [], [r"^/api/people/(credentials|credential-types)\b", r"^/api/people/\d+/credentials"]),
    ("hr_leave", "People", "Leave balances and corrections", [], [r"^/api/people/(leave|leave-adjustments|leave-policies)\b", r"^/api/people/\d+/leave"]),
    ("hr_hiring", "People", "Hiring (job openings and candidates)", [], [r"^/api/people/(openings|candidates)\b"]),
    ("hr_reviews", "People", "Reviews and goals", [], [r"^/api/people/(reviews|goals)\b", r"^/api/people/\d+/goals"]),
    ("hr_surveys", "People", "Staff surveys and eNPS", [], [r"^/api/people/surveys\b"]),
    ("hr_policies", "People", "Policies to sign", [], [r"^/api/people/policies\b"]),
    ("hr_news", "People", "News to the team", [], [r"^/api/people/announcements\b"]),
    ("hr_pay", "People", "Pay history and pay rates", [], [r"^/api/people/\d+/pay", r"^/api/people/pay\b"]),
    ("hr_records", "People", "Staff records, onboarding, files, gear and HR reports", ["/people"], [r"^/api/people\b"]),
    # Phone app
    ("field_clock", "Phone app", "Clock in and out, breaks", [], [r"^/api/field/(clock-in|clock-out|break)\b"]),
    ("field_jobs", "Phone app", "Jobs: photos, plans, materials, notes, POs, forms", ["/field/jobs"],
     [r"^/api/field/(jobs|products|suppliers|forms|documents|upload)\b"]),
    ("field_schedule", "Phone app", "My schedule", ["/field/schedule"], [r"^/api/field/schedule\b"]),
    ("field_prestart", "Phone app", "Pre-starts, defects and washes", ["/field/prestart"], [r"^/api/field/plant\b"]),
    ("field_timesheet", "Phone app", "My timesheet and leave requests", ["/field/timesheet"], [r"^/api/field/(timesheet|time-off)\b"]),
    ("field_crew", "Phone app", "Clock a crew on (supervisors)", ["/field/crew"], [r"^/api/field/crew\b"]),
    ("field_me", "Phone app", "Me: my leave, licences, details, policies, reviews, surveys", ["/field/me"],
     [r"^/api/field/me(?!/(directory|photo|new-password))\b"]),
    ("field_work", "Phone app", "Board tasks on the phone", ["/field/work"], [r"^/api/field/my-work\b"]),
    ("field_tools", "Phone app", "Tools: who has what, ask for it, hand it over", ["/field/tools"], [r"^/api/field/(tools|tool-moves)\b"]),
    ("field_safety", "Phone app", "Safety: SWMS sign-on, site pre-starts, ITP checks, hazard reports", ["/field/safety"], [r"^/api/field/safety\b"]),
    # Admin-ish
    ("settings_ops", "Admin", "Operations settings (rates, margins, overtime, HR settings)", [], [r"^/api/ops-settings\b"]),
]
KEYS = [f[0] for f in FEATURES]
_RULES = [(re.compile(p), f[0]) for f in FEATURES for p in f[4]]

ALL = {k: "edit" for k in KEYS}
OFFICE_KEYS = [k for k in KEYS if not k.startswith("field_")]
FIELD_KEYS = [k for k in KEYS if k.startswith("field_")]


def _preset(base: str, **levels: str) -> dict[str, str]:
    out = {k: base for k in KEYS}
    for k, v in levels.items():
        out[k] = v
    return out


def _group(level: str, *groups: str) -> dict[str, str]:
    return {f[0]: level for f in FEATURES if f[1] in groups}


# Starting points; an admin edits them on the Permissions page.
POSITIONS: list[tuple[str, str, dict[str, str]]] = [
    ("Director", "Everything", dict(ALL)),
    ("Office manager", "Runs the office: everything but Xero set-up", _preset("edit", xero="view")),
    ("Estimator", "Tenders, pricing and sales; sees live jobs", {**_preset("none"), **_group("edit", "Estimating", "Work"),
     "live_jobs": "view", "schedule": "view", "customers": "view", "purchasing": "view", "supplier_prices": "view", "documents": "view",
     **{k: "edit" for k in FIELD_KEYS}, "field_crew": "none"}),
    ("Project manager", "Runs live jobs; sees estimates and job money", {**_preset("none"), **_group("edit", "Operations", "Customers", "Work", "Safety"),
     "tenders": "view", "workbook": "view", "civil": "view", "reports": "edit", "rate_library": "view", "finance": "view",
     "invoices": "view", "supplier_prices": "view", "hr_licences": "view", "hr_leave": "view", **{k: "edit" for k in FIELD_KEYS}}),
    ("Supervisor", "On site: jobs, schedule, timesheets, plant, crew", {**_preset("none"), "my_work": "edit", "boards": "edit", "assistant": "edit",
     "tools": "edit", "vehicles_map": "view", "safety": "edit", "itp": "edit",
     "live_jobs": "edit", "schedule": "edit", "timesheets": "edit", "purchasing": "edit", "plant": "edit", "maintenance": "edit",
     "documents": "edit", "customers": "view", "hr_licences": "view", **{k: "edit" for k in FIELD_KEYS}}),
    ("Accounts", "Money, invoices, purchasing and timesheets", {**_preset("none"), **_group("edit", "Money"), "my_work": "edit", "boards": "edit",
     "assistant": "edit", "purchasing": "edit", "timesheets": "edit", "live_jobs": "view", "customers": "edit", "crm": "view",
     "hr_leave": "view", "hr_pay": "view", "field_me": "edit", "field_timesheet": "edit"}),
    ("Plumber", "Phone app: clock in, jobs, pre-starts, timesheet, Me", {**_preset("none"), **{k: "edit" for k in FIELD_KEYS}, "field_crew": "none",
     "assistant": "edit"}),
    ("Apprentice", "Phone app, without crew or POs", {**_preset("none"), **{k: "edit" for k in FIELD_KEYS}, "field_crew": "none"}),
    ("Labourer / operator", "Phone app: clock in, pre-starts, timesheet, Me", {**_preset("none"), **{k: "edit" for k in FIELD_KEYS},
     "field_crew": "none", "field_jobs": "view"}),
]

for _name, _d, _feats in POSITIONS:  # the director's dashboard is for the director and the office manager
    if _name not in ("Director", "Office manager"):
        _feats["director"] = "none"


def feature_for(path: str) -> str | None:
    for rx, key in _RULES:
        if rx.search(path):
            return key
    return None


def level(db: Session, user, key: str) -> str:
    if user is None or user.role == "admin":
        return "edit"
    own = (user.features or {}).get(key)
    if own in LEVELS:
        return own
    if user.position_id:
        from .models import Position

        p = db.get(Position, user.position_id)
        lv = (p.features or {}).get(key) if p else None
        if lv in LEVELS:
            return lv
    return "edit"


def effective(db: Session, user) -> dict[str, str]:
    if user is None:
        return {}
    if user.role == "admin":
        return dict(ALL)
    pos = {}
    if user.position_id:
        from .models import Position

        p = db.get(Position, user.position_id)
        pos = (p.features or {}) if p else {}
    own = user.features or {}
    return {k: own.get(k) if own.get(k) in LEVELS else pos.get(k) if pos.get(k) in LEVELS else "edit" for k in KEYS}


def catalogue() -> list[dict]:
    return [{"key": k, "group": g, "label": label, "routes": routes} for k, g, label, routes, _ in FEATURES]


def seed(db: Session) -> None:
    from sqlalchemy import select

    from .models import Position

    if db.scalar(select(Position.id).limit(1)):
        # Features added since the positions were made: take them from the preset of the same name, else hidden
        presets = {name: feats for name, _d, feats in POSITIONS}
        for p in db.scalars(select(Position)):
            have = dict(p.features or {})
            missing = [k for k in KEYS if k not in have]
            if missing:
                for k in missing:
                    have[k] = presets.get(p.name, {}).get(k, "none")
                p.features = have
        db.flush()
        return
    for i, (name, desc, feats) in enumerate(POSITIONS):
        db.add(Position(name=name, description=desc, features=feats, position=i))
    db.flush()


def clean(features: dict | None) -> dict[str, str]:
    """Only known features and levels; anything else is dropped."""
    return {k: v for k, v in (features or {}).items() if k in KEYS and v in LEVELS}
