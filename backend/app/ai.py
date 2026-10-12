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
    model: str = ""


class AIUnavailable(Exception):
    pass


class SheetReader(Protocol):
    name: str

    def read_sheet(self, page_png: bytes, page_text: str, service_codes: list[str], count_types: list[str]) -> SheetReading: ...


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
        },
        "required": ["sheet_no", "title", "revision", "scale_text", "sheet_type", "services", "is_hydraulic", "confidence", "legend"],
        "additionalProperties": False,
    }


PROMPT = """This is one sheet from a set of construction drawings that a commercial plumbing estimator in \
Queensland, Australia is pricing. Read it and fill in the fields.

Service codes: {services}.
Countable items: {counts}.

Read the sheet number, title, revision and scale from the title block (usually bottom right). \
For services, list only those the sheet actually draws, judging by the title, notes, legend and line work. \
If there is a legend, transcribe its hydraulic entries and map each to a service code and/or countable item where one clearly fits. \
The text layer extracted from the PDF is below; it may be empty for scanned sheets.

<pdf_text>
{text}
</pdf_text>"""

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
    """Reads a sheet with Claude (vision + structured output)."""

    name = "claude"

    def __init__(self, model: str | None = None):
        import anthropic

        self.anthropic = anthropic
        self.client = anthropic.Anthropic()
        self.model = model or os.environ.get("TAKEOFF_AI_MODEL", "claude-opus-5-5")

    def read_sheet(self, page_png, page_text, service_codes, count_types):
        image = base64.standard_b64encode(_downscale_png(page_png)).decode()
        try:
            response = self.client.beta.messages.create(
                model=self.model,
                max_tokens=16000,
                # Server-side fallback: if a request is declined, the API retries it on a suitable model.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                output_config={"effort": "low", "format": {"type": "json_schema", "schema": _schema(service_codes, count_types)}},
                messages=[{"role": "user", "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": image}},
                    {"type": "text", "text": PROMPT.format(services=", ".join(service_codes), counts=", ".join(count_types),
                                                           text=(page_text or "")[:12000])},
                ]}],
            )
        except self.anthropic.AuthenticationError as e:
            raise AIUnavailable("The AI service rejected the credentials. Check ANTHROPIC_API_KEY.") from e
        except self.anthropic.RateLimitError as e:
            raise AIUnavailable("The AI service is rate limiting requests. Try again shortly.") from e
        except self.anthropic.APIStatusError as e:
            raise AIUnavailable(f"The AI service returned an error ({e.status_code}).") from e
        except self.anthropic.APIConnectionError as e:
            raise AIUnavailable("Couldn't reach the AI service.") from e

        if response.stop_reason == "refusal":
            raise AIUnavailable("The AI service declined to read this sheet.")
        if response.stop_reason == "max_tokens":
            raise AIUnavailable("The AI response was cut off.")
        text = next((b.text for b in response.content if b.type == "text"), "")
        data = json.loads(text)
        return SheetReading(
            sheet_no=data["sheet_no"].strip(), title=data["title"].strip(), revision=data["revision"].strip(),
            scale_text=data["scale_text"].strip(), sheet_type=data["sheet_type"],
            services=[s for s in data["services"] if s in service_codes], is_hydraulic=data["is_hydraulic"],
            confidence=max(0.0, min(1.0, float(data["confidence"]))),
            legend=[LegendEntry(**e) for e in data["legend"]], model=response.model,
        )


_override: SheetReader | None = None


def set_reader(reader: SheetReader | None) -> None:
    """For tests and for plugging in another provider."""
    global _override
    _override = reader


def get_reader() -> SheetReader | None:
    if _override is not None:
        return _override
    if os.environ.get("TAKEOFF_AI", "").lower() == "claude":
        try:
            return ClaudeSheetReader()
        except Exception as e:  # SDK missing or no credentials configured
            log.warning("AI sheet reading is switched on but unavailable: %s", e)
    return None


def ai_status() -> dict:
    r = get_reader()
    return {"enabled": r is not None, "provider": getattr(r, "name", None),
            "model": getattr(r, "model", None)}
