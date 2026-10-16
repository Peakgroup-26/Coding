"""Ask Peak: the company-wide assistant. Anyone can type or talk to it from any page and it answers from the
live records, making custom reports (tables, with a chart when it helps) that can be downloaded.

It only reads. It sees what the person asking can see: jobs by their permissions, and money (costs, WIP,
cash flow, invoices) only with the finance permission. Each person has their own conversation; "New
conversation" starts a fresh one. The conversation is kept the same way as the job chat (see chat.py).
"""
import json
import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Callable

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from . import chat, crm, finance, ops, purchasing, sales, supplier_prices
from . import timesheets as ts
from .access import can_see_job, has
from .ai import AIUnavailable
from .models import BudgetLine, ChatMessage, ChatSession, Customer, Invoice, Job, PurchaseOrder, TimeEntry, User

log = logging.getLogger(__name__)

SYSTEM = """You are Ask Lorojo, the assistant for everyone at Peak Plumbing & Gas Services (Sunshine Coast, Queensland): \
plumbing, gas, maintenance, commercial hydraulics and civil. You answer questions from the company's live records \
using your tools, and build reports on request.

How to work:
- Look things up with the tools; never guess or invent a number. If the records don't hold something, say so.
- Find jobs by name with find_jobs first (people say "the Maroochydore apartments job"); if several match, pick the \
obvious one or ask.
- When the answer is a set of figures, call show_report with a clear title, the columns and rows, and a one-line \
summary, plus a chart when a comparison or trend is easier to see. Then answer in two or three plain sentences \
that give the headline (the report sits under your answer, and can be downloaded).
- "Estimated" or "budget" hours are the job's budget (from the estimate, plus approved variations); "actual" \
hours are clocked time. Say which jobs have no budget when that matters.
- Money is ex GST unless you say otherwise. Australian English, dates as 15/10/2026.
- The person may be listening rather than reading: keep spoken answers short.
- You can only read. If asked to change something, say where in the app to do it.

Today is {today}. You're talking to {name} ({role}{finance}).
"""

MAX_STEPS = 14


class ToolError(Exception):
    pass


@dataclass
class Ctx:
    db: Session
    user: User
    reports: list


@dataclass
class Tool:
    name: str
    description: str
    properties: dict
    required: list
    fn: Callable
    money: bool = False

    def schema(self):
        return {"name": self.name, "description": self.description,
                "input_schema": {"type": "object", "properties": self.properties, "required": self.required, "additionalProperties": False}}


TOOLS: dict[str, Tool] = {}


def tool(name, description, properties=None, required=None, money=False):
    def wrap(fn):
        TOOLS[name] = Tool(name, description, properties or {}, required or [], fn, money)
        return fn
    return wrap


def _jobs(ctx: Ctx, live_only=False) -> list[Job]:
    stmt = select(Job)
    if live_only:
        stmt = stmt.where(Job.work_status != "")
    return [j for j in ctx.db.scalars(stmt) if can_see_job(ctx.user, j)]


def _job(ctx: Ctx, job_id: int) -> Job:
    j = ctx.db.get(Job, job_id)
    if j is None or not can_see_job(ctx.user, j):
        raise ToolError(f"No job {job_id} that you can see")
    return j


def _d(s: str | None, default: date | None = None) -> date | None:
    if not s:
        return default
    try:
        return date.fromisoformat(s)
    except ValueError:
        raise ToolError(f"Dates are YYYY-MM-DD, not {s!r}")


# --- tools ---
@tool("find_jobs", "Find jobs (quotes and live jobs) by words in the name, job number, quote number, client or address.",
      {"query": {"type": "string"}, "live_only": {"type": "boolean", "description": "Only jobs that are underway or done, not quotes"}},
      ["query"])
