"""PDF reports to download or share: ITPs, daily site pre-starts, plant pre-starts, SWMS (with the sign-on register),
incident reports, toolbox talks and filled-in job forms. Built with PyMuPDF's HTML layout (Story), in the Lorojo colours,
with signatures and photos embedded and "page x of y" on every page.
"""
import base64
import html
import io
from datetime import datetime, timezone
from pathlib import Path

import pymupdf as fitz
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import ops, storage
from .models import (Document, FormResponse, FormTemplate, Job, JobItp, JobSwms, Plant, PlantCheck, SafetyEvent, SitePrestart,
                     SwmsSignon, ToolboxTalk, User)
from .timesheets import local

LOGO = Path(__file__).resolve().parents[2] / "frontend" / "public" / "brand" / "lorojo-logo.png"
CSS = """
body { font-family: sans-serif; font-size: 8.5pt; color: #161616; }
.top { background-color: #0e0e0e; color: #ffffff; padding: 8px 10px; }
.top .t { font-size: 15pt; font-weight: bold; color: #ff6a13; margin: 4px 0 0 0; }
.top .s { color: #ffffff; margin: 2px 0 0 0; }
h2 { font-size: 11pt; color: #0e0e0e; border-bottom: 2px solid #ff6a13; padding-bottom: 2px; margin: 12px 0 6px 0; }
table { border-collapse: collapse; width: 100%; margin: 4px 0; }
th { background-color: #ffb27a; text-align: left; padding: 3px 4px; border: 1px solid #d9d2cc; font-size: 8pt; }
td { border: 1px solid #d9d2cc; padding: 3px 4px; vertical-align: top; }
.kv td.k { width: 150px; background-color: #faf8f6; font-weight: bold; }
.pass { color: #1f8a43; font-weight: bold; } .fail { color: #c42b2b; font-weight: bold; } .na { color: #6f6a66; }
.hold { color: #c42b2b; font-weight: bold; } .muted { color: #6f6a66; }
.E { background-color: #c42b2b; color: #fff; font-weight: bold; } .H { background-color: #ff6a13; color: #fff; font-weight: bold; }
.M { background-color: #ffd27a; font-weight: bold; } .L { background-color: #bfe5c9; font-weight: bold; }
.photo { margin: 4px; }
"""
RESULT = {"pass": "PASS", "fail": "FAIL", "na": "N/A"}


def e(v) -> str:
    return html.escape("" if v is None else str(v))


class Doc:
    """Collects HTML and images, then lays them out on A4 pages."""

    def __init__(self, title: str, subtitle: str = ""):
        self.title, self.subtitle = title, subtitle
        self.parts: list[str] = []
        self.arch = fitz.Archive()
        self.n = 0
        if LOGO.exists():
            pix = fitz.Pixmap(str(LOGO))
            while pix.width > 400:
                pix.shrink(1)
            self.arch.add(pix.tobytes("png"), "logo.png")

    def image(self, data: bytes, max_px: int = 700) -> str | None:
        try:
            pix = fitz.Pixmap(data)
        except Exception:  # noqa: BLE001 - not an image we can read: skip it
            return None
        if pix.alpha:
            pix = fitz.Pixmap(pix, 0) if pix.n > 3 else pix
        while pix.width > max_px:
            pix.shrink(1)
        if pix.colorspace and pix.colorspace.n not in (1, 3):
            pix = fitz.Pixmap(fitz.csRGB, pix)
        self.n += 1
        name = f"img{self.n}.png"
        self.arch.add(pix.tobytes("png"), name)
        return name

    def signature(self, data_url: str, width: int = 90) -> str:
        if not data_url or "," not in data_url:
            return ""
        try:
            name = self.image(base64.b64decode(data_url.split(",", 1)[1]), 400)
        except (ValueError, TypeError):
            return ""
        return f'<img src="{name}" width="{width}"/>' if name else ""

    def photos(self, db: Session, ids: list) -> str:
        out = []
        for i in ids or []:
            d = db.get(Document, int(i)) if str(i).isdigit() else None
            if d is None or not (d.mime or "").startswith("image/"):
                continue
            try:
                name = self.image(storage.read_bytes(d.path))
            except Exception:  # noqa: BLE001 - a missing file shouldn't stop the report
                name = None
            if name:
                out.append(f'<img class="photo" src="{name}" width="230"/>')
        return " ".join(out)

    def add(self, s: str) -> "Doc":
        self.parts.append(s)
        return self

    def kv(self, rows: list[tuple[str, object]]) -> "Doc":
        return self.add('<table class="kv">' + "".join(f'<tr><td class="k" width="150">{e(k)}</td><td>{v if isinstance(v, Raw) else e(v)}</td></tr>'
                                                       for k, v in rows) + "</table>")

    def render(self, db: Session) -> bytes:
        company = ops.settings(db)["company_name"]
        head = (f'<div class="top"><img src="logo.png" width="80"/><p class="t">{e(self.title)}</p>'
                f'<p class="s">{e(self.subtitle)}</p></div>')
        story = fitz.Story(html=head + "".join(self.parts), user_css=CSS, archive=self.arch)
        buf = io.BytesIO()
        w = fitz.DocumentWriter(buf)
        page = fitz.paper_rect("a4")
        where = page + (32, 32, -32, -40)
        more = 1
        while more:
            dev = w.begin_page(page)
            more, _ = story.place(where)
            story.draw(dev)
            w.end_page()
        w.close()
        doc = fitz.open("pdf", buf.getvalue())
        stamp = datetime.now(timezone.utc).astimezone().strftime("%d/%m/%Y %H:%M")
        for i, p in enumerate(doc):
            p.insert_text((32, p.rect.height - 20), f"{company} · {self.title} · made in Lorojo {stamp} · page {i + 1} of {doc.page_count}",
                          fontsize=7, color=(0.43, 0.42, 0.4))
        doc.set_metadata({"title": self.title, "author": company, "creator": "Lorojo"})
        return doc.tobytes(deflate=True)


