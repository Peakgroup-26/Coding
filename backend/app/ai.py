"""AI-assisted sheet reading, behind an interface so the model or provider can be swapped.

Off unless TAKEOFF_AI=claude is set: drawings are commercial-in-confidence, so sending them to
an outside API is a deliberate choice for Peak to make. The local suggestion tools (line-style
runs and symbol matching in suggest.py) never send anything anywhere.
"""
import base64
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Protocol

log = logging.getLogger(__name__)

SHEET_TYPES = ["plan", "section", "detail", "schematic", "legend", "cover", "other"]


@dataclass
class LegendEntry:
    description: str
    item_type: str = ""  # a count item name, if the symbol is a counted item
    service_code: str = ""  # a service code, if the entry is a line type for a service


@dataclass
class CountTag:
    tag: str  # text label printed on the plan next to each item, e.g. "FW" or "HR"
    item_type: str


@dataclass
class StyleAssignment:
    key: str
    service_code: str
    dn: int
    material: str
    confidence: float = 0.0


@dataclass
class CivilTakeoff:
    category: str
    description: str
    unit: str
    quantity: float
    basis: str  # where on the sheet the quantity came from
    confidence: float = 0.0
    needs_measuring: bool = False


@dataclass
class CivilReading:
    sheet_no: str = ""
    title: str = ""
    revision: str = ""
    sheet_type: str = "other"
    items: list[CivilTakeoff] = field(default_factory=list)
    model: str = ""


@dataclass
class CivilGroup:
    item_ids: list[int]
    description: str
    category: str
    unit: str
    combine: str  # sum | max
    reason: str = ""


@dataclass
class SheetReading:
    sheet_no: str = ""
    title: str = ""
    revision: str = ""
    scale_text: str = ""
    sheet_type: str = "other"
    services: list[str] = field(default_factory=list)
    is_hydraulic: bool = False
    confidence: float = 0.0
    legend: list[LegendEntry] = field(default_factory=list)
    count_tags: list[CountTag] = field(default_factory=list)
    model: str = ""


class AIUnavailable(Exception):
    pass


class SheetReader(Protocol):
    name: str

    def read_sheet(self, page_png: bytes, page_text: str, service_codes: list[str], count_types: list[str]) -> SheetReading: ...

    # Optional (the autopilot skips a step when the reader doesn't have it):
    # map_styles(page_png, legend, styles, service_codes, materials) -> list[StyleAssignment]
    # read_civil_sheet(page_png, page_text, categories) -> CivilReading
    # consolidate_civil(items) -> list[CivilGroup]
    # match_civil_rates(lines) -> {line_id: (rate_ids, reason)}


def _schema(service_codes: list[str], count_types: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {
            "sheet_no": {"type": "string", "description": "Drawing number from the title block, e.g. H-101. Empty if not shown."},
            "title": {"type": "string", "description": "Drawing title from the title block."},
            "revision": {"type": "string", "description": "Current revision from the title block, e.g. C or P2."},
            "scale_text": {"type": "string", "description": "The sheet's main scale as written, e.g. '1:100 @ A1'. Empty if none."},
            "sheet_type": {"type": "string", "enum": SHEET_TYPES},
            "services": {"type": "array", "items": {"type": "string", "enum": service_codes},
                         "description": "Hydraulic services this sheet shows."},
            "is_hydraulic": {"type": "boolean", "description": "True if this is a hydraulic/plumbing/drainage/fire/gas services drawing."},
            "confidence": {"type": "number", "description": "0 to 1: how sure you are about sheet_type and services."},
            "legend": {
                "type": "array",
                "description": "Entries from any legend or symbol key on the sheet. Empty if there is none.",
                "items": {
                    "type": "object",
                    "properties": {
                        "description": {"type": "string", "description": "The legend text, plus the line style or colour if it's a line."},
                        "item_type": {"type": "string", "enum": [""] + count_types,
                                      "description": "Matching countable item, or empty."},
                        "service_code": {"type": "string", "enum": [""] + service_codes,
                                         "description": "Service this line type or symbol belongs to, or empty."},
                    },
                    "required": ["description", "item_type", "service_code"],
                    "additionalProperties": False,
                },
            },
            "count_tags": {
                "type": "array",
                "description": "Text labels printed on the plan beside each instance of a countable item (e.g. 'FW' beside "
                               "every floor waste, 'HR' beside every hose reel). Only labels that tag individual items.",
                "items": {
                    "type": "object",
                    "properties": {
                        "tag": {"type": "string"},
                        "item_type": {"type": "string", "enum": count_types},
                    },
                    "required": ["tag", "item_type"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["sheet_no", "title", "revision", "scale_text", "sheet_type", "services", "is_hydraulic", "confidence",
                     "legend", "count_tags"],
        "additionalProperties": False,
    }


def _style_schema(keys: list[str], service_codes: list[str], materials: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {"assignments": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "enum": keys},
                "service_code": {"type": "string", "enum": service_codes},
                "dn": {"type": "integer", "description": "Nominal size in mm, e.g. 100"},
                "material": {"type": "string", "enum": materials},
                "confidence": {"type": "number", "description": "0 to 1"},
            },
            "required": ["key", "service_code", "dn", "material", "confidence"],
            "additionalProperties": False,
        }}},
        "required": ["assignments"],
        "additionalProperties": False,
    }