def find_jobs(ctx: Ctx, query: str, live_only: bool = False):
    words = [w for w in query.lower().replace("–", " ").split() if len(w) > 1]
    rows = []
    for j in _jobs(ctx, live_only):
        hay = f"{j.name} {j.job_no} {j.quote_no} {j.client} {j.address}".lower()
        score = sum(1 for w in words if w in hay or (w.endswith("s") and w[:-1] in hay))
        if score:
            rows.append((score, j))
    rows.sort(key=lambda x: (-x[0], -x[1].id))
    return [{"job_id": j.id, "job_no": j.job_no, "quote_no": j.quote_no, "name": j.name, "client": j.client, "sector": j.sector,
             "kind": j.kind, "work_status": j.work_status or "quote", "sales_stage": j.sales_stage} for _, j in rows[:15]]


@tool("job_overview", "One job's details and, for live jobs, its money: contract, variations, budget vs actual by category, "
      "% complete, forecast margin, invoiced, labour hours budget vs actual.", {"job_id": {"type": "integer"}}, ["job_id"])
def job_overview(ctx: Ctx, job_id: int):
    j = _job(ctx, job_id)
    out = {"job_id": j.id, "job_no": j.job_no, "quote_no": j.quote_no, "name": j.name, "client": j.client, "status": j.work_status or "quote",
           "sales_stage": j.sales_stage, "tender_value": j.tender_value, "start": str(j.start_date or ""), "finish": str(j.finish_date or "")}
    if j.work_status:
        f = finance.job_financials(ctx.db, j)
        if not has(ctx.user, "can_finance"):
            f = {k: f[k] for k in ("percent_complete", "hours_budget", "hours_actual")}
        out["financials"] = f
    return out


@tool("labour_hours", "Labour hours on a job: the budget (estimated) hours by stage and the actual clocked hours, grouped by "
      "person, task / stage, week or day, with cost when allowed.",
      {"job_id": {"type": "integer"}, "group_by": {"type": "string", "enum": ["person", "task", "week", "day"]},
       "start": {"type": "string", "description": "YYYY-MM-DD, optional"}, "end": {"type": "string", "description": "YYYY-MM-DD, optional"}},
      ["job_id"])
def labour_hours(ctx: Ctx, job_id: int, group_by: str = "person", start: str = "", end: str = ""):
    j = _job(ctx, job_id)
    s, e = _d(start), _d(end)
    budget = defaultdict(float)
    for b in ctx.db.scalars(select(BudgetLine).where(BudgetLine.job_id == j.id, BudgetLine.category == "labour")):
        budget[b.stage or b.description] += b.hours
    if not budget and not j.work_status:
        from .reports import labour

        est = labour(ctx.db, j)
        for r in est["by_stage"]:
            budget[r["stage"]] += r["hours"]
    rates = finance._rates(ctx.db)
    names = {u.id: u.name or u.email for u in ctx.db.scalars(select(User))}
    groups = defaultdict(lambda: {"hours": 0.0, "cost": 0.0, "entries": 0})
    total = 0.0
    for t in ctx.db.scalars(select(TimeEntry).where(TimeEntry.job_id == j.id, TimeEntry.status != "rejected")):
        day = ts.local_day(t.start_at)
        if (s and day < s) or (e and day > e):
            continue
        h = finance.entry_hours(t)
        key = {"person": names.get(t.user_id, "?"), "task": t.task or "(no task)", "week": ts.week_start(day).isoformat(),
               "day": day.isoformat()}[group_by]
        groups[key]["hours"] += h
        groups[key]["cost"] += finance.entry_cost(ctx.db, t, rates)
        groups[key]["entries"] += 1
        total += h
    show_cost = has(ctx.user, "can_finance")
    return {"job": f"{j.job_no or j.quote_no} {j.name}", "budget_hours_total": round(sum(budget.values()), 1),
            "budget_hours_by_stage": {k: round(v, 1) for k, v in budget.items()}, "actual_hours_total": round(total, 1),
            "variance_hours": round(sum(budget.values()) - total, 1),
            "actual_by_" + group_by: [{"key": k, "hours": round(v["hours"], 2), **({"cost": round(v["cost"], 2)} if show_cost else {}),
                                       "entries": v["entries"]} for k, v in sorted(groups.items())]}


