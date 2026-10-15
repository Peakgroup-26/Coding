"""What the chat AI can do to a job. Each tool works through the same code as the buttons on screen,
records its changes in the audit log under the person chatting, and respects their permissions.

A tool returns (result for the AI, short line for the person or None). Tools that change things
refuse while the job is final or while the autopilot is reading it.
"""
import json
from dataclasses import dataclass
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import autopilot, civil, memory, tender
from .access import has
from .audit import record, snapshot
from .models import (AiMemory, CivilBoqLine, CivilRate, CivilRateSet, CountItem, CountType, Job, JobAllowance, Material, Run,
                     Service, Sheet, TenderDocument, TenderRequirement, User)
from .takeoff import job_totals


class ToolError(Exception):
    """A tool couldn't do what was asked; the message goes back to the AI."""


@dataclass
class Ctx:
    db: Session
    job: Job
    user: User


@dataclass
class Tool:
    name: str
    description: str
    properties: dict
    required: list[str]
    fn: Callable
    kinds: tuple = ("hydraulic", "civil")
    writes: bool = False

    def schema(self) -> dict:
        return {"name": self.name, "description": self.description,
                "input_schema": {"type": "object", "properties": self.properties, "required": self.required,
                                 "additionalProperties": False}}


TOOLS: dict[str, Tool] = {}


def tool(name, description, properties=None, required=None, kinds=("hydraulic", "civil"), writes=False):
    def wrap(fn):
        TOOLS[name] = Tool(name, description, properties or {}, required or [], fn, kinds, writes)
        return fn
    return wrap


def run(ctx: Ctx, name: str, args: dict) -> tuple[str, str | None]:
    t = TOOLS.get(name)
    if t is None or (ctx.job.kind or "hydraulic") not in t.kinds:
        raise ToolError(f"There's no tool called {name} for this job")
    if t.writes:
        if ctx.job.status == "final":
            raise ToolError("This estimate is final. A reviewer has to reopen it before anything changes.")
        if autopilot.is_running(ctx.job.id):
            raise ToolError("The autopilot is still reading this job. Wait for it to finish, then try again.")
    out, action = t.fn(ctx, **args)
    return (out if isinstance(out, str) else json.dumps(out, default=str)), action


def schemas_for(kind: str) -> list[dict]:
    return [t.schema() for t in TOOLS.values() if kind in t.kinds]


# --- helpers ---
def _services(db) -> dict[str, Service]:
    return {s.code: s for s in db.scalars(select(Service))}


def _service_id(db, code: str) -> int:
    s = _services(db).get((code or "").upper())
    if s is None:
        raise ToolError(f"Unknown service code {code}. Codes: {', '.join(_services(db))}")
    return s.id


def _label(s: Sheet) -> str:
    return s.sheet_no or f"p{s.page_no}"


def _runs(ctx: Ctx, run_ids=None, sheet_id=None, service_code=None, dn=None, material=None, status=None) -> list[Run]:
    q = select(Run).where(Run.job_id == ctx.job.id)
    if run_ids:
        q = q.where(Run.id.in_(run_ids))
    if sheet_id:
        q = q.where(Run.sheet_id == sheet_id)
    if service_code:
        q = q.where(Run.service_id == _service_id(ctx.db, service_code))
    if dn:
        q = q.where(Run.dn == dn)
    if material:
        q = q.where(Run.material == material)
    if status:
        q = q.where(Run.status == status)
    return list(ctx.db.scalars(q))


FILTER = {
    "run_ids": {"type": "array", "items": {"type": "integer"}, "description": "Specific runs; leave empty to use the other filters"},
    "sheet_id": {"type": "integer", "description": "0 for every sheet"},
    "service_code": {"type": "string", "description": "e.g. SAN; empty for any"},
    "dn": {"type": "integer", "description": "0 for any size"},
    "material": {"type": "string", "description": "empty for any"},
    "status": {"type": "string", "enum": ["", "suggested", "confirmed"]},
}
CONFIRM = {"confirmed_by_user": {"type": "boolean", "description": "True only if the person has already agreed to this exact change"}}
BULK_LIMIT = 20


# --- looking ---
@tool("job_summary", "Where the job is up to: sheets, scales, quantities found, what needs attention, tender items.")
def job_summary(ctx: Ctx):
    return snapshot_text(ctx.db, ctx.job, detail=True), None


@tool("list_sheets", "Every sheet with its id, number, title, type, whether it's a hydraulic sheet and whether its scale is confirmed.")
def list_sheets(ctx: Ctx):
    rows = []
    for s in ctx.db.scalars(select(Sheet).where(Sheet.job_id == ctx.job.id, Sheet.is_duplicate.is_(False)).order_by(Sheet.file_id, Sheet.page_no)):
        rows.append({"sheet_id": s.id, "sheet": _label(s), "title": s.title, "rev": s.revision, "type": s.classification,
                     "hydraulic": s.is_hydraulic, "current": s.is_current, "services": s.services_shown or [],
                     "scale": s.stated_scale, "scale_confirmed": s.scale_verified})
    return rows, None


