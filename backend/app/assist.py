"""AI-assisted steps shared by the per-sheet tools and the autopilot.

Everything created here is a suggestion (status "suggested", source "ai"): it stays out of
totals and pricing until a person approves it.
"""
import math

import pymupdf
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import storage
from .audit import record, snapshot
from .geometry import RunShape, overlap_fraction
from .models import CountItem, CountType, Material, Run, Service, Sheet, StyleMapping, User
from .pdf_processing import refresh_currency
from .scale import pick_title_block_scale, stated_m_per_pt
from .suggest import chain_segments, extract_segments
from .takeoff import recompute_run, resolve_scale


def read_and_apply(db: Session, reader, sheet: Sheet, user: User) -> dict:
    """Read a sheet with the AI and fill in what it found (unless a person has confirmed the sheet)."""
    services = [s.code for s in db.scalars(select(Service).where(Service.active.is_(True)))]
    count_types = [c.name for c in db.scalars(select(CountType).where(CountType.active.is_(True)))]
    png = storage.local_path(sheet.image_key).read_bytes()
    reading = reader.read_sheet(png, sheet.extracted_text, services, count_types)
    before = snapshot(sheet)
    sheet.ai_reading = {
        "sheet_no": reading.sheet_no, "title": reading.title, "revision": reading.revision, "scale_text": reading.scale_text,
        "sheet_type": reading.sheet_type, "services": reading.services, "is_hydraulic": reading.is_hydraulic,
        "confidence": reading.confidence, "model": reading.model,
        "legend": [{"description": e.description, "item_type": e.item_type, "service_code": e.service_code} for e in reading.legend],
        "count_tags": [{"tag": t.tag, "item_type": t.item_type} for t in getattr(reading, "count_tags", [])],
    }
    applied = False
    if not sheet.confirmed:
        # Only fill in what the AI read; keep anything it left blank.
        sheet.sheet_no = reading.sheet_no or sheet.sheet_no
        sheet.title = reading.title or sheet.title
        sheet.revision = reading.revision or sheet.revision
        sheet.classification = reading.sheet_type
        sheet.services_shown = reading.services
        sheet.is_hydraulic = reading.is_hydraulic
        sheet.confidence = reading.confidence
        if reading.scale_text and not sheet.stated_scale:
            st = pick_title_block_scale(reading.scale_text)
            if st:
                sheet.stated_scale = st.text
                sheet.stated_m_per_pt = stated_m_per_pt(st.ratio, st.paper, sheet.width_pt, sheet.height_pt)
        sheet.proposed = {"classification": reading.sheet_type, "services": reading.services,
                          "is_hydraulic": reading.is_hydraulic, "source": "ai"}
        applied = True
    db.flush()
    refresh_currency(db, sheet.job_id)
    record(db, user.id, "sheet", sheet.id, "ai_read", before, snapshot(sheet))
    return {"sheet_id": sheet.id, "applied": applied, "reading": sheet.ai_reading}


def create_suggested_runs(db: Session, sheet: Sheet, assigns: list[dict], user: User, client: str = "",
                          remember: bool = True, min_length_m: float = 0.5) -> dict:
    """Turn line styles into suggested runs. assigns: [{key, service_id, dn, material}].

    Raises KeyError(style key) if a style isn't on the sheet. The caller commits.
    """
    styles = extract_segments(sheet)
    existing = [RunShape(r.id, r.geometry, r.service_id, r.dn, len(r.geometry) < 2)
                for r in db.scalars(select(Run).where(Run.sheet_id == sheet.id))]
    materials = {m.name: m.waste_pct for m in db.scalars(select(Material))}
    created, skipped_overlap, skipped_short, skipped_scale = 0, 0, 0, 0
    for a in assigns:
        st = styles.get(a["key"])
        if st is None:
            raise KeyError(a["key"])
        svc = db.get(Service, a["service_id"])
        if remember:
            m = db.scalar(select(StyleMapping).where(StyleMapping.client == client, StyleMapping.style_key == a["key"]))
            if m is None:
                m = StyleMapping(client=client, style_key=a["key"])
                db.add(m)
            m.service_id, m.dn, m.material = a["service_id"], a["dn"], a["material"]
        for pts in chain_segments(st["segments"]):
            length_pt = sum(math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]) for i in range(len(pts) - 1))
            try:
                mpp, vp_id = resolve_scale(sheet, pts)
            except Exception:  # crosses a viewport edge or the viewport isn't verified
                skipped_scale += 1
                continue
            if length_pt * mpp < min_length_m:
                skipped_short += 1
                continue
            shape = RunShape(-1, pts, a["service_id"], a["dn"], False)
            if any(e.service_id == a["service_id"] and overlap_fraction(shape, e) > 0.8 for e in existing):
                skipped_overlap += 1
                continue
            run = Run(job_id=sheet.job_id, sheet_id=sheet.id, viewport_id=vp_id, service_id=a["service_id"], dn=a["dn"],
                      material=a["material"], stage_id=svc.default_stage_id, geometry=[list(p) for p in pts], m_per_pt=mpp,
                      waste_pct=materials.get(a["material"], 0.0), status="suggested", source="ai", created_by=user.id)
            recompute_run(db, run)
            db.add(run)
            db.flush()
            existing.append(RunShape(run.id, pts, a["service_id"], a["dn"], False))
            created += 1
    record(db, user.id, "sheet", sheet.id, "suggest_runs", after={"job_id": sheet.job_id, "created": created})
    return {"created": created, "skipped_overlapping": skipped_overlap, "skipped_short": skipped_short,
            "skipped_viewport_edge": skipped_scale}


