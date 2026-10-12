"""Split uploaded PDFs into sheets: render each page, extract text and vector line ends,
read the title block and propose a classification."""
import json
import logging

import fitz  # PyMuPDF
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import config, storage
from .models import ClassificationCorrection, DrawingFile, Job, Sheet
from .scale import detect_page_size, pick_title_block_scale, stated_m_per_pt
from .titleblock import classify, read_title_block, revision_rank, title_key

log = logging.getLogger(__name__)

MAX_SNAP_POINTS = 250_000


def _title_block_region(rect: fitz.Rect) -> fitz.Rect:
    """Most Australian drawing title blocks sit along the right edge or bottom-right corner."""
    return fitz.Rect(rect.x0 + rect.width * 0.62, rect.y0 + rect.height * 0.55, rect.x1, rect.y1)


def _title_candidates(page: fitz.Page, region: fitz.Rect) -> list[str]:
    """Text lines in the title block, largest font first."""
    lines = []
    d = page.get_text("dict", clip=region)
    for block in d.get("blocks", []):
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            text = "".join(s["text"] for s in spans).strip()
            if text:
                size = max(s["size"] for s in spans)
                lines.append((size, text))
    lines.sort(key=lambda x: -x[0])
    return [t for _, t in lines]


def _snap_points(page: fitz.Page) -> list[list[float]]:
    """End points of vector lines and curves, in displayed-page coordinates."""
    mat = page.rotation_matrix
    seen = set()
    out = []
    try:
        drawings = page.get_drawings()
    except Exception:  # some malformed PDFs fail here; snapping is optional
        return out
    for dr in drawings:
        for item in dr.get("items", []):
            kind = item[0]
            if kind == "l":
                pts = [item[1], item[2]]
            elif kind == "c":
                pts = [item[1], item[4]]
            elif kind == "re":
                r = item[1]
                pts = [r.tl, r.tr, r.br, r.bl]
            else:
                continue
            for p in pts:
                q = fitz.Point(p) * mat
                key = (round(q.x * 2) / 2, round(q.y * 2) / 2)
                if key not in seen:
                    seen.add(key)
                    out.append([key[0], key[1]])
                    if len(out) >= MAX_SNAP_POINTS:
                        return out
    return out


def process_file(db: Session, drawing: DrawingFile) -> list[Sheet]:
    job = db.get(Job, drawing.job_id)
    pdf_path = storage.local_path(drawing.storage_key)
    sheets = []
    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        drawing.status = "failed"
        drawing.error = f"Could not open PDF: {e}"
        db.commit()
        return []

    drawing.page_count = doc.page_count
    corrections = {
        c.title_key: c
        for c in db.scalars(select(ClassificationCorrection).where(ClassificationCorrection.client == (job.client or "")))
    }

    for i, page in enumerate(doc):
        rect = page.rect  # already rotated
        width_pt, height_pt = rect.width, rect.height
        page_size = detect_page_size(width_pt, height_pt)

        zoom = min(config.RENDER_MAX_PX / max(width_pt, height_pt), 4.0)
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        image_key = f"jobs/{job.id}/files/{drawing.id}/page-{i + 1}.png"
        pix.save(str(storage.local_path(image_key)))

        text = page.get_text("text") or ""
        has_text = len(text.strip()) > 20
        region = _title_block_region(rect)
        tb_text = page.get_text("text", clip=region) or ""
        tb = read_title_block(tb_text, _title_candidates(page, region))

        snaps = _snap_points(page)
        snap_key = f"jobs/{job.id}/files/{drawing.id}/page-{i + 1}-snaps.json"
        storage.save_bytes(snap_key, json.dumps(snaps).encode())

        stated = pick_title_block_scale(tb_text) or pick_title_block_scale(text)
        stated_mpp = None
        if stated:
            stated_mpp = stated_m_per_pt(stated.ratio, stated.paper, width_pt, height_pt)

        cls = classify(text, tb.title)
        sheet = Sheet(
            file_id=drawing.id,
            job_id=job.id,
            page_no=i + 1,
            sheet_no=tb.sheet_no,
            title=tb.title or f"{drawing.filename} p{i + 1}",
            revision=tb.revision,
            drawing_date=tb.drawing_date,
            width_pt=width_pt,
            height_pt=height_pt,
            page_size=page_size,
            image_key=image_key,
            image_width_px=pix.width,
            image_height_px=pix.height,
            snap_key=snap_key,
            has_text_layer=has_text,
            has_vectors=len(snaps) > 0,
            extracted_text=text[:20000],
            stated_scale=stated.text if stated else "",
            stated_m_per_pt=stated_mpp,
            classification=cls.classification,
            services_shown=cls.services,
            is_hydraulic=cls.is_hydraulic,
            confidence=cls.confidence,
        )
        prior = corrections.get(title_key(sheet.title))
        if prior:
            sheet.classification = prior.classification
            sheet.services_shown = prior.services_shown
            sheet.is_hydraulic = prior.is_hydraulic
            sheet.confidence = 0.9
        db.add(sheet)
        sheets.append(sheet)

    doc.close()
    drawing.status = "ready"
    db.flush()
    refresh_currency(db, job.id)
    db.commit()
    return sheets


def refresh_currency(db: Session, job_id: int) -> None:
    """Mark duplicates (same sheet number and revision) and keep only the latest revision current."""
    sheets = list(db.scalars(select(Sheet).where(Sheet.job_id == job_id).order_by(Sheet.id)))
    by_no: dict[str, list[Sheet]] = {}
    for s in sheets:
        s.is_duplicate = False
        s.is_current = True
        if s.sheet_no:
            by_no.setdefault(s.sheet_no.upper(), []).append(s)
    for group in by_no.values():
        seen_revs: dict[str, Sheet] = {}
        for s in group:
            key = (s.revision or "").upper()
            if key in seen_revs:
                s.is_duplicate = True
                s.is_current = False
            else:
                seen_revs[key] = s
        originals = list(seen_revs.values())
        latest = max(originals, key=lambda s: revision_rank(s.revision))
        for s in originals:
            s.is_current = s is latest