@tool("list_runs", "Pipe runs with their id, sheet, service, DN, material, length and whether they're suggested or approved. Max 300.",
      {k: FILTER[k] for k in ("sheet_id", "service_code", "dn", "material", "status")}, kinds=("hydraulic",))
def list_runs(ctx: Ctx, sheet_id=0, service_code="", dn=0, material="", status=""):
    services = {s.id: s.code for s in ctx.db.scalars(select(Service))}
    sheets = {s.id: _label(s) for s in ctx.db.scalars(select(Sheet).where(Sheet.job_id == ctx.job.id))}
    runs = _runs(ctx, sheet_id=sheet_id, service_code=service_code, dn=dn, material=material, status=status)
    return [{"run_id": r.id, "sheet": sheets.get(r.sheet_id), "service": services.get(r.service_id), "dn": r.dn,
             "material": r.material, "length_m": r.length_m, "vertical_m": r.vertical_m, "status": r.status}
            for r in runs[:300]], None


@tool("totals", "Take-off totals by service, size and material, and the counts. Includes suggestions, shown separately.",
      kinds=("hydraulic",))
def totals(ctx: Ctx):
    confirmed = job_totals(ctx.db, ctx.job.id)
    everything = job_totals(ctx.db, ctx.job.id, include_suggested=True)
    pick = lambda t: {"lines": [{k: l[k] for k in ("service_code", "dn", "material", "total_m")} for l in t["lines"]],
                      "counts": t["counts"], "total_m": t["grand_total_m"]}
    return {"approved": pick(confirmed), "approved_plus_suggested": pick(everything)}, None


@tool("pricing", "The priced estimate summary (needs a price book chosen for the job).", kinds=("hydraulic",))
def pricing(ctx: Ctx):
    from .pricing import price_job

    p = price_job(ctx.db, ctx.job.id)
    if not p["summary"]:
        return "No price book is chosen for this job yet, so it isn't priced.", None
    s = p["summary"]
    return {k: s[k] for k in ("material_cost", "labour_cost", "allowances_cost", "cost", "margin", "sell_ex_gst", "sell_inc_gst")
            } | {"unmapped_items": len(p["unmapped"]), "loadings": s.get("loadings")}, None


# --- changing hydraulic take-off ---
@tool("change_runs", "Change the service, size or material of pipe runs picked by id or by filter. "
      "Changing more than 20 runs needs confirmed_by_user.",
      {**FILTER, **CONFIRM, "set_service_code": {"type": "string", "description": "empty = leave"},
       "set_dn": {"type": "integer", "description": "0 = leave"}, "set_material": {"type": "string", "description": "empty = leave"}},
      ["set_service_code", "set_dn", "set_material"], kinds=("hydraulic",), writes=True)
def change_runs(ctx: Ctx, set_service_code="", set_dn=0, set_material="", confirmed_by_user=False, run_ids=None, sheet_id=0,
                service_code="", dn=0, material="", status=""):
    runs = _runs(ctx, run_ids, sheet_id, service_code, dn, material, status)
    if not runs:
        raise ToolError("No runs match that")
    if len(runs) > BULK_LIMIT and not confirmed_by_user:
        return f"That would change {len(runs)} runs. Tell the person and ask them to confirm first.", None
    new_svc = _service_id(ctx.db, set_service_code) if set_service_code else None
    if set_material and not ctx.db.scalar(select(Material).where(Material.name == set_material)):
        ctx.db.add(Material(name=set_material, waste_pct=0.0))
        ctx.db.flush()
    waste = {m.name: m.waste_pct for m in ctx.db.scalars(select(Material))}
    for r in runs:
        before = snapshot(r)
        if new_svc:
            r.service_id = new_svc
        if set_dn:
            r.dn = set_dn
        if set_material:
            r.material, r.waste_pct = set_material, waste.get(set_material, r.waste_pct)
        if r.status == "suggested" and r.source == "ai":
            r.ai_edited = True
        record(ctx.db, ctx.user.id, "run", r.id, "update", before, snapshot(r))
    what = ", ".join(x for x in (set_service_code, f"DN{set_dn}" if set_dn else "", set_material) if x)
    return f"Changed {len(runs)} run(s) to {what}.", f"Changed {len(runs)} run(s) to {what}"


@tool("delete_runs", "Delete pipe runs picked by id or by filter. More than 20 needs confirmed_by_user.",
      {**FILTER, **CONFIRM}, kinds=("hydraulic",), writes=True)