class Raw(str):
    """Already-made HTML for a table cell."""


def _job_rows(db: Session, job: Job | None) -> list[tuple[str, object]]:
    if job is None:
        return []
    from .models import Customer, Site

    c = db.get(Customer, job.customer_id) if job.customer_id else None
    s = db.get(Site, job.site_id) if job.site_id else None
    return [("Job", f"{job.job_no or job.quote_no or ''} {job.name}".strip()), ("Customer", c.name if c else job.client),
            ("Site", (s.address if s else "") or job.address)]


def _names(db: Session) -> dict[int, str]:
    return {u.id: u.name or u.email for u in db.scalars(select(User))}


def _when(dt) -> str:
    return local(dt).strftime("%d/%m/%Y %H:%M") if dt else ""


# --- the reports ---
def itp_pdf(db: Session, ji: JobItp) -> bytes:
    from . import itp

    job = db.get(Job, ji.job_id)
    names = _names(db)
    d = Doc("Inspection and Test Plan", f"{ji.name}{' – ' + ji.area if ji.area else ''}")
    st = itp.state(db, ji)
    real = [s for s in st if s.get("frequency") != "daily"]
    d.kv(_job_rows(db, job) + [("ITP", f"{ji.name}{' – ' + ji.area if ji.area else ''}"),
                               ("Progress", f"{sum(1 for s in real if s['done'])} of {len(real)} items done · {'Complete' if ji.status == 'complete' else 'Open'}")])
    d.add("<h2>Items</h2><table><tr><th>#</th><th>Stage</th><th>Activity / check</th><th>Acceptance criteria</th><th>Point</th><th>Result</th><th>Reading</th><th>Date / by</th><th>Signed off</th></tr>")
    all_checks = itp.checks(db, ji)
    for n, s in enumerate(st, 1):
        last = next((c for c in reversed(all_checks) if c.item_key == s["key"]), None)
        res = f'<span class="{last.result}">{RESULT[last.result]}</span>' if last else '<span class="muted">–</span>'
        point = f'<span class="hold">{e(itp.POINTS.get(s.get("point"), ""))}</span>' if s.get("point") in ("hold", "witness") else e(itp.POINTS.get(s.get("point"), ""))
        sig = (f"{e(last.signed_name)}{' (' + e(last.signed_role) + ')' if last.signed_role else ''}<br/>{d.signature(last.signature, 70)}"
               if last and last.signed_name else "")
        d.add(f"<tr><td>{n}</td><td>{e(s.get('stage'))}</td><td><b>{e(s['activity'])}</b><br/><span class='muted'>{e(s.get('check'))} · "
              f"{e(itp.FREQUENCY.get(s.get('frequency'), ''))}</span></td><td>{e(s.get('criteria'))}</td><td>{point}</td><td>{res}</td>"
              f"<td>{e(last.reading) if last else ''}</td><td>{(last.day.strftime('%d/%m/%Y') + '<br/>' + e(names.get(last.user_id or 0, ''))) if last else ''}</td>"
              f"<td>{sig}</td></tr>")
    d.add("</table>")
    notes = [c for c in all_checks if c.notes or c.photos]
    if notes:
        d.add("<h2>Notes and photos</h2>")
        for c in notes:
            item = next((s for s in st if s["key"] == c.item_key), {"activity": c.item_key})
            d.add(f"<p><b>{e(item['activity'])}</b> – {c.day.strftime('%d/%m/%Y')} {e(names.get(c.user_id or 0, ''))}: "
                  f"<span class='{c.result}'>{RESULT[c.result]}</span> {e(c.notes)}</p><p>{d.photos(db, c.photos)}</p>")
    daily = [c for c in all_checks if next((s for s in st if s["key"] == c.item_key), {}).get("frequency") == "daily"]
    if daily:
        d.add("<h2>Daily checks log</h2><table><tr><th>Date</th><th>Check</th><th>Result</th><th>By</th><th>Notes</th></tr>")
        for c in daily:
            item = next((s for s in st if s["key"] == c.item_key), {"activity": c.item_key})
            d.add(f"<tr><td>{c.day.strftime('%d/%m/%Y')}</td><td>{e(item['activity'])}</td><td class='{c.result}'>{RESULT[c.result]}</td>"
                  f"<td>{e(names.get(c.user_id or 0, ''))}</td><td>{e(c.notes)}</td></tr>")
        d.add("</table>")
    return d.render(db)