def count_tagged_items(db: Session, sheet: Sheet, tags: list[dict], user: User, excluded: set[str] = frozenset()) -> int:
    """Suggest a count at every place a tag (e.g. "FW") is printed on the sheet.

    tags: [{"tag": "FW", "item_type": "Floor waste"}]. Skips spots that already have a count of that type,
    and items whose service is in `excluded` (service codes).
    """
    codes = {s.id: s.code for s in db.scalars(select(Service))}
    types = {c.name: c for c in db.scalars(select(CountType).where(CountType.active.is_(True)))
             if codes.get(c.default_service_id) not in excluded}
    wanted = {}
    for t in tags:
        tag = (t.get("tag") or "").strip().upper()
        if tag and len(tag) <= 12 and t.get("item_type") in types:
            wanted[tag] = types[t["item_type"]]
    if not wanted:
        return 0
    doc = pymupdf.open(storage.local_path(sheet.file.storage_key))
    try:
        page = doc[sheet.page_no - 1]
        mat = page.rotation_matrix
        words = page.get_text("words")
    finally:
        doc.close()
    # The title block, legend and notes repeat tags too; leave out the title block area.
    tb_x, tb_y = sheet.width_pt * 0.62, sheet.height_pt * 0.55
    existing = {}
    for c in db.scalars(select(CountItem).where(CountItem.sheet_id == sheet.id)):
        existing.setdefault(c.item_type, []).append((c.x, c.y))
    legend_words = _legend_tag_positions(words, mat, wanted)
    created = 0
    for x0, y0, x1, y1, word, *_ in words:
        ct = wanted.get(word.strip().strip(".,;:()").upper())
        if ct is None:
            continue
        r = pymupdf.Rect(x0, y0, x1, y1) * mat
        cx, cy = (r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2
        if cx > tb_x and cy > tb_y:
            continue
        if (round(cx), round(cy)) in legend_words:
            continue
        near = existing.setdefault(ct.name, [])
        if any(math.hypot(cx - ex, cy - ey) < 12 for ex, ey in near):
            continue
        service_id = ct.default_service_id
        if service_id is None:
            continue
        svc = db.get(Service, service_id)
        db.add(CountItem(job_id=sheet.job_id, sheet_id=sheet.id, service_id=service_id, item_type=ct.name, x=cx, y=cy,
                         stage_id=ct.default_stage_id or (svc.default_stage_id if svc else None),
                         status="suggested", source="ai", created_by=user.id))
        near.append((cx, cy))
        created += 1
    if created:
        record(db, user.id, "sheet", sheet.id, "suggest_counts", after={"job_id": sheet.job_id, "created": created, "by": "tags"})
    return created


def _legend_tag_positions(words, mat, wanted) -> set:
    """Tags that sit in a legend line (a tag followed by its description words) aren't items."""
    out = set()
    by_line = {}
    for w in words:
        by_line.setdefault((w[5], w[6]), []).append(w)
    for line in by_line.values():
        if len(line) < 3:
            continue
        for w in line:
            if w[4].strip().strip(".,;:()").upper() in wanted:
                r = pymupdf.Rect(w[0], w[1], w[2], w[3]) * mat
                out.add((round((r.x0 + r.x1) / 2), round((r.y0 + r.y1) / 2)))
    return out