def delete_runs(ctx: Ctx, confirmed_by_user=False, run_ids=None, sheet_id=0, service_code="", dn=0, material="", status=""):
    runs = _runs(ctx, run_ids, sheet_id, service_code, dn, material, status)
    if not runs:
        raise ToolError("No runs match that")
    if len(runs) > BULK_LIMIT and not confirmed_by_user:
        return f"That would delete {len(runs)} runs. Tell the person and ask them to confirm first.", None
    for r in runs:
        record(ctx.db, ctx.user.id, "run", r.id, "delete", before=snapshot(r))
        ctx.db.delete(r)
    return f"Deleted {len(runs)} run(s).", f"Deleted {len(runs)} run(s)"


@tool("approve_takeoff", "Approve suggested runs and/or counts (all current sheets, or one sheet). Only when the person asks to approve.",
      {"sheet_id": {"type": "integer", "description": "0 for all sheets"}, "what": {"type": "string", "enum": ["all", "runs", "counts"]}},
      ["what"], kinds=("hydraulic",), writes=True)
def approve_takeoff(ctx: Ctx, what="all", sheet_id=0):
    from .routers.autopilot import approve_suggestions

    kinds = {"all": ("run", "count"), "runs": ("run",), "counts": ("count",)}[what]
    r = approve_suggestions(ctx.db, ctx.job, ctx.user, sheet_id or None, kinds)
    return r, f"Approved {r['runs']} run(s) and {r['counts']} count(s)"


@tool("reject_suggestions", "Delete suggested (not yet approved) runs and/or counts, on one sheet or all.",
      {"sheet_id": {"type": "integer", "description": "0 for all sheets"}, "what": {"type": "string", "enum": ["all", "runs", "counts"]}},
      ["what"], kinds=("hydraulic",), writes=True)
def reject_suggestions(ctx: Ctx, what="all", sheet_id=0):
    n = 0
    for kind, model in (("run", Run), ("count", CountItem)):
        if what not in ("all", kind + "s"):
            continue
        q = select(model).where(model.job_id == ctx.job.id, model.status == "suggested")
        if sheet_id:
            q = q.where(model.sheet_id == sheet_id)
        for obj in ctx.db.scalars(q):
            record(ctx.db, ctx.user.id, kind, obj.id, "delete", before=snapshot(obj))
            ctx.db.delete(obj)
            n += 1
    return f"Removed {n} suggestion(s).", f"Removed {n} suggestion(s)"


@tool("take_off_line_style", "Trace every line of one colour / layer / dash style on a sheet as suggested pipe runs of the given "
      "service, size and material, and remember it for this client. Use list_line_styles first to find the style.",
      {"sheet_id": {"type": "integer"}, "style_key": {"type": "string", "description": "From list_line_styles"},
       "service_code": {"type": "string"}, "dn": {"type": "integer"}, "material": {"type": "string"}},
      ["sheet_id", "style_key", "service_code", "dn", "material"], kinds=("hydraulic",), writes=True)
def take_off_line_style(ctx: Ctx, sheet_id, style_key, service_code, dn, material):
    from .assist import create_suggested_runs

    sheet = ctx.db.get(Sheet, sheet_id)
    if sheet is None or sheet.job_id != ctx.job.id:
        raise ToolError("No such sheet on this job")
    if not sheet.scale_verified:
        raise ToolError("This sheet's scale isn't confirmed, so nothing can be measured on it yet. "
                        "The person needs to check one dimension on the sheet first.")
    if dn <= 0:
        raise ToolError("DN must be a positive size in mm")
    if not ctx.db.scalar(select(Material).where(Material.name == material)):
        ctx.db.add(Material(name=material, waste_pct=0.0))
        ctx.db.flush()
    try:
        r = create_suggested_runs(ctx.db, sheet, [{"key": style_key, "service_id": _service_id(ctx.db, service_code), "dn": dn,
                                                   "material": material}], ctx.user, client=ctx.job.client or "", remember=True)
    except KeyError:
        raise ToolError("That line style isn't on this sheet. Use list_line_styles.")
    return r, f"Traced {r['created']} {service_code} DN{dn} run(s) on {_label(sheet)}"


@tool("list_line_styles", "The line styles (colour, dash, width, CAD layer, total length) on a sheet, longest first, and what "
      "each is mapped to for this client if anything.", {"sheet_id": {"type": "integer"}}, ["sheet_id"], kinds=("hydraulic",))