def site_prestart_pdf(db: Session, sp: SitePrestart) -> bytes:
    from .safety import PRESTART_QUESTIONS

    job = db.get(Job, sp.job_id)
    names = _names(db)
    d = Doc("Daily site pre-start", f"{job.job_no or ''} {job.name} – {sp.day.strftime('%A %d/%m/%Y')}" if job else "")
    d.kv(_job_rows(db, job) + [("Date", sp.day.strftime("%A %d/%m/%Y")), ("Led by", names.get(sp.led_by or 0, ""))])
    d.add("<h2>Checks</h2>")
    d.kv([(q["label"], _answer(sp.answers.get(q["key"]))) for q in PRESTART_QUESTIONS])
    d.add(_attendees(d, sp.attendees))
    return d.render(db)


def _answer(v) -> str:
    if v is True:
        return "Yes"
    if v is False:
        return "No"
    if isinstance(v, list):
        return ", ".join(str(x) for x in v)
    return "" if v is None else str(v)


def _attendees(d: Doc, att: list) -> str:
    rows = "".join(f"<tr><td>{n}</td><td>{e(a.get('name'))}</td><td>{e(local(datetime.fromisoformat(a['signed_at'])).strftime('%d/%m/%Y %H:%M') if a.get('signed_at') else '')}</td>"
                   f"<td>{d.signature(a.get('signature', ''), 80)}</td></tr>" for n, a in enumerate(att or [], 1))
    return f"<h2>Signed on ({len(att or [])})</h2><table><tr><th>#</th><th>Name</th><th>When</th><th>Signature</th></tr>{rows}</table>"


def plant_check_pdf(db: Session, pc: PlantCheck) -> bytes:
    p = db.get(Plant, pc.plant_id)
    names = _names(db)
    kind = {"prestart": "Daily pre-start", "start_day": "Start of day", "end_day": "End of day", "weekly": "Weekly vehicle pre-start",
            "wash": "Monthly wash", "service": "Service"}.get(pc.kind, pc.kind)
    d = Doc(f"Plant {kind.lower()}", f"{p.name if p else ''}{' – ' + p.rego if p and p.rego else ''} – {_when(pc.at)}")
    job = db.get(Job, pc.job_id) if pc.job_id else None
    d.kv([("Machine / vehicle", f"{p.name} {p.fleet_no}".strip() if p else ""), ("Rego / serial", f"{p.rego if p else ''} {p.serial if p else ''}".strip()),
          ("Check", kind), ("When", _when(pc.at)), ("By", names.get(pc.user_id or 0, "")), ("Result", Raw('<span class="pass">PASSED</span>' if pc.passed else '<span class="fail">FAILED – see notes</span>')),
          ("Hours", pc.hours if pc.hours is not None else ""), ("Odometer (km)", pc.odometer if pc.odometer is not None else ""),
          ("Fuel", f"{pc.fuel_pct:.0f}%" if pc.fuel_pct is not None else "")] + (_job_rows(db, job)[:1] if job else []))
    labels = {}
    if p and p.checklist_id:
        t = db.get(FormTemplate, p.checklist_id)
        labels = {f["key"]: f["label"] for f in (t.fields if t else [])}
    if pc.answers:
        d.add("<h2>Checklist</h2>")
        d.kv([(labels.get(k, k.replace("_", " ").capitalize()), _answer(v)) for k, v in pc.answers.items() if not str(v).startswith("data:")])
    if pc.notes:
        d.add(f"<h2>Notes</h2><p>{e(pc.notes)}</p>")
    ph = d.photos(db, list((pc.photo_ids or {}).values()))
    if ph:
        d.add(f"<h2>Photos</h2><p>{ph}</p>")
    return d.render(db)


