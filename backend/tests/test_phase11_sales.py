"""Phase 11: residential / commercial / maintenance sectors, leads, and the sales dashboard."""
from datetime import date, timedelta

import pytest

from app import ai, sales
from app.models import Job

from .test_phase7_autopilot import FakeReader, _plan_pdf


def test_sectors_leads_and_stages(client):
    r = client.post("/api/leads", json={"name": "Smith bathroom", "sector": "residential", "client": "J Smith",
                                        "contact": "0400 000 000", "lead_source": "Website"})
    assert r.status_code == 200, r.text
    lead = r.json()
    year = date.today().year
    assert lead["quote_no"].startswith(f"RES-{year}-") and lead["sales_stage"] == "lead" and lead["lead_date"] == date.today().isoformat()
    second = client.post("/api/leads", json={"name": "Jones reno", "sector": "residential"}).json()
    assert int(second["quote_no"][-4:]) == int(lead["quote_no"][-4:]) + 1
    maint = client.post("/api/leads", json={"name": "Body corp hot water", "sector": "maintenance"}).json()
    assert maint["quote_no"].startswith("MNT-")

    # Plans dropped on the lead: it becomes "quoting".
    ai.set_reader(FakeReader())
    try:
        client.post(f"/api/jobs/{lead['id']}/add-plans", files=[("files", ("p.pdf", _plan_pdf(), "application/pdf"))])
    finally:
        ai.set_reader(None)
    assert client.get(f"/api/jobs/{lead['id']}").json()["sales_stage"] == "quoting"

    # Quote sent, then won: dates fill in.
    j = client.put(f"/api/jobs/{lead['id']}/sales", json={"mark_quote_sent": True, "tender_value": 18500}).json()
    assert j["sales_stage"] == "quote_sent" and j["quote_sent_date"] == date.today().isoformat()
    j = client.put(f"/api/jobs/{lead['id']}/sales", json={"tender_result": "won"}).json()
    assert j["sales_stage"] == "won" and j["decided_date"] == date.today().isoformat()
    j = client.put(f"/api/jobs/{lead['id']}/sales", json={"tender_result": "pending"}).json()
    assert j["decided_date"] is None and j["sales_stage"] == "quote_sent"
    bad = client.put(f"/api/jobs/{lead['id']}/sales", json={"quote_sent_date": "2000-01-01"})
    assert bad.status_code == 422

    # Lists by sector; plans dropped in a sector tab land in that sector.
    assert {x["name"] for x in client.get("/api/jobs?sector=maintenance").json()} >= {"Body corp hot water"}
    assert not [x for x in client.get("/api/jobs?sector=residential").json() if x["sector"] != "residential"]
    r = client.post("/api/quick-start", data={"kind": "hydraulic", "sector": "maintenance", "name": "Pump room"},
                    files=[("files", ("p.pdf", _plan_pdf(), "application/pdf"))])
    assert r.json()["sector"] == "maintenance" and r.json()["quote_no"].startswith("MNT-")
    assert client.post("/api/quick-start", data={"kind": "hydraulic", "sector": "industrial"},
                       files=[("files", ("p.pdf", _plan_pdf(), "application/pdf"))]).status_code == 422

    # People can be limited to sectors.
    client.post("/api/users", json={"email": "resi@test.local", "password": "password-123", "sectors": ["residential"]})
    tok = client.post("/api/auth/login", json={"email": "resi@test.local", "password": "password-123"}).json()["token"]
    h = {"Authorization": f"Bearer {tok}"}
    seen = client.get("/api/jobs", headers=h).json()
    assert seen and {x["sector"] for x in seen} == {"residential"}
    assert client.get(f"/api/jobs/{maint['id']}", headers=h).status_code == 404
    assert client.post("/api/leads", json={"name": "x", "sector": "commercial"}, headers=h).status_code == 403
    assert [s["key"] for s in client.get("/api/sales/settings", headers=h).json()["sectors"]] == ["residential"]


def _job(i, sector, lead, sent=None, result="pending", decided=None, value=None, source="Website"):
    return Job(id=i, name=f"J{i}", sector=sector, kind="hydraulic", lead_date=lead, quote_sent_date=sent, tender_result=result,
               decided_date=decided, tender_value=value, lead_source=source, client="", contact="", quote_no="", status="draft")