def list_line_styles(ctx: Ctx, sheet_id):
    from .models import StyleMapping
    from .suggest import extract_segments, style_summary

    sheet = ctx.db.get(Sheet, sheet_id)
    if sheet is None or sheet.job_id != ctx.job.id:
        raise ToolError("No such sheet on this job")
    saved = {m.style_key: m for m in ctx.db.scalars(select(StyleMapping).where(StyleMapping.client == (ctx.job.client or "")))}
    out = []
    for st in style_summary(extract_segments(sheet), sheet.calibrated_scale if sheet.scale_verified else None)[:40]:
        m = saved.get(st["key"])
        out.append({k: st[k] for k in ("key", "colour", "dashes", "width", "layer", "length_m")}
                   | ({"mapped_to": {"service_id": m.service_id, "dn": m.dn, "material": m.material}} if m else {}))
    return out, None


@tool("count_tagged_items", "Count every place a text tag (e.g. 'FW', 'HR') is printed on the current hydraulic plans as a "
      "suggested count of an item type.",
      {"tag": {"type": "string"}, "item_type": {"type": "string", "description": "A count item name, e.g. Floor waste"},
       "sheet_id": {"type": "integer", "description": "0 for every current plan"}},
      ["tag", "item_type"], kinds=("hydraulic",), writes=True)
def count_tags(ctx: Ctx, tag, item_type, sheet_id=0):
    from .assist import count_tagged_items

    if not ctx.db.scalar(select(CountType).where(CountType.name == item_type)):
        names = [c.name for c in ctx.db.scalars(select(CountType).where(CountType.active.is_(True)))]
        raise ToolError(f"Unknown item type. Choose one of: {', '.join(names)}")
    q = select(Sheet).where(Sheet.job_id == ctx.job.id, Sheet.is_current.is_(True), Sheet.is_duplicate.is_(False))
    q = q.where(Sheet.id == sheet_id) if sheet_id else q.where(Sheet.classification == "plan", Sheet.is_hydraulic.is_(True))
    n = sum(count_tagged_items(ctx.db, s, [{"tag": tag, "item_type": item_type}], ctx.user,
                               excluded=set(ctx.job.excluded_services or [])) for s in ctx.db.scalars(q))
    return f"Added {n} suggested {item_type} count(s).", f"Counted {n} × {item_type} ({tag})"


@tool("add_allowance", "Add a PC item, provisional sum or exclusion to the estimate.",
      {"kind": {"type": "string", "enum": ["pc", "provisional", "exclusion"]}, "description": {"type": "string"},
       "amount": {"type": "number", "description": "$ ex GST; 0 for an exclusion"},
       "service_code": {"type": "string", "description": "empty for none"}},
      ["kind", "description", "amount"], kinds=("hydraulic",), writes=True)
def add_allowance(ctx: Ctx, kind, description, amount, service_code=""):
    svc = _services(ctx.db).get(service_code.upper()) if service_code else None
    a = JobAllowance(job_id=ctx.job.id, kind=kind, description=description[:500], amount=max(0.0, amount),
                     service_id=svc.id if svc else None, stage_id=svc.default_stage_id if svc else None)
    ctx.db.add(a)
    ctx.db.flush()
    record(ctx.db, ctx.user.id, "allowance", a.id, "create", after=snapshot(a))
    label = {"pc": "PC item", "provisional": "provisional sum", "exclusion": "exclusion"}[kind]
    return f"Added {label}: {description}.", f"Added {label}: {description}" + (f" (${amount:,.0f})" if amount else "")


# --- common: sheets, autopilot, tender documents ---
@tool("set_sheet", "Correct a sheet's type or whether it's a hydraulic sheet (e.g. when the autopilot sorted it wrongly).",
      {"sheet_id": {"type": "integer"}, "sheet_type": {"type": "string", "enum": ["", "plan", "section", "detail", "schematic", "legend", "cover", "other"]},
       "is_hydraulic": {"type": "string", "enum": ["", "yes", "no"]}}, ["sheet_id"], writes=True)
def set_sheet(ctx: Ctx, sheet_id, sheet_type="", is_hydraulic=""):
    s = ctx.db.get(Sheet, sheet_id)
    if s is None or s.job_id != ctx.job.id:
        raise ToolError("No such sheet on this job")
    before = snapshot(s)
    if sheet_type:
        s.classification = sheet_type
    if is_hydraulic:
        s.is_hydraulic = is_hydraulic == "yes"
    s.confirmed = True
    record(ctx.db, ctx.user.id, "sheet", s.id, "update", before, snapshot(s))
    return f"Sheet {_label(s)} updated.", f"Sheet {_label(s)}: {sheet_type or ''} {'hydraulic' if s.is_hydraulic else 'not hydraulic'}".strip()


@tool("run_autopilot", "Start the autopilot again (reads new plans and documents, re-takes-off). reread=true re-reads every sheet "
      "with the AI. It runs in the background; tell the person it has started.",
      {"reread": {"type": "boolean"}}, ["reread"], writes=True)
def run_autopilot(ctx: Ctx, reread):
    ctx.db.commit()  # the autopilot works in its own session
    if not autopilot.start(ctx.job.id, ctx.user.id, reread):
        return "It's already running.", None
    return "Started. It runs in the background; the job page shows progress.", "Started the autopilot" + (" (re-reading every sheet)" if reread else "")