CIVIL_UNITS = ["m", "m2", "m3", "ea", "t", "item"]


def _civil_schema(categories: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {
            "sheet_no": {"type": "string"},
            "title": {"type": "string"},
            "revision": {"type": "string"},
            "sheet_type": {"type": "string", "enum": ["plan", "long_section", "schedule", "detail", "cover", "notes", "other"]},
            "items": {"type": "array", "items": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "enum": categories},
                    "description": {"type": "string"},
                    "unit": {"type": "string", "enum": CIVIL_UNITS},
                    "quantity": {"type": "number"},
                    "basis": {"type": "string"},
                    "confidence": {"type": "number", "description": "0 to 1"},
                    "needs_measuring": {"type": "boolean"},
                },
                "required": ["category", "description", "unit", "quantity", "basis", "confidence", "needs_measuring"],
                "additionalProperties": False,
            }},
        },
        "required": ["sheet_no", "title", "revision", "sheet_type", "items"],
        "additionalProperties": False,
    }


def _consolidate_schema() -> dict:
    return {
        "type": "object",
        "properties": {"groups": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "item_ids": {"type": "array", "items": {"type": "integer"}},
                "description": {"type": "string"},
                "category": {"type": "string"},
                "unit": {"type": "string", "enum": CIVIL_UNITS},
                "combine": {"type": "string", "enum": ["sum", "max"]},
                "reason": {"type": "string"},
            },
            "required": ["item_ids", "description", "category", "unit", "combine", "reason"],
            "additionalProperties": False,
        }}},
        "required": ["groups"],
        "additionalProperties": False,
    }


def _match_schema() -> dict:
    return {
        "type": "object",
        "properties": {"matches": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "line_id": {"type": "integer"},
                "rate_ids": {"type": "array", "items": {"type": "integer"}},
                "reason": {"type": "string"},
            },
            "required": ["line_id", "rate_ids", "reason"],
            "additionalProperties": False,
        }}},
        "required": ["matches"],
        "additionalProperties": False,
    }


PROMPT = """This is one sheet from a set of construction drawings that a commercial plumbing estimator in \
Queensland, Australia is pricing. Read it and fill in the fields.

Service codes: {services}.
Countable items: {counts}.

Read the sheet number, title, revision and scale from the title block (usually bottom right). \
For services, list only those the sheet actually draws, judging by the title, notes, legend and line work. \
If there is a legend, transcribe its hydraulic entries and map each to a service code and/or countable item where one clearly fits. \
List any short text tags the drawing prints beside each instance of a countable item (for example FW, IO, HR). \
The text layer extracted from the PDF is below; it may be empty for scanned sheets.

<pdf_text>
{text}
</pdf_text>"""

STYLE_PROMPT = """This is a hydraulic services drawing. The PDF's vector line work has been grouped into \
line styles (colour, dash pattern, line width, CAD layer). For each style that draws a pipe, say which \
service, nominal size (DN, mm) and material it is, using the legend, the layer name, the colours and any \
pipe labels on the sheet. Leave out styles that are not pipes (walls, grids, text, dimensions, hatching, \
title block, fixtures) and styles you can't place with reasonable confidence.

Service codes: {services}.
Materials: {materials}.

Legend read from this sheet:
{legend}

Line styles (longest first):
{styles}"""

