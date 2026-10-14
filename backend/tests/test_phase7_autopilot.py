"""Phase 7: drop the plans in. The autopilot reads, scales and takes off a set by itself, and
nothing it finds counts until a person approves it. No real AI calls: a fake reader stands in."""
import pymupdf
import pytest

from app import ai
from app.ai import LegendEntry, SheetReading, StyleAssignment
from app.autoscale import check_dimensions
from app.db import SessionLocal
from app.models import Sheet

from .conftest import make_sheet_page, mm

BROWN = (0.55, 0.27, 0.07)


def _dims(page, horizontal_text="10000", vertical_text="5000"):
    """Dimension strings beside make_sheet_page's 100 mm test line and 50 mm check line (10 m and 5 m at 1:100)."""
    page.insert_text((mm(140), mm(97)), horizontal_text, fontsize=9)
    page.insert_text((mm(97), mm(180)), vertical_text, fontsize=9, rotate=90)


def _plan_pdf(sheet_no="H-201", dims=True, tags=True) -> bytes:
    doc = pymupdf.open()
    page = make_sheet_page(doc, sheet_no, "SANITARY DRAINAGE PLAN GROUND FLOOR")
    if dims:
        _dims(page)
    # A sanitary drain: 10 m + 5 m with a 3 m branch, and a dashed cold water line.
    for a, b in [((100, 300), (200, 300)), ((200, 300), (200, 350)), ((150, 330), (150, 300))]:
        page.draw_line((mm(a[0]), mm(a[1])), (mm(b[0]), mm(b[1])), color=BROWN, width=2)
    page.draw_line((mm(100), mm(400)), (mm(200), mm(400)), color=(0, 0, 1), width=0.5, dashes="[3 2] 0")
    if tags:
        for x in (120, 160, 190):
            page.insert_text((mm(x), mm(295)), "FW", fontsize=7)
        page.insert_text((mm(300), mm(450)), "FW FLOOR WASTE", fontsize=7)  # a legend line, not an item
    data = doc.tobytes()
    doc.close()
    return data


class FakeReader:
    name = "fake"
    model = "fake-model"

    def __init__(self, with_styles=True):
        self.with_styles = with_styles
        self.style_calls = 0

    def read_sheet(self, page_png, page_text, service_codes, count_types):
        return SheetReading(sheet_no="H-201", title="Sanitary drainage plan - ground", revision="A", scale_text="1:100 @ A1",
                            sheet_type="plan", services=["SAN", "CW"], is_hydraulic=True, confidence=0.95,
                            legend=[LegendEntry("Brown: sanitary drain", "", "SAN")],
                            count_tags=[ai.CountTag("FW", "Floor waste")], model="fake-model")

    def map_styles(self, page_png, legend, styles, service_codes, materials):
        self.style_calls += 1
        brown = next(s["key"] for s in styles if s["colour"] == "#8c4512")
        blue = next(s["key"] for s in styles if s["colour"] == "#0000ff" and s["dashes"] != "solid")
        return [StyleAssignment(brown, "SAN", 100, "PVC DWV", 0.9),
                StyleAssignment(blue, "CW", 20, "Copper", 0.3)]  # too unsure: left out


@pytest.fixture
def reader():
    fake = FakeReader()
    ai.set_reader(fake)
    yield fake
    ai.set_reader(None)


def _quick_start(client, pdf, client_name="Hydraulic Consultants", kind="hydraulic", name="Autopilot job"):
    r = client.post("/api/quick-start", data={"kind": kind, "name": name, "client": client_name},
                    files=[("files", ("set.pdf", pdf, "application/pdf"))])
    assert r.status_code == 200, r.text
    return r.json()


def test_dimension_check_confirms_or_refuses_the_scale(client):
    job = client.post("/api/jobs", json={"name": "Dims"}).json()
    good = client.post(f"/api/jobs/{job['id']}/files", files=[("files", ("a.pdf", _plan_pdf(), "application/pdf"))]).json()[0]
    doc = pymupdf.open()
    page = make_sheet_page(doc, "H-202", "PLAN")
    _dims(page, horizontal_text="10400")  # 4% out: a sign the scale is wrong
    bad = client.post(f"/api/jobs/{job['id']}/files", files=[("files", ("b.pdf", doc.tobytes(), "application/pdf"))]).json()[0]
    with SessionLocal() as db:
        g, b = db.get(Sheet, good["id"]), db.get(Sheet, bad["id"])
        res = check_dimensions(g, g.stated_m_per_pt)
        assert res["ok"] and len(res["matches"]) == 2
        assert {m["known_m"] for m in res["matches"]} == {10.0, 5.0}
        # The same sheet at the wrong scale (as if it were 1:200) is not confirmed.
        assert not check_dimensions(g, g.stated_m_per_pt * 2)["ok"]
        res = check_dimensions(b, b.stated_m_per_pt)
        assert not res["ok"] and res["conflicts"] and "disagree" in res["reason"]