def swms_pdf(db: Session, js: JobSwms) -> bytes:
    job = db.get(Job, js.job_id)
    d = Doc("Safe Work Method Statement", f"{js.title} – v{js.version}")
    d.kv(_job_rows(db, job) + [("Activity", js.activity), ("High risk construction work", ", ".join(js.high_risk or []) or "None"),
                               ("PPE", ", ".join(js.ppe or [])), ("Site-specific notes", js.site_notes or "–")])
    d.add("<h2>Steps, hazards and controls</h2><table><tr><th>#</th><th>Step</th><th>Hazards</th><th>Risk</th><th>Controls</th><th>Risk after</th><th>Who</th></tr>")
    for n, s in enumerate(js.steps or [], 1):
        d.add(f"<tr><td>{n}</td><td><b>{e(s.get('step'))}</b></td><td>{e(s.get('hazards'))}</td><td class='{e(s.get('risk_before'))}'>{e(s.get('risk_before'))}</td>"
              f"<td>{e(s.get('controls'))}</td><td class='{e(s.get('risk_after'))}'>{e(s.get('risk_after'))}</td><td>{e(s.get('who'))}</td></tr>")
    d.add("</table><p class='muted'>Risk: E extreme, H high, M medium, L low.</p>")
    signs = list(db.scalars(select(SwmsSignon).where(SwmsSignon.job_swms_id == js.id, SwmsSignon.version == js.version).order_by(SwmsSignon.signed_at)))
    d.add(_attendees(d, [{"name": s.typed_name, "signed_at": s.signed_at.isoformat(), "signature": s.signature} for s in signs]))
    return d.render(db)


def event_pdf(db: Session, ev: SafetyEvent) -> bytes:
    from . import safety

    names = _names(db)
    out = safety.event_out(db, ev, names)
    d = Doc(f"{out['kind_label']} report", f"{ev.title} – {_when(ev.occurred_at)}")
    d.kv(_job_rows(db, db.get(Job, ev.job_id) if ev.job_id else None) + [
        ("What", out["kind_label"]), ("When", _when(ev.occurred_at)), ("Where", ev.location), ("Reported by", out["reported_by"]),
        ("Severity", ev.severity.title()), ("Treatment", out["treatment_label"]), ("People involved", ev.people),
        ("Notifiable to WHSQ", "Yes" if ev.notifiable else "No"), ("Status", ev.status.title())])
    d.add(f"<h2>What happened</h2><p>{e(ev.description)}</p><h2>Immediate action</h2><p>{e(ev.immediate_action) or '–'}</p>")
    if ev.root_cause:
        d.add(f"<h2>Root cause</h2><p>{e(ev.root_cause)}</p>")
    if out["actions"]:
        d.add("<h2>Corrective actions</h2><table><tr><th>Action</th><th>Who</th><th>Due</th><th>Status</th></tr>" + "".join(
            f"<tr><td>{e(a['description'])}</td><td>{e(a['assignee'])}</td><td>{e(a['due'])}</td><td>{e(a['status'])}</td></tr>" for a in out["actions"]) + "</table>")
    ph = d.photos(db, ev.photos)
    if ph:
        d.add(f"<h2>Photos</h2><p>{ph}</p>")
    return d.render(db)


def toolbox_pdf(db: Session, tb: ToolboxTalk) -> bytes:
    names = _names(db)
    d = Doc("Toolbox talk", f"{tb.topic} – {tb.day.strftime('%d/%m/%Y')}")
    d.kv(_job_rows(db, db.get(Job, tb.job_id) if tb.job_id else None) + [("Topic", tb.topic), ("Date", tb.day.strftime("%A %d/%m/%Y")),
                                                                         ("Presented by", names.get(tb.presenter_id or 0, ""))])
    d.add(f"<h2>What was covered</h2><p>{e(tb.notes) or '–'}</p>")
    d.add(_attendees(d, tb.attendees))
    return d.render(db)


def form_pdf(db: Session, r: FormResponse) -> bytes:
    t = db.get(FormTemplate, r.template_id)
    names = _names(db)
    d = Doc(t.name if t else "Form", _when(r.created_at))
    d.kv(_job_rows(db, db.get(Job, r.job_id) if r.job_id else None) + [("Filled in by", names.get(r.user_id or 0, "")), ("When", _when(r.created_at))])
    rows = []
    for f in (t.fields if t else []):
        v = (r.answers or {}).get(f["key"])
        if f["type"] == "heading":
            continue
        if f["type"] == "signature":
            rows.append((f["label"], Raw(d.signature(v or "", 120))))
        elif f["type"] == "photo":
            rows.append((f["label"], Raw(d.photos(db, [v] if v else []))))
        else:
            rows.append((f["label"], _answer(v)))
    d.kv(rows)
    return d.render(db)


def filename(kind: str, label: str) -> str:
    safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in label).strip().replace(" ", "-")[:80]
    return f"{kind}-{safe or 'report'}.pdf"

