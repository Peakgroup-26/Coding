"""Phase 4: AI assistance. No real API calls: the AI reader is swapped for a fake, and the Claude
reader's response handling is tested against a mocked SDK response."""
import json
from types import SimpleNamespace

import pymupdf
import pytest

from app import ai
from app.ai import AIUnavailable, ClaudeSheetReader, LegendEntry, SheetReading

from .conftest import make_sheet_page, mm
from .helpers import calibrate, new_job, settings

BROWN = (0.55, 0.27, 0.07)


def _drawing_pdf() -> bytes:
    doc = pymupdf.open()
    page = make_sheet_page(doc, "H-990", "SANITARY DRAINAGE AND WATER PLAN")
    # Drainage main drawn as two exploded segments with one 90° corner (10 m + 5 m), plus a 3 m branch.
    for a, b in [((100, 300), (200, 300)), ((200, 300), (200, 350)), ((150, 330), (150, 300))]:
        page.draw_line((mm(a[0]), mm(a[1])), (mm(b[0]), mm(b[1])), color=BROWN, width=2)
    # Cold water drawn as exploded dashes: 10 mm pieces with 1 mm gaps, 100 mm long overall.
    for i in range(10):
        x0 = 100 + i * 10
        page.draw_line((mm(x0), mm(400)), (mm(x0 + 9), mm(400)), color=(0, 0, 1), width=0.5)
    # Five WC symbols and one different symbol
    for cx in (300, 340, 380, 420, 460):
        c = pymupdf.Point(mm(cx), mm(200))
        page.draw_rect(pymupdf.Rect(c.x - 9, c.y - 12, c.x + 9, c.y + 12), color=(0, 0, 0), width=1)
        page.draw_circle(c + (0, 4), 5, color=(0, 0, 0), width=1)
    tri = [pymupdf.Point(mm(500), mm(190)), pymupdf.Point(mm(510), mm(210)), pymupdf.Point(mm(490), mm(210))]
    page.draw_polyline(tri + [tri[0]], color=(0, 0, 0), width=1)
    data = doc.tobytes()
    doc.close()
    return data


@pytest.fixture(scope="module")
def sheet_job(client):
    job = new_job(client, name="AI job", client="Consultant X")
    r = client.post(f"/api/jobs/{job['id']}/files", files=[("files", ("ai.pdf", _drawing_pdf(), "application/pdf"))])
    sheet = r.json()[0]
    calibrate(client, sheet["id"])
    return job, sheet


class FakeReader:
    name = "fake"
    model = "fake-model"

    def __init__(self):
        self.calls = 0

    def read_sheet(self, page_png, page_text, service_codes, count_types):
        self.calls += 1
        assert page_png[:4] == b"\x89PNG" and "SAN" in service_codes and "WC" in count_types
        return SheetReading(sheet_no="H-990", title="Sanitary drainage plan - ground", revision="B", scale_text="1:100 @ A1",
                            sheet_type="plan", services=["SAN", "CW"], is_hydraulic=True, confidence=0.93,
                            legend=[LegendEntry("Brown solid line: sanitary drain", "", "SAN")], model="fake-model")


def test_ai_off_by_default(client, sheet_job):
    _, sheet = sheet_job
    assert client.get("/api/ai/status").json()["enabled"] is False
    assert client.post(f"/api/sheets/{sheet['id']}/ai-read").status_code == 409


def test_ai_reading_applies_to_unconfirmed_sheets_and_accuracy(client, sheet_job):
    job, sheet = sheet_job
    fake = FakeReader()
    ai.set_reader(fake)
    try:
        r = client.post(f"/api/jobs/{job['id']}/ai-read").json()
        assert r == {"read": 1, "errors": []}
        s = client.get(f"/api/sheets/{sheet['id']}").json()
        assert s["revision"] == "B" and s["services_shown"] == ["SAN", "CW"] and s["proposed"]["source"] == "ai"
        assert s["ai_reading"]["legend"][0]["service_code"] == "SAN"
        # A confirmed sheet is never overwritten
        client.patch(f"/api/sheets/{sheet['id']}", json={"confirmed": True, "revision": "A"})
        assert client.post(f"/api/sheets/{sheet['id']}/ai-read").json()["applied"] is False
        assert client.get(f"/api/sheets/{sheet['id']}").json()["revision"] == "A"
    finally:
        ai.set_reader(None)
    # The user confirmed what the AI proposed, so it scores as correct
    acc = client.get(f"/api/jobs/{job['id']}/ai-stats").json()["classification"]
    assert acc["sheets_confirmed"] == 1 and acc["both_correct_pct"] == 100 and acc["by_source"]["ai"]["sheets"] == 1


