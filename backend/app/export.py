"""Excel BOQ export. Every number comes from takeoff.job_totals, the same function the
screen uses."""
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import CountItem, Flag, GeneratedItem, Job, Level, Rule, Run, Service, Sheet, Stage
from .takeoff import d2, job_totals, run_waste_m

HEADER_FILL = PatternFill("solid", fgColor="1F3A5F")
HEADER_FONT = Font(bold=True, color="FFFFFF")
M_FMT = "#,##0.00"


def _sheet(wb: Workbook, title: str, headers: list[str], rows: list[list], metre_cols: set[int] = frozenset()):
    ws = wb.create_sheet(title)
    ws.append(headers)
    for c in ws[1]:
        c.fill = HEADER_FILL
        c.font = HEADER_FONT
    for r in rows:
        ws.append(r)
    for col in metre_cols:
        for cell in ws.iter_rows(min_row=2, min_col=col, max_col=col):
            cell[0].number_format = M_FMT
    for i, h in enumerate(headers, 1):
        width = max([len(str(h))] + [len(str(r[i - 1])) for r in rows if i - 1 < len(r) and r[i - 1] is not None])
        ws.column_dimensions[get_column_letter(i)].width = min(max(width + 2, 8), 60)
    ws.freeze_panes = "A2"
    return ws


