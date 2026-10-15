"""Automatic scale check: confirm a sheet's scale against dimension strings printed on it.

The brief's rule still holds: nothing is measured until the scale has been checked against a
second dimension and agrees within 1%. Here the second dimension comes from the drawing itself.
A dimension text (e.g. "3600", in mm) sitting beside a straight line of matching length at the
calibrated scale is one confirmation. Two or more independent confirmations, and no nearby
dimension that disagrees, verify the sheet. Otherwise it's left for a person to check.
"""
import math
import re
from dataclasses import dataclass

import pymupdf

from . import storage
from .models import Sheet
from .suggest import extract_segments

NUMBER_MM = re.compile(r"^(\d{3,6})$")
NUMBER_M = re.compile(r"^(\d{1,4}(?:\.\d{1,3})?)\s?m$", re.IGNORECASE)
MIN_DIM_M = 0.6  # ignore tiny dimensions: their line work is too short to test the scale
NEAR_PT = 30.0  # how far the text may sit from its dimension line
PARALLEL_DEG = 5.0
REQUIRED = 2


@dataclass
class DimText:
    value_m: float
    text: str
    cx: float
    cy: float
    horizontal: bool


@dataclass
class DimMatch:
    text: str
    known_m: float
    measured_m: float
    error_pct: float
    p1: list[float]
    p2: list[float]


def _dimension_texts(sheet: Sheet) -> list[DimText]:
    doc = pymupdf.open(storage.local_path(sheet.file.storage_key))
    try:
        page = doc[sheet.page_no - 1]
        mat = page.rotation_matrix
        out = []
        for x0, y0, x1, y1, word, *_ in page.get_text("words"):
            w = word.strip().replace(",", "")
            m = NUMBER_MM.match(w)
            value = int(m.group(1)) / 1000.0 if m else None
            if value is None:
                m = NUMBER_M.match(w)
                value = float(m.group(1)) if m else None
            if value is None or value < MIN_DIM_M:
                continue
            r = pymupdf.Rect(x0, y0, x1, y1) * mat
            out.append(DimText(value, word, (r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2, r.width >= r.height))
        return out
    finally:
        doc.close()


def _best_line(d: DimText, segments: list, m_per_pt: float):
    """The nearest straight line that this text could be dimensioning, and its measured length."""
    best = None
    for x1, y1, x2, y2 in segments:
        dx, dy = x2 - x1, y2 - y1
        length = math.hypot(dx, dy)
        if length * m_per_pt < MIN_DIM_M * 0.5:
            continue
        angle = abs(math.degrees(math.atan2(dy, dx))) % 180
        horizontal = min(angle, 180 - angle) <= PARALLEL_DEG
        vertical = abs(angle - 90) <= PARALLEL_DEG
        if not ((d.horizontal and horizontal) or (not d.horizontal and vertical)):
            continue
        # Text sits beside the middle of its dimension line.
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        along = abs((d.cx - mx) * dx + (d.cy - my) * dy) / length
        across = abs((d.cx - mx) * dy - (d.cy - my) * dx) / length
        if along > length / 4 or across > NEAR_PT:
            continue
        measured = length * m_per_pt
        err = abs(measured - d.value_m) / d.value_m
        if best is None or err < best[0]:
            best = (err, measured, [x1, y1], [x2, y2])
    return best


def check_dimensions(sheet: Sheet, m_per_pt: float, tolerance: float = 0.01) -> dict:
    """Compare dimension strings on the sheet with the line work at this scale.

    Returns {"ok": bool, "matches": [...], "conflicts": [...]}. A conflict is a dimension whose
    nearest parallel line is close in length (within 10%) but outside the tolerance: a sign
    the scale is slightly off, so the sheet is not verified.
    """
    if not sheet.has_vectors or not m_per_pt:
        return {"ok": False, "matches": [], "conflicts": [], "reason": "No vector line work to check against"}
    segments = [s for st in extract_segments(sheet).values() for s in st["segments"]]
    matches, conflicts = [], []
    for d in _dimension_texts(sheet):
        best = _best_line(d, segments, m_per_pt)
        if best is None:
            continue
        err, measured, p1, p2 = best
        m = DimMatch(d.text, d.value_m, round(measured, 3), round(err * 100, 3), p1, p2)
        if round(err, 9) <= tolerance:
            matches.append(m)
        elif err <= 0.10:
            conflicts.append(m)
    ok = len(matches) >= REQUIRED and not conflicts
    reason = ""
    if conflicts:
        reason = f"{len(conflicts)} dimension(s) on the sheet disagree with the scale by more than 1%"
    elif len(matches) < REQUIRED:
        reason = "Not enough dimensions on the sheet to confirm the scale automatically"
    return {"ok": ok, "matches": [m.__dict__ for m in matches[:10]], "conflicts": [m.__dict__ for m in conflicts[:10]],
            "reason": reason}