@tool("wip_report", "Work in progress for every live job: revenue, cost to date, committed, forecast cost, margin, % complete, earned, "
      "invoiced, over/under billed.", {"sector": {"type": "string", "description": "residential | commercial | maintenance | civil, or empty"}},
      money=True)
def wip_report(ctx: Ctx, sector: str = ""):
    jobs = [j for j in _jobs(ctx, True) if j.work_status in ops.ACTIVE and (not sector or j.sector == sector or (sector == "civil" and j.kind == "civil"))]
    return finance.wip(ctx.db, jobs)


@tool("month_to_date", "This month so far against the forecast pro-rated to today: revenue, labour, materials, subcontractors, with "
      "the jobs driving the costs.", money=True)
def month_to_date(ctx: Ctx):
    return finance.month_to_date(ctx.db, _jobs(ctx, True))


@tool("cash_flow", "Cash flow forecast by week: money in (invoices due, work still to bill) and out (wages, suppliers, overheads), "
      "running bank balance.", {"weeks": {"type": "integer"}}, money=True)
def cash_flow(ctx: Ctx, weeks: int = 13):
    return finance.cashflow(ctx.db, _jobs(ctx, True), max(4, min(weeks, 52)))


@tool("timesheet_hours", "Clocked hours between two dates, grouped by person, job or day, optionally for one person or one job. "
      "Includes ordinary / overtime by person.",
      {"start": {"type": "string"}, "end": {"type": "string"}, "group_by": {"type": "string", "enum": ["person", "job", "day"]},
       "person": {"type": "string", "description": "part of a name, optional"}, "job_id": {"type": "integer"}}, ["start", "end"])
def timesheet_hours(ctx: Ctx, start: str, end: str, group_by: str = "person", person: str = "", job_id: int = 0):
    s, e = _d(start), _d(end)
    lo, _ = ts.day_bounds(s)
    hi, _ = ts.day_bounds(e + timedelta(days=1))
    users = {u.id: u for u in ctx.db.scalars(select(User))}
    jobs = {j.id: j for j in _jobs(ctx)}
    groups = defaultdict(float)
    for t in ctx.db.scalars(select(TimeEntry).where(TimeEntry.start_at >= lo, TimeEntry.start_at < hi, TimeEntry.status != "rejected")):
        u = users.get(t.user_id)
        if person and (u is None or person.lower() not in (u.name or u.email).lower()):
            continue
        if job_id and t.job_id != job_id:
            continue
        if t.job_id and t.job_id not in jobs:
            continue
        j = jobs.get(t.job_id)
        key = {"person": (u.name or u.email) if u else "?", "job": f"{j.job_no} {j.name}" if j else "(no job)",
               "day": ts.local_day(t.start_at).isoformat()}[group_by]
        groups[key] += finance.entry_hours(t)
    return {"from": start, "to": end, "total_hours": round(sum(groups.values()), 1),
            "rows": [{"key": k, "hours": round(v, 2)} for k, v in sorted(groups.items(), key=lambda kv: -kv[1])]}


@tool("purchase_orders", "Purchase orders, filtered by job, supplier name, status or date.",
      {"job_id": {"type": "integer"}, "supplier": {"type": "string"}, "status": {"type": "string"}, "since": {"type": "string"}}, money=True)
