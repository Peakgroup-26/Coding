"""Scale maths. Everything here is pure and unit-tested.

A sheet's scale is stored as metres of real-world length per PDF point on the page.
"""
import math
import re
from dataclasses import dataclass

MM_PER_PT = 25.4 / 72.0

# ISO A sizes in mm (short side, long side)
PAPER_SIZES_MM: dict[str, tuple[float, float]] = {
    "A0": (841.0, 1189.0),
    "A1": (594.0, 841.0),
    "A2": (420.0, 594.0),
    "A3": (297.0, 420.0),
    "A4": (210.0, 297.0),
}

PAGE_SIZE_TOLERANCE = 0.03  # 3% to allow for plotter margins and odd exports


class ScaleError(ValueError):
    pass


def distance(p1, p2) -> float:
    return math.hypot(p2[0] - p1[0], p2[1] - p1[1])


def polyline_length(points) -> float:
    return sum(distance(points[i], points[i + 1]) for i in range(len(points) - 1))


def detect_page_size(width_pt: float, height_pt: float) -> str:
    short_mm, long_mm = sorted((width_pt * MM_PER_PT, height_pt * MM_PER_PT))
    for name, (s, l) in PAPER_SIZES_MM.items():
        if abs(short_mm - s) / s <= PAGE_SIZE_TOLERANCE and abs(long_mm - l) / l <= PAGE_SIZE_TOLERANCE:
            return name
    return "custom"


@dataclass
class StatedScale:
    text: str
    ratio: float  # the 100 in 1:100
    paper: str | None  # the A1 in "1:100 @ A1", if given


_SCALE_RE = re.compile(
    r"1\s*:\s*(\d{1,5}(?:\.\d+)?)(?:\s*(?:@|AT)\s*(A[0-4]))?",
    re.IGNORECASE,
)


def parse_stated_scales(text: str) -> list[StatedScale]:
    """Find every "1:100" or "1:100 @ A1" in some text."""
    out = []
    for m in _SCALE_RE.finditer(text or ""):
        ratio = float(m.group(1))
        if ratio < 1 or ratio > 10000:
            continue
        paper = m.group(2).upper() if m.group(2) else None
        out.append(StatedScale(text=m.group(0).strip(), ratio=ratio, paper=paper))
    return out


def pick_title_block_scale(text: str) -> StatedScale | None:
    """Choose the scale most likely to be the sheet's main scale.

    Prefer one that names a paper size (title blocks usually do), then the most common one.
    """
    scales = parse_stated_scales(text)
    if not scales:
        return None
    with_paper = [s for s in scales if s.paper]
    pool = with_paper or scales
    counts: dict[float, int] = {}
    for s in pool:
        counts[s.ratio] = counts.get(s.ratio, 0) + 1
    # Most common wins; ties go to the first one found (dicts keep insertion order).
    best_ratio = max(counts, key=counts.get)
    return next(s for s in pool if s.ratio == best_ratio)


def stated_m_per_pt(ratio: float, intended_paper: str | None, width_pt: float, height_pt: float) -> float:
    """Metres per point for a stated scale, corrected for the paper the PDF is actually at.

    A sheet drawn "1:100 @ A1" but saved at A3 is shrunk by 841/420, so each point on the
    page stands for that much more real length. If no paper is stated, the page is taken as
    the intended size.
    """
    if ratio <= 0:
        raise ScaleError("Scale ratio must be positive")
    factor = 1.0
    if intended_paper:
        if intended_paper not in PAPER_SIZES_MM:
            raise ScaleError(f"Unknown paper size {intended_paper}")
        intended_long = PAPER_SIZES_MM[intended_paper][1]
        actual_long = max(width_pt, height_pt) * MM_PER_PT
        factor = intended_long / actual_long
    return MM_PER_PT * factor * ratio / 1000.0


def calibrate_two_point(p1, p2, known_m: float) -> float:
    if known_m is None or known_m <= 0:
        raise ScaleError("Known distance must be greater than zero")
    d = distance(p1, p2)
    if d < 1.0:
        raise ScaleError("Calibration points are too close together")
    return known_m / d


@dataclass
class Verification:
    measured_m: float
    known_m: float
    error_pct: float
    ok: bool


def verify(m_per_pt: float, p1, p2, known_m: float, tolerance: float = 0.01) -> Verification:
    if known_m is None or known_m <= 0:
        raise ScaleError("Check dimension must be greater than zero")
    if distance(p1, p2) < 1.0:
        raise ScaleError("Check points are too close together")
    measured = distance(p1, p2) * m_per_pt
    err = abs(measured - known_m) / known_m
    # Round before comparing so 1.000% is treated as within 1%.
    return Verification(measured_m=measured, known_m=known_m, error_pct=err * 100, ok=round(err, 9) <= tolerance)


def ratio_from_m_per_pt(m_per_pt: float, width_pt: float, height_pt: float, paper: str | None) -> float:
    """The 1:N this calibration implies at a given paper size (for showing the user)."""
    factor = 1.0
    if paper and paper in PAPER_SIZES_MM:
        factor = PAPER_SIZES_MM[paper][1] / (max(width_pt, height_pt) * MM_PER_PT)
    return m_per_pt * 1000.0 / (MM_PER_PT * factor)