@tool("list_tender_items", "What the tender documents say (each item's id, type, title, quote, page, status, and what accepting does).",
      {"status": {"type": "string", "enum": ["", "suggested", "accepted", "rejected"]}})
def list_tender_items(ctx: Ctx, status=""):
    docs = {d.id: d.filename for d in ctx.db.scalars(select(TenderDocument).where(TenderDocument.job_id == ctx.job.id))}
    q = select(TenderRequirement).where(TenderRequirement.job_id == ctx.job.id)
    if status:
        q = q.where(TenderRequirement.status == status)
    return [{"item_id": r.id, "type": r.category, "title": r.title, "quote": r.quote[:400], "document": docs.get(r.document_id),
             "page": r.page, "status": r.status, "services": r.service_codes, "material": r.material, "percent": r.percent,
             "amount": r.amount, "effect": tender.effect(ctx.db, r), "needs": tender.missing_input(r)} for r in ctx.db.scalars(q)], None


@tool("decide_tender_item", "Accept, reject or undo a tender document item. You can fill in what it needs first (a % loading, a "
      "material, a service, an amount). Only accept when the person asks.",
      {"item_id": {"type": "integer"}, "action": {"type": "string", "enum": ["accept", "reject", "undo"]},
       "percent": {"type": "number", "description": "0 = leave"}, "material": {"type": "string", "description": "empty = leave"},
       "amount": {"type": "number", "description": "0 = leave"}, "service_code": {"type": "string", "description": "empty = leave"},
       "civil_category": {"type": "string", "description": "empty = leave"},
       "applies_to": {"type": "string", "enum": ["", "labour", "material", "all"]}},
      ["item_id", "action"], writes=True)
def decide_tender_item(ctx: Ctx, item_id, action, percent=0, material="", amount=0, service_code="", civil_category="", applies_to=""):
    r = ctx.db.get(TenderRequirement, item_id)
    if r is None or r.job_id != ctx.job.id:
        raise ToolError("No such tender item on this job")
    if action == "accept":
        if r.status == "accepted":
            return "Already accepted.", None
        before = snapshot(r)
        if percent:
            r.percent = percent
        if material:
            r.material = material
        if amount:
            r.amount = amount
        if service_code:
            _service_id(ctx.db, service_code)
            r.service_codes = [service_code.upper()]
        if civil_category:
            r.civil_category = civil_category
        if applies_to:
            r.applies_to = applies_to
        if snapshot(r) != before:
            record(ctx.db, ctx.user.id, "tender_requirement", r.id, "update", before, snapshot(r))
        try:
            tender.apply(ctx.db, r, ctx.user)
        except ValueError as e:
            raise ToolError(str(e))
        return f"Accepted: {tender.effect(ctx.db, r)}", f"Accepted tender item: {r.title}"
    tender.undo(ctx.db, r, ctx.user, new_status="rejected" if action == "reject" else "suggested")
    return f"{action.title()}ed.", f"{'Rejected' if action == 'reject' else 'Undid'} tender item: {r.title}"


# --- civil BOQ ---
@tool("list_boq", "The civil BOQ lines: id, category, description, unit, quantity, rate, amount, status, whether it needs measuring.",
      {"category": {"type": "string", "description": "empty for all"}}, kinds=("civil",))
def list_boq(ctx: Ctx, category=""):
    q = select(CivilBoqLine).where(CivilBoqLine.job_id == ctx.job.id)
    if category:
        q = q.where(CivilBoqLine.category == category)
    rows = [{"line_id": l.id, "category": l.category, "description": l.description, "unit": l.unit, "qty": civil.line_qty(l),
             "rate": l.rate, "amount": float(civil.money(civil.line_qty(l)) * civil.money(l.rate or 0)), "status": l.status,
             "needs_measuring": l.needs_measuring, "note": l.note} for l in sorted(ctx.db.scalars(q), key=lambda l: l.sort)]
    return {"lines": rows[:300], "summary": civil.civil_summary(ctx.db, ctx.job.id)}, None


@tool("change_boq_line", "Change a civil BOQ line's quantity, rate, description, unit or category, and/or approve it.",
      {"line_id": {"type": "integer"}, "qty": {"type": "number", "description": "-1 = leave"},
       "rate": {"type": "number", "description": "-1 = leave"}, "description": {"type": "string", "description": "empty = leave"},
       "unit": {"type": "string", "enum": ["", "m", "m2", "m3", "ea", "t", "item"]}, "category": {"type": "string", "description": "empty = leave"},
       "approve": {"type": "boolean"}}, ["line_id"], kinds=("civil",), writes=True)