def purchase_orders(ctx: Ctx, job_id: int = 0, supplier: str = "", status: str = "", since: str = ""):
    stmt = select(PurchaseOrder).order_by(PurchaseOrder.id.desc())
    if job_id:
        stmt = stmt.where(PurchaseOrder.job_id == job_id)
    if status:
        stmt = stmt.where(PurchaseOrder.status == status)
    if since:
        stmt = stmt.where(PurchaseOrder.order_date >= _d(since))
    out = []
    for po in ctx.db.scalars(stmt.limit(300)):
        if supplier and supplier.lower() not in po.supplier_name.lower():
            continue
        o = purchasing.po_out(ctx.db, po)
        out.append({k: o[k] for k in ("po_no", "job_no", "job", "supplier", "status", "order_date", "value", "bill_amount", "bill_variance")})
    return out


@tool("invoices", "Invoices: status, overdue, and the aged debtors totals.", {"status": {"type": "string"}, "job_id": {"type": "integer"}},
      money=True)
def invoices(ctx: Ctx, status: str = "", job_id: int = 0):
    stmt = select(Invoice).order_by(Invoice.issue_date.desc())
    if status:
        stmt = stmt.where(Invoice.status == status)
    if job_id:
        stmt = stmt.where(Invoice.job_id == job_id)
    rows = [purchasing.invoice_out(ctx.db, i) for i in ctx.db.scalars(stmt.limit(300))]
    return {"aged": purchasing.aged_debtors(ctx.db)["buckets"],
            "invoices": [{k: r[k] for k in ("invoice_no", "job_no", "customer", "issue_date", "due_date", "amount", "total", "status", "days_overdue")}
                         for r in rows]}


@tool("supplier_prices", "Current supplier prices for a product (words or a code) across every supplier, cheapest first; or the "
      "cheapest-supplier summary by product group when the query is empty.", {"query": {"type": "string"}}, money=True)
def supplier_price(ctx: Ctx, query: str = ""):
    if not query:
        c = supplier_prices.comparison(ctx.db, limit=50)
        return {"products_compared": c["products"], "saving_total": c["saving_total"], "groups": c["groups"][:30],
                "top_savings": c["rows"][:20], "supplier_wins": c["supplier_wins"]}
    rows = supplier_prices.search(ctx.db, query, 100)
    return sorted(rows, key=lambda r: (r["product_key"] or r["code"], r["price"]))


@tool("sales_summary", "Leads, quotes and wins: conversion rates, days to quote and to win, pipeline, by source / estimator / sector.",
      {"months": {"type": "integer"}, "sector": {"type": "string"}})
def sales_summary(ctx: Ctx, months: int = 12, sector: str = ""):
    jobs = [j for j in _jobs(ctx) if not sector or j.sector == sector]
    d = sales.dashboard(ctx.db, jobs, max(1, min(months, 36)))
    return {k: d[k] for k in ("period", "leads", "quotes_sent", "won", "lost", "conversion", "days", "value", "pipeline", "by_source",
                              "by_estimator", "by_sector", "by_work_type", "lost_reasons", "monthly")}


@tool("customer_feedback", "Customer feedback and NPS by department, client type, customer and month.", {"months": {"type": "integer"}})
def customer_feedback(ctx: Ctx, months: int = 12):
    r = crm.nps_report(ctx.db, max(1, min(months, 36)))
    return {k: r[k] for k in ("overall", "by_department", "by_client_type", "by_month")} | {"lowest_customers": r["by_customer"][:15],
                                                                                          "recent": r["recent"][:20]}


@tool("customers", "Find customers and their jobs, money owed, NPS and recent activity.", {"query": {"type": "string"}}, ["query"])
def customers(ctx: Ctx, query: str):
    out = []
    for c in ctx.db.scalars(select(Customer).where(or_(Customer.name.ilike(f"%{query}%"), Customer.email.ilike(f"%{query}%"))).limit(10)):
        s = crm.customer_summary(ctx.db, c)
        jobs = [j for j in ctx.db.scalars(select(Job).where(Job.customer_id == c.id)) if can_see_job(ctx.user, j)]
        out.append({"id": c.id, "name": c.name, "type": c.kind, "phone": c.phone, "email": c.email, "nps": s["nps"],
                    "jobs": [{"job_id": j.id, "job_no": j.job_no, "name": j.name, "status": j.work_status or "quote"} for j in jobs[:20]],
                    **({"invoiced_total": s["invoiced_total"], "owing": s["owing"]} if has(ctx.user, "can_finance") else {}),
                    "recent_activity": s["activities"][:5]})
    return out


