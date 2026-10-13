"""Marked-up PDF: each measured sheet with its take-off drawn over it, a colour legend and that
sheet's totals, plus a cover page with the job totals."""
from collections import defaultdict
from datetime import datetime, timezone

import pymupdf
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import storage
from .models import CountItem, Job, Run, Service, Sheet
from .takeoff import job_totals


def _rgb(hex_colour: str) -> tuple:
    h = hex_colour.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)) if len(h) >= 6 else (0, 0, 0)


def _text_box(page, rect, lines: list[tuple[str, tuple | None]], fontsize: float):
    """A white panel with optional colour swatches, sized to its lines."""
    page.draw_rect(rect, color=(0.2, 0.2, 0.2), fill=(1, 1, 1), width=0.6, fill_opacity=0.92)
    y = rect.y0 + fontsize * 1.4
    for text, colour in lines:
        x = rect.x0 + fontsize * 0.6
        if colour is not None:
            page.draw_rect(pymupdf.Rect(x, y - fontsize * 0.8, x + fontsize * 1.6, y - fontsize * 0.1), color=colour, fill=colour)
            x += fontsize * 2.2
        page.insert_text((x, y), text, fontsize=fontsize, color=(0, 0, 0))
        y += fontsize * 1.35


def build_markup_pdf(db: Session, job_id: int, include_suggested: bool = True) -> bytes:
    job = db.get(Job, job_id)
    services = {s.id: s for s in db.scalars(select(Service))}
    sheets = list(db.scalars(select(Sheet).where(Sheet.job_id == job_id, Sheet.is_current.is_(True)).order_by(Sheet.file_id, Sheet.page_no)))
    runs_by: dict[int, list[Run]] = defaultdict(list)
    for r in db.scalars(select(Run).where(Run.job_id == job_id)):
        if include_suggested or r.status == "confirmed":
            runs_by[r.sheet_id].append(r)
    counts_by: dict[int, list[CountItem]] = defaultdict(list)
    for c in db.scalars(select(CountItem).where(CountItem.job_id == job_id)):
        if include_suggested or c.status == "confirmed":
            counts_by[c.sheet_id].append(c)

    out = pymupdf.open()
    # Cover page (A4 landscape)
    cover = out.new_page(width=842, height=595)
    t = job_totals(db, job_id)
    cover.insert_text((40, 60), f"{job.name}", fontsize=20)
    cover.insert_text((40, 84), " · ".join(x for x in [f"Quote {job.quote_no}" if job.quote_no else "", job.client, job.address] if x), fontsize=10)
    cover.insert_text((40, 102), f"Take-off mark-up generated {datetime.now(timezone.utc).strftime('%d %b %Y %H:%M')} UTC. "
                                 "Solid = confirmed, dashed = suggested (not in totals).", fontsize=9, color=(0.35, 0.35, 0.35))
    y = 140
    cover.insert_text((40, y), "Confirmed totals by service (m, incl. waste)", fontsize=12)
    y += 20
    colour_of = {s.code: _rgb(s.colour) for s in services.values()}
    for s in t["services"]:
        cover.draw_rect(pymupdf.Rect(40, y - 9, 56, y - 1), color=colour_of.get(s["service_code"]), fill=colour_of.get(s["service_code"]))
        cover.insert_text((64, y), f"{s['service_code']}  {s['service_name']}", fontsize=10)
        cover.insert_text((330, y), f"{s['total_m']:,.2f}", fontsize=10)
        y += 16
    cover.insert_text((64, y + 4), "Total", fontsize=10)
    cover.insert_text((330, y + 4), f"{t['grand_total_m']:,.2f}", fontsize=10)
    y += 34
    cover.insert_text((40, y), "Sheets", fontsize=12)
    y += 18
    for sh in sheets:
        if sh.id in runs_by or sh.id in counts_by:
            cover.insert_text((40, y), f"{sh.sheet_no or 'p' + str(sh.page_no)}  Rev {sh.revision or '-'}  {sh.title[:80]}", fontsize=9)
            y += 13
            if y > 570:
                break

    for sh in sheets:
        runs, counts = runs_by.get(sh.id, []), counts_by.get(sh.id, [])
        if not runs and not counts:
            continue
        src = pymupdf.open(storage.local_path(sh.file.storage_key))
        page = out.new_page(width=sh.width_pt, height=sh.height_pt)
        page.show_pdf_page(page.rect, src, sh.page_no - 1)
        src.close()
        scale = max(sh.width_pt, sh.height_pt) / 2384  # line weights relative to an A1 sheet
        lw = max(1.2, 3.0 * scale)

        per_service: dict[int, float] = defaultdict(float)
        for r in runs:
            colour = _rgb(services[r.service_id].colour)
            dashes = None if r.status == "confirmed" else f"[{6 * scale:.1f} {4 * scale:.1f}] 0"
            if len(r.geometry) > 1:
                page.draw_polyline([pymupdf.Point(x, y) for x, y in r.geometry], color=colour, width=lw, dashes=dashes,
                                   stroke_opacity=0.85, lineCap=1, lineJoin=1)
                (x0, y0), (x1, y1) = r.geometry[0], r.geometry[1]
                page.insert_text(((x0 + x1) / 2 + 3, (y0 + y1) / 2 - 3), f"DN{r.dn} {r.length_m + r.vertical_m:.1f}m",
                                 fontsize=max(5, 6 * scale), color=colour)
            if r.vertical_m > 0:
                page.draw_circle(pymupdf.Point(*r.geometry[0]), 4 * scale + 2, color=colour, fill=(1, 1, 1), width=lw * 0.6)
            if r.status == "confirmed":
                per_service[r.service_id] += r.length_m + r.vertical_m
        per_count: dict[tuple, int] = defaultdict(int)
        for c in counts:
            colour = _rgb(services[c.service_id].colour)
            s = 4 * scale + 2
            page.draw_rect(pymupdf.Rect(c.x - s, c.y - s, c.x + s, c.y + s), color=colour,
                           fill=colour if c.status == "confirmed" else None, width=1)
            if c.status == "confirmed":
                per_count[(services[c.service_id].code, c.item_type)] += 1

        fs = max(6.0, 8 * scale)
        lines = [(f"{sh.sheet_no or 'p' + str(sh.page_no)} Rev {sh.revision or '-'}: take-off mark-up", None)]
        for sid, metres in sorted(per_service.items(), key=lambda kv: services[kv[0]].order):
            lines.append((f"{services[sid].code}  {metres:,.2f} m (plan + vertical)", _rgb(services[sid].colour)))
        for (code, item), n in sorted(per_count.items()):
            lines.append((f"{code} {item} x {n}", colour_of.get(code)))
        if any(r.status != "confirmed" for r in runs) or any(c.status != "confirmed" for c in counts):
            lines.append(("Dashed / hollow = suggested, not counted", None))
        width = max(len(text) for text, _ in lines) * fs * 0.55 + fs * 3
        _text_box(page, pymupdf.Rect(12, 12, 12 + width, 12 + fs * 1.35 * len(lines) + fs), lines, fs)

    data = out.tobytes(garbage=3, deflate=True)
    out.close()
    return data