def change_boq_line(ctx: Ctx, line_id, qty=-1, rate=-1, description="", unit="", category="", approve=False):
    l = ctx.db.get(CivilBoqLine, line_id)
    if l is None or l.job_id != ctx.job.id:
        raise ToolError("No such BOQ line on this job")
    before = snapshot(l)
    if qty >= 0:
        l.overridden_qty, l.needs_measuring = qty, l.needs_measuring and qty == 0
    if rate >= 0:
        l.rate, l.rate_overridden, l.rate_note = rate, True, "Set in the chat"
    if description:
        l.description = description[:1000]
    if unit:
        l.unit = unit
    if category:
        l.category = category
    if approve:
        l.status = "confirmed"
    record(ctx.db, ctx.user.id, "civil_line", l.id, "update", before, snapshot(l))
    return {"line_id": l.id, "qty": civil.line_qty(l), "rate": l.rate, "status": l.status}, f"Updated BOQ line: {l.description[:60]}"


@tool("add_boq_line", "Add a line to the civil BOQ. Leave rate at -1 to look it up from previous jobs.",
      {"category": {"type": "string"}, "description": {"type": "string"},
       "unit": {"type": "string", "enum": ["m", "m2", "m3", "ea", "t", "item"]}, "qty": {"type": "number"},
       "rate": {"type": "number", "description": "-1 to look it up"}}, ["category", "description", "unit", "qty"],
      kinds=("civil",), writes=True)
def add_boq_line(ctx: Ctx, category, description, unit, qty, rate=-1):
    last = max([l.sort for l in ctx.db.scalars(select(CivilBoqLine).where(CivilBoqLine.job_id == ctx.job.id))], default=0)
    l = CivilBoqLine(job_id=ctx.job.id, sort=last + 1, category=category, description=description[:1000], unit=unit, qty=max(0.0, qty),
                     rate=rate if rate >= 0 else None, rate_overridden=rate >= 0, status="suggested", source="manual",
                     needs_measuring=qty <= 0, note="Added in the chat")
    ctx.db.add(l)
    ctx.db.flush()
    if rate < 0:
        civil.reprice(ctx.db, ctx.job.id)
    record(ctx.db, ctx.user.id, "civil_line", l.id, "create", after=snapshot(l))
    return {"line_id": l.id, "rate": l.rate, "rate_note": l.rate_note}, f"Added BOQ line: {description[:60]}"


@tool("delete_boq_line", "Delete a civil BOQ line.", {"line_id": {"type": "integer"}}, ["line_id"], kinds=("civil",), writes=True)
def delete_boq_line(ctx: Ctx, line_id):
    l = ctx.db.get(CivilBoqLine, line_id)
    if l is None or l.job_id != ctx.job.id:
        raise ToolError("No such BOQ line on this job")
    record(ctx.db, ctx.user.id, "civil_line", l.id, "delete", before=snapshot(l))
    ctx.db.delete(l)
    return "Deleted.", f"Deleted BOQ line: {l.description[:60]}"


@tool("approve_boq", "Approve suggested civil BOQ lines (all that have a quantity, or the given ids). Only when the person asks.",
      {"line_ids": {"type": "array", "items": {"type": "integer"}, "description": "empty = all with a quantity"}},
      kinds=("civil",), writes=True)
def approve_boq(ctx: Ctx, line_ids=None):
    n = 0
    for l in ctx.db.scalars(select(CivilBoqLine).where(CivilBoqLine.job_id == ctx.job.id, CivilBoqLine.status == "suggested")):
        if line_ids and l.id not in line_ids:
            continue
        if not line_ids and l.needs_measuring and not civil.line_qty(l):
            continue
        before = snapshot(l)
        l.status = "confirmed"
        record(ctx.db, ctx.user.id, "civil_line", l.id, "update", before, snapshot(l))
        n += 1
    return f"Approved {n} line(s).", f"Approved {n} BOQ line(s)"


@tool("reprice_boq", "Look up rates for the civil BOQ again from previous jobs (rates typed in are kept).", kinds=("civil",), writes=True)
def reprice_boq(ctx: Ctx):
    n = civil.reprice(ctx.db, ctx.job.id)
    return f"Priced {n} line(s) from previous jobs.", f"Looked up rates again ({n} priced)"


@tool("search_past_rates", "Search previous civil jobs' rates by description.",
      {"query": {"type": "string"}, "unit": {"type": "string", "description": "empty for any"}}, ["query"], kinds=("civil",))
def search_past_rates(ctx: Ctx, query, unit=""):
    if not has(ctx.user, "can_past_rates"):
        raise ToolError("This person doesn't have access to previous job rates.")
    rates = list(ctx.db.scalars(select(CivilRate).join(CivilRateSet).where(CivilRateSet.active.is_(True))))
    sets = {s.id: s.name for s in ctx.db.scalars(select(CivilRateSet))}
    probe = CivilBoqLine(description=query, unit=unit)
    return [{"job": sets.get(r.set_id), "description": r.description, "unit": r.unit, "rate": r.rate, "match": round(s, 2)}
            for s, r in civil.candidates(probe, rates, n=15)], None


