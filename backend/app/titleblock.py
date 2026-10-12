"""Title-block reading, sheet classification and revision ordering. Pure functions."""
import re
from dataclasses import dataclass, field

# Keywords that suggest which hydraulic services a sheet shows.
SERVICE_KEYWORDS: dict[str, list[str]] = {
    "CW": ["cold water", "water services", "water reticulation", "potable"],
    "HW": ["hot water", "warm water", "tempered water", "hw flow", "hw return"],
    "HWS": ["hot water plant", "hws", "heat pump", "hot water unit"],
    "SW": ["site water", "external water", "water main", "property service", "site services"],
    "SAN": ["sanitary", "sewer", "drainage", "soil and waste", "under slab", "stack", "vent"],
    "TW": ["trade waste", "grease arrestor", "grease trap", "pre-treatment"],
    "FIRE": ["fire", "hydrant", "hose reel", "booster"],
    "RW": ["roof", "downpipe", "gutter", "roof water", "rainwater"],
    "STW": ["stormwater", "storm water"],
    "CSTW": ["civil", "detention", "headwall", "site stormwater"],
    "PUMP": ["pump", "rising main"],
    "GAS": ["gas"],
}

HYDRAULIC_WORDS = ["hydraulic", "plumbing", "drainage", "water", "sewer", "stormwater", "fire", "gas", "sanitary"]

SHEET_TYPE_KEYWORDS: list[tuple[str, list[str]]] = [
    ("cover", ["cover sheet", "drawing register", "drawing list", "title sheet"]),
    ("legend", ["legend", "abbreviations", "general notes", "notes and legend"]),
    ("schematic", ["schematic", "riser diagram", "isometric"]),
    ("section", ["section", "elevation"]),
    ("detail", ["detail", "details", "typical"]),
    ("plan", ["plan", "layout", "level", "ground floor", "first floor", "basement", "roof"]),
]

_REV_RE = re.compile(r"\bREV(?:ISION)?\.?\s*[:\-]?\s*([A-Z]?\d{0,2}[A-Z]?)\b", re.IGNORECASE)
_LABELLED_SHEET_RE = re.compile(
    r"\b(?:DWG|DRAWING|SHEET)\s*(?:NO\.?|NUMBER|#)\s*[:\-]?\s*([A-Z0-9][A-Z0-9\-_.]{1,20})",
    re.IGNORECASE,
)
_SHEET_TOKEN_RE = re.compile(r"\b(H(?:YD)?[\-_ ]?\d{2,4}[A-Z]?|[A-Z]{1,4}[\-_]\d{2,4}[A-Z]?)\b")
_DATE_RE = re.compile(r"\b(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})\b")


@dataclass
class TitleBlock:
    sheet_no: str = ""
    title: str = ""
    revision: str = ""
    drawing_date: str = ""


@dataclass
class Classification:
    classification: str = "other"
    services: list[str] = field(default_factory=list)
    is_hydraulic: bool = False
    confidence: float = 0.0


def read_title_block(title_block_text: str, title_lines: list[str] | None = None) -> TitleBlock:
    """Pull sheet number, revision, date and title from the title-block area's text.

    title_lines: candidate title strings (e.g. largest text in the title block), best first.
    """
    tb = TitleBlock()
    text = title_block_text or ""

    m = _LABELLED_SHEET_RE.search(text)
    if m:
        tb.sheet_no = m.group(1).strip(".-_").upper()
    else:
        tokens = _SHEET_TOKEN_RE.findall(text.upper())
        if tokens:
            # Prefer hydraulic-looking numbers (H-101, HYD-201).
            hyd = [t for t in tokens if t.startswith("H")]
            tb.sheet_no = (hyd or tokens)[-1].replace(" ", "-")

    revs = [r for r in _REV_RE.findall(text) if r]
    if revs:
        tb.revision = revs[-1].upper()

    d = _DATE_RE.findall(text)
    if d:
        tb.drawing_date = d[-1]

    for line in title_lines or []:
        clean = " ".join(line.split())
        if len(clean) >= 6 and not _SCALE_LIKE.search(clean) and clean.upper() != tb.sheet_no:
            tb.title = clean[:200]
            break
    return tb


_SCALE_LIKE = re.compile(r"^\s*(scale|1\s*:|rev|dwg|drawing no|sheet no|date)", re.IGNORECASE)


def classify(text: str, title: str = "") -> Classification:
    t = f"{title} {title} {text}".lower()  # title counts double
    services = []
    hits = 0
    for code, words in SERVICE_KEYWORDS.items():
        n = sum(t.count(w) for w in words)
        if n:
            services.append(code)
            hits += n
    sheet_type = "other"
    title_l = (title or "").lower()
    for name, words in SHEET_TYPE_KEYWORDS:
        if any(w in title_l for w in words):
            sheet_type = name
            break
    else:
        for name, words in SHEET_TYPE_KEYWORDS:
            if any(w in t for w in words):
                sheet_type = name
                break
    is_hyd = any(w in t for w in HYDRAULIC_WORDS)
    conf = 0.2
    if is_hyd:
        conf += 0.3
    if services:
        conf += min(0.3, 0.05 * hits)
    if sheet_type != "other":
        conf += 0.2
    return Classification(classification=sheet_type, services=services, is_hydraulic=is_hyd, confidence=round(min(conf, 0.95), 2))


def title_key(title: str) -> str:
    """Normalised title used to remember a user's classification corrections."""
    return re.sub(r"[^a-z ]", "", (title or "").lower()).strip()[:200]


def revision_rank(rev: str) -> tuple:
    """Sort key for revisions. Preliminary (P1, P2) sort below issued (A, B / 0, 1).

    Within a group, numbers compare numerically and letters alphabetically.
    """
    r = (rev or "").strip().upper()
    if not r:
        return (-1, 0, "", 0)
    prelim = 0 if re.fullmatch(r"P\d+", r) else 1
    nums = re.findall(r"\d+", r)
    letters = re.sub(r"[\d]", "", r if prelim else r[1:])
    return (prelim, len(letters), letters, int(nums[-1]) if nums else 0)