def test_classification_accuracy_counts_corrections(client):
    job = new_job(client, name="Accuracy job")
    from .helpers import upload
    sheets = upload(client, job["id"], [{"sheet_no": f"H-{i}", "title": "SANITARY DRAINAGE PLAN"} for i in range(4)])
    for s in sheets[:3]:
        client.patch(f"/api/sheets/{s['id']}", json={"confirmed": True})
    client.patch(f"/api/sheets/{sheets[3]['id']}", json={"confirmed": True, "classification": "detail"})
    acc = client.get(f"/api/jobs/{job['id']}/ai-stats").json()["classification"]
    assert acc["sheets_confirmed"] == 4 and acc["type_correct_pct"] == 75


def test_line_styles_and_run_suggestions(client, sheet_job):
    job, sheet = sheet_job
    services, _ = settings(client)
    styles = client.get(f"/api/sheets/{sheet['id']}/line-styles").json()["styles"]
    brown = next(s for s in styles if s["colour"] == "#8c4512")
    assert brown["length_m"] == pytest.approx(18, abs=0.05)
    blue_dashes = next(s for s in styles if s["colour"] == "#0000ff" and s["width"] == 0.5)

    r = client.post(f"/api/sheets/{sheet['id']}/suggest-runs", json={"styles": [
        {"key": brown["key"], "service_id": services["SAN"]["id"], "dn": 100, "material": "PVC DWV"},
        {"key": blue_dashes["key"], "service_id": services["CW"]["id"], "dn": 20, "material": "Copper"}]}).json()
    assert r["created"] == 3, r
    runs = [x for x in client.get(f"/api/sheets/{sheet['id']}/runs").json() if x["source"] == "ai"]
    assert all(x["status"] == "suggested" for x in runs)
    san = sorted((x for x in runs if x["service_id"] == services["SAN"]["id"]), key=lambda x: -x["length_m"])
    assert san[0]["length_m"] == pytest.approx(15, abs=0.05) and len(san[0]["geometry"]) == 3  # one bend
    assert san[1]["length_m"] == pytest.approx(3, abs=0.05)
    cw = next(x for x in runs if x["service_id"] == services["CW"]["id"])
    assert cw["length_m"] == pytest.approx(9.9, abs=0.15) and len(cw["geometry"]) == 2  # dashes bridged into one run

    # Mappings were remembered for this client: re-running with no styles uses them, and skips what's already there
    again = client.post(f"/api/sheets/{sheet['id']}/suggest-runs", json={}).json()
    assert again["created"] == 0 and again["skipped_overlapping"] == 3
    assert next(s for s in client.get(f"/api/sheets/{sheet['id']}/line-styles").json()["styles"] if s["key"] == brown["key"])["mapping"]["dn"] == 100


def test_symbol_matching(client, sheet_job):
    _, sheet = sheet_job
    services, _ = settings(client)
    ex = client.post(f"/api/sheets/{sheet['id']}/counts", json={"service_id": services["SAN"]["id"], "item_type": "WC",
                                                                 "x": mm(300), "y": mm(200)}).json()
    r = client.post(f"/api/sheets/{sheet['id']}/suggest-counts", json={"count_id": ex["id"], "box_pt": 34})
    assert r.status_code == 200, r.text
    assert r.json()["created"] == 4
    found = [c for c in client.get(f"/api/sheets/{sheet['id']}/counts").json() if c["source"] == "ai"]
    xs = sorted(round(c["x"] / mm(1)) for c in found)
    assert xs == [340, 380, 420, 460]  # not the triangle at 500
    assert all(c["status"] == "suggested" for c in found)
    # Nothing to match on blank paper
    assert client.post(f"/api/sheets/{sheet['id']}/suggest-counts", json={"x": mm(600), "y": mm(50), "item_type": "WC",
                                                                         "service_id": services["SAN"]["id"]}).status_code == 422