# --- memory ---
@tool("remember", "Save something to remember for later work. scope: company (every job), client (this client's jobs) or job. "
      "Use it when the person states a preference, a rule or a correction that should carry forward. One clear sentence.",
      {"text": {"type": "string"}, "scope": {"type": "string", "enum": ["company", "client", "job"]}}, ["text", "scope"])
def remember(ctx: Ctx, text, scope):
    m = memory.remember(ctx.db, ctx.job, text, scope, ctx.user.id)
    return f"Saved as memory {m.id} ({m.scope}).", f"Remembered ({m.scope}): {m.text}"


@tool("forget", "Switch off a memory that's wrong or out of date.", {"memory_id": {"type": "integer"}}, ["memory_id"])
def forget(ctx: Ctx, memory_id):
    m = ctx.db.get(AiMemory, memory_id)
    if m is None:
        raise ToolError("No such memory")
    m.active = False
    record(ctx.db, ctx.user.id, "memory", m.id, "update", after={"active": False})
    return "Done.", f"Forgot: {m.text}"


# --- the job snapshot sent with each message ---
def snapshot_text(db: Session, job: Job, detail: bool = False) -> str:
    lines = [f"Job {job.id}: {job.name} ({'civil BOQ' if job.kind == 'civil' else 'hydraulic take-off'}, {job.sector}); "
             f"quote {job.quote_no or '-'}; client: {job.client or '-'}; status: {job.status}; sales stage: {job.sales_stage}"
             + (f"; quoted ${job.tender_value:,.0f}" if job.tender_value else "")]
    ap = job.autopilot or {}
    state = ap.get("state", "never")
    lines.append(f"Autopilot: {state}" + (f" ({ap.get('step')})" if state in ("queued", "running") else ""))
    for a in (ap.get("attention") or [])[:15]:
        lines.append(f"  needs attention: {a.get('sheet', '')} {a['message']}".rstrip())
    sheets = list(db.scalars(select(Sheet).where(Sheet.job_id == job.id, Sheet.is_duplicate.is_(False))))
    lines.append(f"Sheets: {len(sheets)} ({sum(1 for s in sheets if s.is_current)} current)")
    if job.kind != "civil":
        plans = [s for s in sheets if s.is_current and s.is_hydraulic and s.classification == "plan"]
        for s in plans[:40 if detail else 15]:
            lines.append(f"  plan sheet_id={s.id} {_label(s)} {s.title[:60]} scale {'confirmed' if s.scale_verified else 'NOT confirmed'}")
        t, everything = job_totals(db, job.id), job_totals(db, job.id, include_suggested=True)
        lines.append(f"Pipe: {t['grand_total_m']:.1f} m approved, {everything['grand_total_m']:.1f} m including suggestions; "
                     f"suggestions waiting: {t['excluded']['suggested_runs']} runs, {t['excluded']['suggested_counts']} counts")
        for l in everything["lines"][:30 if detail else 12]:
            lines.append(f"  {l['service_code']} DN{l['dn']} {l['material']}: {l['total_m']:.1f} m")
        allowances = list(db.scalars(select(JobAllowance).where(JobAllowance.job_id == job.id)))
        if allowances:
            lines.append("Allowances / exclusions: " + "; ".join(f"{a.kind} {a.description} ${a.amount:,.0f}" for a in allowances[:15]))
    else:
        s = civil.civil_summary(db, job.id)
        lines.append(f"BOQ: {s['lines']} lines ({s['lines_suggested']} waiting for approval, {s['needs_measuring']} need a "
                     f"quantity, {s['unpriced']} without a rate); approved total ${s['total_confirmed_ex_gst']:,.2f} ex GST")
    reqs = list(db.scalars(select(TenderRequirement).where(TenderRequirement.job_id == job.id)))
    if reqs:
        lines.append(f"Tender document items: {len(reqs)} ({sum(1 for r in reqs if r.status == 'suggested')} waiting)")
    if job.excluded_services:
        lines.append("Excluded: " + ", ".join(job.excluded_services))
    if job.spec_materials:
        lines.append("Specified materials: " + ", ".join(f"{k}: {v}" for k, v in job.spec_materials.items()))
    return "\n".join(lines)


# --- reports and programs ---
@tool("report", "Material list, labour hours, or crew & program (people needed, stage dates, duration, manpower by week, "
      "cash flow) for this job. include_suggested counts items not yet approved.",
      {"which": {"type": "string", "enum": ["materials", "labour", "program"]}, "include_suggested": {"type": "boolean"}},
      ["which"])