def build_workbook(db: Session, job_id: int) -> bytes:
    job = db.get(Job, job_id)
    t = job_totals(db, job_id)
    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    for row in [
        ["Job", job.name], ["Client", job.client], ["Builder", job.builder], ["Address", job.address],
        ["Quote no.", job.quote_no], ["Due date", job.due_date.isoformat() if job.due_date else ""],
        [], ["Lengths in metres. Confirmed quantities on current sheets only."],
    ]:
        ws.append(row)
    for c in ws["A"][:6]:
        c.font = Font(bold=True)
    ws.append([])
    ws.append(["Service", "Name", "Plan (m)", "Vertical (m)", "Waste (m)", "Total (m)"])
    for c in ws[ws.max_row]:
        c.fill, c.font = HEADER_FILL, HEADER_FONT
    for s in t["services"]:
        ws.append([s["service_code"], s["service_name"], s["plan_m"], s["vertical_m"], s["waste_m"], s["total_m"]])
    ws.append(["Total", "", None, None, None, t["grand_total_m"]])
    ws[ws.max_row][0].font = Font(bold=True)
    for row in ws.iter_rows(min_row=11, min_col=3, max_col=6):
        for c in row:
            c.number_format = M_FMT
    ex = t["excluded"]
    if any(ex.values()):
        ws.append([])
        ws.append([f"Not included: {ex['suggested_runs']} unconfirmed runs, {ex['suggested_counts']} unconfirmed counts, "
                   f"{ex['superseded_runs']} runs on superseded sheets."])
    ws.column_dimensions["A"].width = 14
    ws.column_dimensions["B"].width = 36
    for col in "CDEF":
        ws.column_dimensions[col].width = 13

    _sheet(wb, "By service", ["Service", "DN", "Material", "Plan (m)", "Vertical (m)", "Waste (m)", "Total (m)", "Runs"],
           [[l["service_code"], l["dn"], l["material"], l["plan_m"], l["vertical_m"], l["waste_m"], l["total_m"], l["runs"]] for l in t["lines"]],
           {4, 5, 6, 7})

    _sheet(wb, "By stage", ["Stage", "Service", "Total (m)"],
           [[s["stage"], s["service_code"], s["total_m"]] for s in t["stages"]], {3})

    # Stage-by-service matrix: rows reconcile to the service totals.
    codes = [s["service_code"] for s in t["services"]]
    cells: dict = {}
    for s in t["stages"]:
        cells.setdefault(s["stage"], {})[s["service_code"]] = s["total_m"]
    matrix = [[stage] + [cells[stage].get(c) for c in codes] + [round(sum(cells[stage].values()), 2)] for stage in cells]
    matrix.append(["Total"] + [s["total_m"] for s in t["services"]] + [t["grand_total_m"]])
    _sheet(wb, "Stage x service", ["Stage"] + codes + ["Total (m)"], matrix, set(range(2, len(codes) + 3)))

    _sheet(wb, "Counts", ["Service", "Item", "Stage", "Qty"],
           [[c["service_code"], c["item_type"], c["stage"], c["qty"]] for c in t["counts"]])

    # Traceability: every run with the sheet it came from.
    services = {s.id: s.code for s in db.scalars(select(Service))}
    stages = {s.id: s.name for s in db.scalars(select(Stage))}
    levels = {l.id: l.name for l in db.scalars(select(Level).where(Level.job_id == job_id))}
    sheets = {s.id: s for s in db.scalars(select(Sheet).where(Sheet.job_id == job_id))}
    run_rows = []
    for r in db.scalars(select(Run).where(Run.job_id == job_id).order_by(Run.id)):
        sh = sheets[r.sheet_id]
        waste = run_waste_m(r)
        run_rows.append([
            r.id, sh.sheet_no or f"p{sh.page_no}", sh.revision, services[r.service_id], r.dn, r.material,
            levels.get(r.level_id, ""), r.location_tag, stages.get(r.stage_id, ""),
            r.length_m, r.vertical_m, float(waste), float(d2(r.length_m) + d2(r.vertical_m) + waste),
            r.status, "yes" if sh.is_current else "no (superseded)",
        ])
    _sheet(wb, "Run detail", ["Run ID", "Sheet", "Rev", "Service", "DN", "Material", "Level", "Location", "Stage",
                              "Plan (m)", "Vertical (m)", "Waste (m)", "Total (m)", "Status", "Current sheet"],
           run_rows, {10, 11, 12, 13})

    count_rows = []
    for c in db.scalars(select(CountItem).where(CountItem.job_id == job_id).order_by(CountItem.id)):
        sh = sheets[c.sheet_id]
        count_rows.append([c.id, sh.sheet_no or f"p{sh.page_no}", services[c.service_id], c.item_type,
                           levels.get(c.level_id, ""), c.location_tag, stages.get(c.stage_id, ""), c.status])
    _sheet(wb, "Count detail", ["Count ID", "Sheet", "Service", "Item", "Level", "Location", "Stage", "Status"], count_rows)

    from .rules import DISCLAIMER, effective_qty  # local import: rules imports takeoff

    fittings = []
    gen = list(db.scalars(select(GeneratedItem).where(GeneratedItem.job_id == job_id).order_by(GeneratedItem.id)))
    rule_names = {r.id: r.name for r in db.scalars(select(Rule))}
    for g in gen:
        q = effective_qty(g)
        fittings.append([stages.get(g.stage_id, "Unstaged"), services.get(g.service_id, ""), g.description, g.uom, q,
                         g.qty if g.overridden_qty is not None else None,
                         rule_names.get(g.rule_id, "Manual" if g.rule_id is None else "(deleted rule)"),
                         _source_label(g.source_ref, sheets, db), g.note])
    fittings.sort(key=lambda r: (r[0], r[1], r[2]))
    ws_f = _sheet(wb, "Fittings and sundries", ["Stage", "Service", "Item", "Unit", "Qty", "Generated qty (if overridden)",
                                                 "Rule", "Source", "Note"], fittings)
    ws_f.append([])
    ws_f.append([DISCLAIMER])

    flag_rows = []
    sheet_labels = {s.id: s.sheet_no or f"p{s.page_no}" for s in sheets.values()}
    for f in db.scalars(select(Flag).where(Flag.job_id == job_id).order_by(Flag.severity, Flag.check_type, Flag.id)):
        flag_rows.append([f.severity, f.check_type, sheet_labels.get(f.sheet_id, ""), f.message, f.status, f.note])
    _sheet(wb, "Flags and notes", ["Severity", "Check", "Sheet", "Message", "Status", "Note"], flag_rows)

    if job.price_book_version_id:
        _pricing_sheet(wb, db, job)

    reg = []
    for s in sorted(sheets.values(), key=lambda s: (s.sheet_no or "~", s.revision)):
        reg.append([s.sheet_no, s.title, s.revision, s.page_size, s.stated_scale,
                    "yes" if s.scale_verified else "no", s.classification, ", ".join(s.services_shown or []),
                    "yes" if s.is_current else "no", "yes" if s.is_duplicate else ""])
    _sheet(wb, "Sheet register", ["Sheet no.", "Title", "Rev", "Page size", "Stated scale", "Scale verified",
                                  "Type", "Services", "Current", "Duplicate"], reg)

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _source_label(ref: str, sheets: dict, db: Session) -> str:
    """Readable source for a generated line, e.g. "Run #12 (H-101)"."""
    kind, _, rest = (ref or "").partition(":")
    if kind == "run" and rest.isdigit():
        r = db.get(Run, int(rest))
        sh = sheets.get(r.sheet_id) if r else None
        return f"Run #{rest}" + (f" ({sh.sheet_no or f'p{sh.page_no}'})" if sh else "")
    if kind == "count" and rest.isdigit():
        c = db.get(CountItem, int(rest))
        sh = sheets.get(c.sheet_id) if c else None
        return f"{c.item_type if c else 'Count'} #{rest}" + (f" ({sh.sheet_no or f'p{sh.page_no}'})" if sh else "")
    return {"job": "Whole job", "manual": "Added by hand"}.get(ref, ref)