@tool("plant_status", "Plant and vehicles: who has what, status, service / rego due, open defects, this week's pre-starts and washes.")
def plant_status(ctx: Ctx):
    from .routers.project import compliance

    return compliance(ctx.db, ctx.user)


@tool("who_is_working", "Who's clocked in right now, on which job, since when.")
def who_is_working(ctx: Ctx):
    return ts.who_is_working(ctx.db)


@tool("show_report", "Show the person a report: a table (and optionally a bar or line chart) under your answer, downloadable as a "
      "spreadsheet. Rows must line up with the columns. Use numbers (not text) for numeric cells.",
      {"title": {"type": "string"}, "summary": {"type": "string"},
       "columns": {"type": "array", "items": {"type": "string"}},
       "rows": {"type": "array", "items": {"type": "array", "items": {"type": ["string", "number", "null"]}}},
       "chart": {"type": "object", "properties": {"type": {"type": "string", "enum": ["bar", "line"]},
                                                  "x": {"type": "string", "description": "column for the labels"},
                                                  "y": {"type": "array", "items": {"type": "string"}, "description": "numeric columns to plot (max 3)"}},
                 "required": ["type", "x", "y"], "additionalProperties": False}},
      ["title", "columns", "rows"])
def show_report(ctx: Ctx, title: str, columns: list, rows: list, summary: str = "", chart: dict | None = None):
    if not columns or any(len(r) != len(columns) for r in rows):
        raise ToolError("Every row needs one value per column")
    if chart and (chart.get("x") not in columns or any(y not in columns for y in chart.get("y", []))):
        raise ToolError("The chart's x and y must be column names")
    rep = {"title": title[:200], "summary": summary[:500], "columns": columns, "rows": rows[:2000], "chart": chart}
    ctx.reports.append(rep)
    return "Shown to the person."


def money_ok(user: User) -> bool:
    """Money tools need the Finance permission and the Finance feature not hidden for this person."""
    from sqlalchemy.orm import object_session

    from . import features

    db = object_session(user)
    return has(user, "can_finance") and (db is None or features.level(db, user, "finance") != "none")


def schemas(user: User) -> list[dict]:
    return [t.schema() for t in TOOLS.values() if not t.money or money_ok(user)]


def run_tool(ctx: Ctx, name: str, args: dict) -> str:
    t = TOOLS.get(name)
    if t is None:
        raise ToolError(f"No tool called {name}")
    if t.money and not money_ok(ctx.user):
        raise ToolError("This person doesn't have access to the money side. Say so.")
    out = t.fn(ctx, **args)
    return out if isinstance(out, str) else json.dumps(out, default=str)


# --- conversation ---
def session(db: Session, user: User, fresh: bool = False) -> ChatSession:
    s = db.scalar(select(ChatSession).where(ChatSession.scope == "company", ChatSession.user_id == user.id, ChatSession.active.is_(True)))
    if s is not None and not fresh:
        return s
    if s is not None:
        s.active = False
    tools = schemas(user)
    s = ChatSession(job_id=None, scope="company", user_id=user.id, tool_names=[t["name"] for t in tools],
                    system=SYSTEM.format(today=date.today().strftime("%A %d %B %Y"), name=user.name or user.email, role=user.role,
                                         finance=", can see finance" if has(user, "can_finance") else ", no finance access"))
    db.add(s)
    db.flush()
    return s