def test_autopilot_takes_off_a_plan_and_nothing_counts_until_approved(client, reader):
    job = _quick_start(client, _plan_pdf())
    st = client.get(f"/api/jobs/{job['id']}/autopilot").json()
    assert st["state"] == "done", st
    sheet = client.get(f"/api/jobs/{job['id']}/sheets").json()[0]
    assert sheet["sheet_no"] == "H-201" and sheet["classification"] == "plan"
    assert sheet["scale_verified"] and sheet["verification_data"]["method"] == "auto_dimensions"

    s = st["summary"]
    assert s["runs_suggested"] == 2 and s["runs_confirmed"] == 0  # the main (10 + 5 m) and the 3 m branch
    assert s["metres"] == pytest.approx(18.0, abs=0.1)
    assert s["counts_suggested"] == 3  # three FW tags; the legend's "FW FLOOR WASTE" isn't an item
    assert reader.style_calls == 1
    assert not [a for a in st["attention"] if a["kind"] in ("scale", "styles")]

    # Suggestions stay out of the totals.
    totals = client.get(f"/api/jobs/{job['id']}/totals").json()
    assert not totals["lines"] and totals["excluded"]["suggested_runs"] == 2 and totals["excluded"]["suggested_counts"] == 3

    r = client.post(f"/api/jobs/{job['id']}/approve-all")
    assert r.status_code == 200, r.text
    assert r.json()["runs"] == 2 and r.json()["counts"] == 3
    totals = client.get(f"/api/jobs/{job['id']}/totals").json()
    san = [l for l in totals["lines"] if l["service_code"] == "SAN"]
    assert sum(l["plan_m"] for l in san) == pytest.approx(18.0, abs=0.1)
    assert [c["qty"] for c in totals["counts"] if c["item_type"] == "Floor waste"] == [3]

    # The approved line colours are remembered for this client, so the next job doesn't need the AI to name them.
    job2 = _quick_start(client, _plan_pdf("H-301"), name="Second job")
    assert reader.style_calls == 1
    assert client.get(f"/api/jobs/{job2['id']}/autopilot").json()["summary"]["runs_suggested"] == 2


def test_autopilot_without_ai_or_dimensions_asks_for_help(client):
    job = _quick_start(client, _plan_pdf(dims=False, tags=False), client_name="Nobody", name="No AI")
    st = client.get(f"/api/jobs/{job['id']}/autopilot").json()
    assert st["state"] == "done"
    kinds = {a["kind"] for a in st["attention"]}
    assert "ai" in kinds and "scale" in kinds
    assert st["summary"]["runs_suggested"] == 0  # never measured on an unconfirmed scale
    sheet = client.get(f"/api/jobs/{job['id']}/sheets").json()[0]
    assert not sheet["scale_verified"] and sheet["calibrated_scale"]  # scale set from the title block, waiting for a check


def test_quick_start_rejects_non_pdfs(client):
    r = client.post("/api/quick-start", data={"kind": "hydraulic"}, files=[("files", ("notes.txt", b"hello", "text/plain"))])
    assert r.status_code == 422


def test_ai_switched_on_without_a_key_counts_as_off(monkeypatch):
    monkeypatch.setenv("TAKEOFF_AI", "claude")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    assert ai.get_reader() is None


def test_a_sheet_the_ai_trips_on_doesnt_stop_the_set(client):
    class Broken(FakeReader):
        def read_sheet(self, *a):
            raise ValueError("bad JSON")

    ai.set_reader(Broken())
    try:
        job = _quick_start(client, _plan_pdf(), client_name="Broken AI", name="Broken")
    finally:
        ai.set_reader(None)
    st = client.get(f"/api/jobs/{job['id']}/autopilot").json()
    assert st["state"] == "done" and any("ValueError" in a["message"] for a in st["attention"])