def test_sales_maths():
    today = date(2026, 10, 15)
    d = lambda n: today - timedelta(days=n)  # noqa: E731
    jobs = [
        _job(1, "residential", d(40), d(30), "won", d(20), 10000, "Website"),     # lead->quote 10, quote->win 10, lead->win 20
        _job(2, "residential", d(35), d(31), "lost", d(25), 8000, "Website"),     # lead->quote 4
        _job(3, "commercial", d(20), d(14), "won", d(4), 50000, "Builder (repeat)"),  # 6, 10, 16
        _job(4, "commercial", d(10), d(5), value=30000, source="Builder (repeat)"),   # quote sent, waiting 5 days
        _job(5, "maintenance", d(3), source="Phone / walk-in"),                    # still a lead
        _job(6, "residential", date(2025, 1, 1), date(2025, 1, 5), "won", date(2025, 2, 1), 9999),  # before the period
    ]

    class FakeDb:
        def scalars(self, q):
            return []

        def scalar(self, q):
            return None

    out = sales.dashboard(FakeDb(), jobs, months=6, today=today)
    assert (out["leads"], out["quotes_sent"], out["won"], out["lost"]) == (5, 4, 2, 1)
    c = out["conversion"]
    assert c["lead_to_quote_pct"] == 80.0 and c["quote_to_win_pct"] == 50.0 and c["lead_to_win_pct"] == 40.0
    assert c["win_rate_decided_pct"] == pytest.approx(66.7)
    days = out["days"]
    assert days["lead_to_quote"]["average"] == pytest.approx((10 + 4 + 6 + 5) / 4, abs=0.05)  # shown to 1 dp
    assert days["quote_to_win"]["median"] == 10 and days["lead_to_win"]["average"] == 18
    assert out["value"]["won"] == 60000 and out["value"]["average_won"] == 30000 and out["value"]["open_quotes"] == 30000
    assert [q["name"] for q in out["open_quotes"]] == ["J4"] and out["open_quotes"][0]["days"] == 5
    assert [q["name"] for q in out["to_quote"]] == ["J5"]
    src = {s["name"]: s for s in out["by_source"]}
    assert src["Website"]["leads"] == 2 and src["Website"]["win_rate_pct"] == 50.0
    assert src["Builder (repeat)"]["quote_rate_pct"] == 100.0
    months = {m["month"]: m for m in out["monthly"]}
    assert months["2026-10"]["won"] == 1 and months["2026-09"]["won"] == 1 and months["2026-09"]["lost"] == 1
    assert out["pipeline"]["quote_sent"]["count"] == 1 and out["pipeline"]["lead"]["count"] == 1


def test_sales_dashboard_endpoint(client):
    out = client.get("/api/sales/dashboard?sector=residential&months=12").json()
    assert out["leads"] >= 2 and set(out["conversion"]) >= {"lead_to_quote_pct", "quote_to_win_pct"}
    assert client.get("/api/sales/dashboard?sector=space").status_code == 422
    assert client.put("/api/sales/settings", json={"lead_sources": ["Website", " ", "Builder", "website"]}).json()["lead_sources"] == ["Website", "Builder"]
    assert client.get("/api/sales/settings").json()["lead_sources"] == ["Website", "Builder"]


def test_pick_lists_and_choices(client):
    st = client.get("/api/sales/settings").json()
    assert "Blocked drain" in st["work_types"]["maintenance"] and "Price too high" in st["lost_reasons"]
    assert {"key": "20k-50k", "label": "$20k – $50k"} in st["value_bands"]

    # Lists are edited one at a time; the others stay as they were.
    out = client.put("/api/sales/settings", json={"work_types": {"maintenance": ["Blocked drain", "Hot water", ""]}}).json()
    assert out["work_types"]["maintenance"] == ["Blocked drain", "Hot water"] and "New house" in out["work_types"]["residential"]
    assert client.put("/api/sales/settings", json={"work_types": {"space": ["x"]}}).status_code == 422
    client.put("/api/sales/settings", json={"lost_reasons": ["Price too high", "No response"]})
    assert client.get("/api/sales/settings").json()["lost_reasons"] == ["Price too high", "No response"]

    lead = client.post("/api/leads", json={"name": "Unit 4 hot water", "sector": "maintenance", "client": "Coast Strata",
                                           "contact": "Jo 0400 111 222", "work_type": "Hot water", "value_band": "<5k"}).json()
    assert lead["work_type"] == "Hot water" and lead["value_band"] == "<5k"
    assert client.post("/api/leads", json={"name": "x", "value_band": "huge"}).status_code == 422
    clients = client.get("/api/sales/clients").json()
    strata = next(c for c in clients if c["name"] == "Coast Strata")
    assert strata["contacts"] == ["Jo 0400 111 222"] and strata["sectors"] == ["maintenance"]

    jid = lead["id"]
    client.put(f"/api/jobs/{jid}/sales", json={"mark_quote_sent": True, "tender_value": 1800})
    j = client.put(f"/api/jobs/{jid}/sales", json={"tender_result": "lost", "outcome_reason": "Price too high"}).json()
    assert j["outcome_reason"] == "Price too high" and j["sales_stage"] == "lost"
    d = client.get("/api/sales/dashboard?sector=maintenance").json()
    assert {"reason": "Price too high", "count": 1, "value": 1800.0, "pct": 100.0} in d["lost_reasons"]
    assert any(g["name"] == "Hot water" for g in d["by_work_type"]) and any(g["name"] == "Under $5k" for g in d["by_size"])
    # Re-opened: the lost reason goes with it.
    assert client.put(f"/api/jobs/{jid}/sales", json={"tender_result": "pending"}).json()["outcome_reason"] == ""