def _pricing_sheet(wb: Workbook, db: Session, job: Job) -> None:
    from .pricing import price_job

    p = price_job(db, job.id)
    rows = [[l["stage"], l["service_code"], l["kind"], l["description"], l["qty"], l["uom"], l["target_kind"], l["target_code"],
             l.get("target_description", ""), l.get("material_cost"), l.get("labour_hours"), l.get("labour_cost"),
             l.get("cost"), l.get("margin_pct"), l.get("sell")] for l in p["lines"]]
    ws = _sheet(wb, "Pricing", ["Stage", "Service", "Source", "Take-off item", "Qty", "Unit", "Priced as", "Code", "Code description",
                                "Material $", "Labour hrs", "Labour $", "Cost $", "Margin %", "Sell $ ex GST"], rows,
                {10, 12, 13, 15})
    for a in p["allowances"]:
        label = {"pc": "PC item", "provisional": "Provisional sum", "exclusion": "Exclusion"}[a["kind"]]
        ws.append([a["stage"], a["service_code"], label, a["description"], None, None, None, None, None,
                   None, None, None, a["amount"] if a["kind"] != "exclusion" else None, a.get("margin_pct"), a.get("sell")])
    for u in p["unmapped"]:
        ws.append([u["stage"], u["service_code"], u["kind"], u["description"], u["qty"], u["uom"], "UNMAPPED"])
    s = p["summary"]
    if s:
        ws.append([])
        ws.append([f"Price book: {p['price_book']['label']}" + ("" if p["price_book"]["locked"] else " (DRAFT)"),
                   f"Margins as {p['margin_basis']}"])
        for label, key in (("Materials", "material_cost"), ("Labour", "labour_cost"), ("Labour hours", "labour_hours"),
                           ("PC items and provisional sums", "allowances_cost"), ("Total cost", "cost"), ("Margin", "margin"),
                           ("Total ex GST", "sell_ex_gst"), ("GST", "gst"), ("Total inc GST", "sell_inc_gst")):
            ws.append([label, None, None, None, None, None, None, None, None, None, None, None, None, None, s[key]])
            ws.cell(ws.max_row, 15).number_format = M_FMT if key != "labour_hours" else "0.00"
        if p["missing_codes"]:
            ws.append([f"Codes missing from the price book: {', '.join(p['missing_codes'])}"])