CIVIL_PROMPT = """This is one sheet from a set of civil engineering drawings (stormwater, sewer, water, roads, \
earthworks and so on) for a project in Queensland, Australia. A civil estimator needs a bill of quantities.

List every measurable item of work this sheet gives a quantity for. Read quantities from schedules and \
tables (pit and pipe schedules, earthworks summaries, pavement areas), from long sections (pipe lengths \
between pits, pipe sizes and classes) and from labels on the plan (for example "45.2 m of 375 RCP"). \
Include pipe size, class and material, pit type and size, pavement make-up and depth ranges in the description.

Rules:
- Only report quantities written on the sheet, or simple sums of them (state the sum in basis). Never estimate.
- If the sheet clearly shows an item but gives no quantity, include it with quantity 0 and needs_measuring true.
- Use the units m, m2, m3, ea, t or item.
- basis says where the number came from, e.g. "Pit schedule, pits SW1-SW6" or "Long section CH 0-120".
- Cover sheets, notes-only sheets and details with no quantities have no items.

Categories: {categories}.

The text layer extracted from the PDF is below; it may be empty for scanned sheets.

<pdf_text>
{text}
</pdf_text>"""

CONSOLIDATE_PROMPT = """These quantities were read, sheet by sheet, from one set of civil drawings. The same work \
often appears on several sheets (a pipe on the plan and again on its long section; a pit on the plan and in \
the pit schedule). Group the items into bill-of-quantities lines.

- Put items in one group only when they are the same physical work in the same units.
- combine is "max" when the items are the same quantity shown on different sheets (count it once), and \
"sum" when they are separate parts of the job that add up (for example pipe runs on different plan sheets).
- Every item id must be in exactly one group. A one-item group is fine.
- description is a clear bill-of-quantities description for the line.

Items:
{items}"""

MATCH_PROMPT = """Each line below is a civil bill-of-quantities item, with candidate rates taken from the \
estimator's previous jobs. For each line, pick the candidates that are for the same work (same item, size, \
class or depth range near enough to price it the same way, and the same unit). Pick none if no candidate \
is a fair match.

Lines:
{lines}"""

MAX_IMAGE_PX = 2000  # long side sent to the model; title blocks stay legible at this size


def _downscale_png(png: bytes, max_px: int = MAX_IMAGE_PX) -> bytes:
    import pymupdf

    pix = pymupdf.Pixmap(png)
    long_side = max(pix.width, pix.height)
    if long_side <= max_px:
        return png
    # Shrink by halving (fast, keeps line work readable), then let the API do the rest.
    while max(pix.width, pix.height) > max_px * 1.5:
        pix.shrink(1)
    return pix.tobytes("png")