def report(ctx: Ctx, which, include_suggested=False):
    from . import reports

    if which == "materials":
        return reports.materials(ctx.db, ctx.job, include_suggested, by_stage=False)["rows"][:200], None
    if which == "labour":
        lab = reports.labour(ctx.db, ctx.job, include_suggested)
        return {k: lab[k] for k in ("by_stage", "by_service", "total_hours", "missing")}, None
    p = reports.program(ctx.db, ctx.job, include_suggested)
    return {k: p[k] for k in ("mode", "start_date", "finish_date", "working_weeks", "calendar_weeks", "stages", "field_hours",
                              "supervision_hours", "pm_hours", "pm_hours_per_week", "peak_people", "base_plumbers",
                              "missing_labour_rates", "cashflow")}, None


@tool("set_program", "Set the planned start date, a target duration in weeks (the crew is then worked out), or a fixed number "
      "of plumbers. Send 0 / empty to leave a value as it is.",
      {"start_date": {"type": "string", "description": "YYYY-MM-DD, or empty"},
       "target_weeks": {"type": "number", "description": "0 = leave; -1 = clear the target and use a fixed crew"},
       "plumbers": {"type": "integer", "description": "0 = leave"}})
def set_program(ctx: Ctx, start_date="", target_weeks=0, plumbers=0):
    from datetime import date as _date

    from . import reports

    before = {"start_date": str(ctx.job.start_date), "target_weeks": ctx.job.target_weeks, "program": ctx.job.program}
    if start_date:
        try:
            ctx.job.start_date = _date.fromisoformat(start_date)
        except ValueError:
            raise ToolError("start_date must be YYYY-MM-DD")
    if target_weeks == -1:
        ctx.job.target_weeks = None
    elif target_weeks > 0:
        ctx.job.target_weeks = target_weeks
    if plumbers > 0:
        ctx.job.program = {**(ctx.job.program or {}), "plumbers": plumbers}
        if target_weeks == 0:
            ctx.job.target_weeks = None
    record(ctx.db, ctx.user.id, "job", ctx.job.id, "program", before,
           {"start_date": str(ctx.job.start_date), "target_weeks": ctx.job.target_weeks, "program": ctx.job.program})
    p = reports.program(ctx.db, ctx.job)
    return ({k: p[k] for k in ("start_date", "finish_date", "working_weeks", "base_plumbers", "peak_people")},
            f"Program: start {p['start_date']}, finish {p['finish_date']}, {p['base_plumbers']} plumber(s)")


@tool("update_sales", "Sales tracking for this job: mark the quote as sent, record won / lost / withdrawn, the price "
      "quoted, the sector, the lead source or contact. Dates fill in as today unless given.",
      {"result": {"type": "string", "enum": ["", "pending", "won", "lost", "withdrawn"]},
       "value": {"type": "number", "description": "Price quoted ex GST; 0 = leave"},
       "mark_quote_sent": {"type": "boolean"},
       "quote_sent_date": {"type": "string", "description": "YYYY-MM-DD, or empty"},
       "decided_date": {"type": "string", "description": "YYYY-MM-DD, or empty"},
       "sector": {"type": "string", "enum": ["", "residential", "commercial", "maintenance"]},
       "lead_source": {"type": "string", "description": "empty = leave"}, "contact": {"type": "string", "description": "empty = leave"}})
def update_sales(ctx: Ctx, result="", value=0, mark_quote_sent=False, quote_sent_date="", decided_date="", sector="", lead_source="", contact=""):
    from datetime import date as _date

    from fastapi import HTTPException

    from .routers.sales import SalesIn, apply_sales

    try:
        body = SalesIn(tender_result=result or None, tender_value=value or None, mark_quote_sent=mark_quote_sent,
                       quote_sent_date=_date.fromisoformat(quote_sent_date) if quote_sent_date else None,
                       decided_date=_date.fromisoformat(decided_date) if decided_date else None,
                       sector=sector or None, lead_source=lead_source or None, contact=contact or None)
        if not value:
            body = body.model_copy(update={"tender_value": ctx.job.tender_value})
        apply_sales(ctx.db, ctx.job, body, ctx.user)
    except ValueError:
        raise ToolError("Dates must be YYYY-MM-DD")
    except HTTPException as e:
        raise ToolError(str(e.detail))
    j = ctx.job
    bits = [x for x in (result and f"result {result}", mark_quote_sent and "quote marked sent", value and f"${value:,.0f}",
                        sector and f"sector {sector}") if x]
    return ({"stage": j.sales_stage, "quote_sent_date": str(j.quote_sent_date), "decided_date": str(j.decided_date),
             "result": j.tender_result, "value": j.tender_value}, "Sales: " + (", ".join(bits) or "updated"))