def visible(db: Session, user: User) -> list[dict]:
    s = db.scalar(select(ChatSession).where(ChatSession.scope == "company", ChatSession.user_id == user.id, ChatSession.active.is_(True)))
    if s is None:
        return []
    return [{"id": m.id, "role": m.role, "text": m.text, "reports": m.reports or [], "at": m.created_at.isoformat()}
            for m in db.scalars(select(ChatMessage).where(ChatMessage.session_id == s.id).order_by(ChatMessage.id))
            if not m.hidden and (m.text or m.reports)]


def ask(db: Session, user: User, text: str) -> dict:
    model = chat.get_model()
    if model is None:
        raise AIUnavailable("The AI isn't switched on for this server (no API key), so Ask Lorojo can't answer yet.")
    s = session(db, user)
    if sum(len(json.dumps(m.content)) for m in db.scalars(select(ChatMessage).where(ChatMessage.session_id == s.id))) > chat.MAX_SESSION_CHARS:
        s = session(db, user, fresh=True)
    first_new = db.scalar(select(ChatMessage.id).order_by(ChatMessage.id.desc()).limit(1)) or 0
    db.add(ChatMessage(session_id=s.id, role="user", content=[{"type": "text", "text": text}], text=text, user_id=user.id))
    if not s.title:
        s.title = text[:200]
    db.commit()
    tools = [t for t in schemas(user) if t["name"] in (s.tool_names or [])]
    ctx = Ctx(db, user, [])
    for _ in range(MAX_STEPS):
        history = [{"role": m.role, "content": m.content}
                   for m in db.scalars(select(ChatMessage).where(ChatMessage.session_id == s.id).order_by(ChatMessage.id))]
        stop, content, _m = model.respond(s.system, tools, history)
        said = "\n".join(b.get("text", "") for b in content if b.get("type") == "text").strip()
        if stop == "refusal":
            said = said or "Sorry, I can't help with that one."
        msg = ChatMessage(session_id=s.id, role="assistant", content=content, text=said)
        db.add(msg)
        db.commit()
        if stop != "tool_use":
            if ctx.reports:
                msg.reports = ctx.reports
            if stop == "max_tokens":
                msg.text = (said + "\n\n(My answer was cut short. Ask me to carry on.)").strip()
            db.commit()
            break
        results = []
        for block in content:
            if block.get("type") != "tool_use":
                continue
            try:
                out = run_tool(ctx, block["name"], block.get("input") or {})
                results.append({"type": "tool_result", "tool_use_id": block["id"], "content": out[:60_000]})
            except ToolError as e:
                results.append({"type": "tool_result", "tool_use_id": block["id"], "content": str(e), "is_error": True})
            except Exception as e:  # noqa: BLE001
                log.exception("Ask Peak tool %s failed", block.get("name"))
                db.rollback()
                results.append({"type": "tool_result", "tool_use_id": block["id"], "content": f"That didn't work ({e.__class__.__name__}).",
                                "is_error": True})
        db.add(ChatMessage(session_id=s.id, role="user", content=results, hidden=True, user_id=user.id))
        db.commit()
    else:
        last = db.scalar(select(ChatMessage).where(ChatMessage.session_id == s.id, ChatMessage.role == "assistant").order_by(ChatMessage.id.desc()))
        if last is not None and ctx.reports:
            last.reports = ctx.reports
            db.commit()
    return {"messages": [m for m in visible(db, user) if m["id"] > first_new]}


def report_xlsx(rep: dict) -> bytes:
    import io

    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    ws = wb.active
    ws.title = "Report"
    ws.append([rep.get("title", "Report")])
    ws["A1"].font = Font(bold=True, size=14)
    if rep.get("summary"):
        ws.append([rep["summary"]])
    ws.append([])
    ws.append(rep["columns"])
    for c in ws[ws.max_row]:
        c.font = Font(bold=True)
    for r in rep["rows"]:
        ws.append(r)
    for i, col in enumerate(rep["columns"], start=1):
        ws.column_dimensions[ws.cell(row=ws.max_row, column=i).column_letter].width = max(12, min(45, len(str(col)) + 4))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()