class ClaudeSheetReader:
    """Reads sheets with Claude (vision + structured output). Also does the autopilot's other
    AI steps: naming line styles, reading civil drawings and matching civil rates."""

    name = "claude"

    def __init__(self, model: str | None = None):
        import anthropic

        self.anthropic = anthropic
        self.client = anthropic.Anthropic()
        self.model = model or os.environ.get("TAKEOFF_AI_MODEL", "claude-opus-5-5")

    def _call(self, content: list, schema: dict, effort: str = "low", max_tokens: int = 16000) -> tuple[dict, str]:
        try:
            response = self.client.beta.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                # Server-side fallback: if a request is declined, the API retries it on a suitable model.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
                messages=[{"role": "user", "content": content}],
            )
        except self.anthropic.AuthenticationError as e:
            raise AIUnavailable("The AI service rejected the credentials. Check ANTHROPIC_API_KEY.") from e
        except self.anthropic.RateLimitError as e:
            raise AIUnavailable("The AI service is rate limiting requests. Try again shortly.") from e
        except self.anthropic.APIStatusError as e:
            raise AIUnavailable(f"The AI service returned an error ({e.status_code}).") from e
        except self.anthropic.APIConnectionError as e:
            raise AIUnavailable("Couldn't reach the AI service.") from e
        except self.anthropic.AnthropicError as e:  # e.g. no credentials configured
            raise AIUnavailable(f"The AI service isn't set up correctly: {e}. Check ANTHROPIC_API_KEY (credentials).") from e

        if response.stop_reason == "refusal":
            raise AIUnavailable("The AI service declined to read this sheet.")
        if response.stop_reason == "max_tokens":
            raise AIUnavailable("The AI response was cut off.")
        text = next((b.text for b in response.content if b.type == "text"), "")
        return json.loads(text), response.model

    @staticmethod
    def _image(png: bytes) -> dict:
        data = base64.standard_b64encode(_downscale_png(png)).decode()
        return {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": data}}

    def read_sheet(self, page_png, page_text, service_codes, count_types):
        data, model = self._call([
            self._image(page_png),
            {"type": "text", "text": PROMPT.format(services=", ".join(service_codes), counts=", ".join(count_types),
                                                   text=(page_text or "")[:12000])},
        ], _schema(service_codes, count_types))
        return SheetReading(
            sheet_no=data["sheet_no"].strip(), title=data["title"].strip(), revision=data["revision"].strip(),
            scale_text=data["scale_text"].strip(), sheet_type=data["sheet_type"],
            services=[s for s in data["services"] if s in service_codes], is_hydraulic=data["is_hydraulic"],
            confidence=max(0.0, min(1.0, float(data["confidence"]))),
            legend=[LegendEntry(**e) for e in data["legend"]],
            count_tags=[CountTag(**t) for t in data.get("count_tags", []) if t.get("tag", "").strip()],
            model=model,
        )

    def map_styles(self, page_png, legend, styles, service_codes, materials):
        data, _ = self._call([
            self._image(page_png),
            {"type": "text", "text": STYLE_PROMPT.format(
                services=", ".join(service_codes), materials=", ".join(materials),
                legend=json.dumps(legend, indent=1), styles=json.dumps(styles, indent=1))},
        ], _style_schema([s["key"] for s in styles], service_codes, materials))
        out = []
        for a in data["assignments"]:
            if a["service_code"] in service_codes and a["material"] in materials and a["dn"] > 0:
                out.append(StyleAssignment(key=a["key"], service_code=a["service_code"], dn=int(a["dn"]),
                                           material=a["material"], confidence=max(0.0, min(1.0, float(a["confidence"])))))
        return out

    def read_civil_sheet(self, page_png, page_text, categories):
        data, model = self._call([
            self._image(page_png),
            {"type": "text", "text": CIVIL_PROMPT.format(categories=", ".join(categories), text=(page_text or "")[:30000])},
        ], _civil_schema(categories), effort="medium")
        return CivilReading(
            sheet_no=data["sheet_no"].strip(), title=data["title"].strip(), revision=data["revision"].strip(),
            sheet_type=data["sheet_type"],
            items=[CivilTakeoff(**{**i, "quantity": max(0.0, float(i["quantity"])),
                                   "confidence": max(0.0, min(1.0, float(i["confidence"])))}) for i in data["items"]],
            model=model,
        )

    def consolidate_civil(self, items):
        data, _ = self._call([{"type": "text", "text": CONSOLIDATE_PROMPT.format(items=json.dumps(items, indent=1))}],
                             _consolidate_schema(), effort="medium")
        return [CivilGroup(**g) for g in data["groups"]]

    def match_civil_rates(self, lines):
        data, _ = self._call([{"type": "text", "text": MATCH_PROMPT.format(lines=json.dumps(lines, indent=1))}],
                             _match_schema())
        return {m["line_id"]: (m["rate_ids"], m["reason"]) for m in data["matches"]}


_override: SheetReader | None = None


def set_reader(reader: SheetReader | None) -> None:
    """For tests and for plugging in another provider."""
    global _override
    _override = reader


def get_reader() -> SheetReader | None:
    if _override is not None:
        return _override
    if os.environ.get("TAKEOFF_AI", "").lower() == "claude":
        if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
            log.warning("TAKEOFF_AI=claude is set but ANTHROPIC_API_KEY is empty, so AI reading is off.")
            return None
        try:
            return ClaudeSheetReader()
        except Exception as e:  # SDK missing or no credentials configured
            log.warning("AI sheet reading is switched on but unavailable: %s", e)
    return None


def ai_status() -> dict:
    r = get_reader()
    return {"enabled": r is not None, "provider": getattr(r, "name", None),
            "model": getattr(r, "model", None)}