def test_suggestions_stay_out_of_pricing_until_confirmed_and_stats(client, sheet_job):
    job, sheet = sheet_job
    jid = job["id"]
    services, _ = settings(client)
    book = client.post("/api/price-books", json={"label": "AI test prices"}).json()
    client.put(f"/api/price-books/{book['id']}/items", json={"code": "P100", "description": "pipe", "uom": "m", "cost": 10})
    client.put(f"/api/price-books/{book['id']}/items", json={"code": "WCX", "description": "wc", "cost": 100})
    client.post("/api/mappings", json={"source_kind": "pipe", "service_code": "SAN", "material": "PVC DWV", "dn": 100, "target_kind": "item", "target_code": "P100"})
    client.post("/api/mappings", json={"source_kind": "count", "item_type": "WC", "target_kind": "item", "target_code": "WCX"})
    client.put(f"/api/jobs/{jid}/pricing-settings", json={"price_book_version_id": book["id"]})

    def priced():
        p = client.get(f"/api/jobs/{jid}/pricing").json()
        return {l["kind"]: l["qty"] for l in p["lines"]}

    # Only the hand-placed WC is priced; no suggested runs at all
    assert priced() == {"count": 1}
    assert client.get(f"/api/jobs/{jid}/totals").json()["excluded"]["suggested_runs"] == 3

    runs = sorted((x for x in client.get(f"/api/sheets/{sheet['id']}/runs").json() if x["source"] == "ai"), key=lambda x: -x["length_m"])
    san_main, cw, san_branch = runs[0], next(r for r in runs if r["service_id"] == services["CW"]["id"]), runs[-1]
    client.patch(f"/api/runs/{san_main['id']}", json={"status": "confirmed"})  # accepted as is
    client.patch(f"/api/runs/{san_branch['id']}", json={"dn": 100, "location_tag": "WC branch"})  # edited...
    client.patch(f"/api/runs/{san_branch['id']}", json={"status": "confirmed"})  # ...then accepted
    client.delete(f"/api/runs/{cw['id']}")  # rejected
    assert priced()["pipe"] == pytest.approx(18, abs=0.1)

    r = client.post(f"/api/sheets/{sheet['id']}/suggestions/reject", json={"kind": "count"}).json()
    assert r == {"rejected": 4}
    stats = client.get(f"/api/jobs/{jid}/ai-stats").json()["sheets"]
    row = next(s for s in stats if s["sheet_id"] == sheet["id"])
    assert (row["accepted"], row["edited"], row["rejected"], row["pending"]) == (1, 1, 5, 0)


def test_claude_reader_parses_structured_output(monkeypatch):
    """The real reader, with the SDK call replaced: checks request shape and response handling."""
    reader = ClaudeSheetReader.__new__(ClaudeSheetReader)
    import anthropic
    reader.anthropic = anthropic
    reader.model = "claude-opus-5-5"
    sent = {}
    payload = {"sheet_no": "H-101", "title": "Ground floor drainage", "revision": "C", "scale_text": "1:100 @ A1",
               "sheet_type": "plan", "services": ["SAN", "XYZ"], "is_hydraulic": True, "confidence": 1.4,
               "legend": [{"description": "WC", "item_type": "WC", "service_code": "SAN"}]}

    def create(**kw):
        sent.update(kw)
        return SimpleNamespace(stop_reason="end_turn", model="claude-opus-5-5",
                               content=[SimpleNamespace(type="text", text=json.dumps(payload))])

    reader.client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=create)))
    png = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 50, 50), False).tobytes("png")
    out = reader.read_sheet(png, "text", ["SAN", "CW"], ["WC"])
    assert out.services == ["SAN"] and out.confidence == 1.0 and out.legend[0].item_type == "WC"
    assert sent["model"] == "claude-opus-5-5" and sent["fallbacks"] == "default"
    assert sent["output_config"]["format"]["type"] == "json_schema"
    assert sent["messages"][0]["content"][0]["type"] == "image"

    reader.client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(
        create=lambda **kw: SimpleNamespace(stop_reason="refusal", content=[], model="x"))))
    with pytest.raises(AIUnavailable):
        reader.read_sheet(png, "", ["SAN"], ["WC"])
