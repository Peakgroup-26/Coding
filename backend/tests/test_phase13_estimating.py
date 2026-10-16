"""Phase 13c: the estimating workbook (the CostX / CANDY side): resources and build-ups, rows linked live to the
take-off, variables, subcontract quote levelling and award, versions, the tender programme and cash flow."""
import pytest

from app.db import SessionLocal
from app.models import OutboundMessage

from .helpers import calibrate, count, new_job, run, settings, upload


def _login(client, email, password="password-123"):
    tok = client.post("/api/auth/login", json={"email": email, "password": password}).json()["token"]
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def wb(client):
    services, stages = settings(client)
    job = new_job(client, name="Coolum Surf Club", quote_no="Q-WB1")
    sheet = upload(client, job["id"], [{"sheet_no": "H-101", "title": "SANITARY DRAINAGE PLAN"}])[0]
    calibrate(client, sheet["id"])
    san = services["SAN"]["id"]
    run(client, sheet["id"], san, 100, "PVC DWV", [(100, 100), (200, 100), (200, 150)])  # 15 m
    count(client, sheet["id"], san, "WC", 150, 130)
    for r in ({"code": "PLUMB", "kind": "labour", "description": "Plumber", "unit": "h", "rate": 95},
              {"code": "EXC5T", "kind": "plant", "description": "5 t excavator wet hire", "unit": "h", "rate": 120},
              {"code": "PVC100", "kind": "material", "description": "PVC DWV DN100", "unit": "m", "rate": 12.5}):
        assert client.post("/api/resources", json=r).status_code == 200
    b = client.post("/api/rate-buildups", json={"code": "SEWER100", "description": "DN100 sewer in trench to 1.2 m", "unit": "m",
                                                "lines": [{"resource": "PLUMB", "qty": 0.25}, {"resource": "EXC5T", "qty": 0.1},
                                                          {"resource": "PVC100", "qty": 1, "waste_pct": 5}]})
    assert b.status_code == 200, b.text
    assert b.json()["rate"]["total"] == round(23.75 + 12 + 13.125, 2)
    return {"job": job, "sheet": sheet, "services": services, "stages": stages, "san": san}


def test_workbook_rows_price_into_the_estimate(client, wb):
    jid = wb["job"]["id"]
    assert client.put(f"/api/jobs/{jid}/workbook/variables", json=[{"name": "weeks", "value": 10}, {"name": "q", "value": 1}]).status_code == 422
    client.put(f"/api/jobs/{jid}/workbook/variables", json=[{"name": "weeks", "value": 10, "note": "on site"}])
    dims = {d["key"]: d for d in client.get(f"/api/jobs/{jid}/dimensions").json()}
    assert dims["pipe:SAN:PVC DWV:100"]["qty"] == 15 and dims["count:SAN:WC"]["qty"] == 1
    rough = wb["stages"]["Rough-in"]["id"]
    rows = [
        {"section": "Preliminaries", "description": "Site supervision", "qty_source": "formula", "formula": "weeks * 8", "uom": "h",
         "rate_source": "resource", "rate_code": "PLUMB", "margin_pct": 20},
        {"section": "Sanitary drainage", "description": "DN100 sewer in trench", "qty_source": "takeoff", "dimension": "pipe:SAN:PVC DWV:100",
         "uom": "m", "rate_source": "buildup", "rate_code": "SEWER100", "margin_pct": 20, "service_id": wb["san"], "stage_id": rough},
        {"section": "Preliminaries", "description": "Site shed and toilet hire", "qty_source": "formula", "formula": "weeks", "uom": "week",
         "material": 180, "margin_pct": 20},
    ]
    for r in rows:
        assert client.post(f"/api/jobs/{jid}/workbook/lines", json=r).status_code == 200
    w = client.get(f"/api/jobs/{jid}/workbook").json()
    secs = {s["name"]: s for s in w["sections"]}
    sup = next(l for l in secs["Preliminaries"]["lines"] if l["description"] == "Site supervision")
    assert sup["qty"] == 80 and sup["labour_cost"] == 7600 and sup["labour_hours"] == 80 and sup["sell"] == 9120
    sewer = secs["Sanitary drainage"]["lines"][0]
    assert sewer["qty"] == 15 and sewer["plant_cost"] == 180 and sewer["material_cost"] == 196.88 and sewer["labour_cost"] == 356.25
    assert w["totals"]["cost"] == pytest.approx(7600 + 733.13 + 1800)
    # It's all in the estimate, with no price book, by stage and as plant / subcontract
    p = client.get(f"/api/jobs/{jid}/pricing").json()
    s = p["summary"]
    assert s["cost"] == pytest.approx(10133.13) and s["plant_cost"] == 180 and s["sell_ex_gst"] == pytest.approx(10133.13 * 1.2, abs=0.02)
    assert any(r["stage"] == "Rough-in" and r["plant_cost"] == 180 for r in s["by_stage"])
    # A bad formula shows on the row and blocks sign-off
    bad = client.post(f"/api/jobs/{jid}/workbook/lines", json={"section": "Preliminaries", "description": "Crane", "qty_source": "formula",
                                                              "formula": "lifts * 2", "uom": "day", "plant": 1500}).json()["id"]
    row = next(l for s_ in client.get(f"/api/jobs/{jid}/workbook").json()["sections"] for l in s_["lines"] if l["id"] == bad)
    assert "lifts" in row["error"] and row["qty"] == 0
    flags = client.post(f"/api/jobs/{jid}/checks").json()
    assert any(f["check_type"] == "workbook" and "Crane" in f["message"] for f in flags)
    client.delete(f"/api/workbook/lines/{bad}")


def test_live_links_resource_rates_and_versions(client, wb):
    jid = wb["job"]["id"]
    v1 = client.post(f"/api/jobs/{jid}/versions", json={"label": "Tender v1"}).json()["id"]
    # Drawings revised: 3 m more sewer; the plumber's rate goes up
    run(client, wb["sheet"]["id"], wb["san"], 100, "PVC DWV", [(150, 130), (150, 100)])
    res = {r["code"]: r for r in client.get("/api/resources").json()}
    assert res["PLUMB"]["used_in"] == 1
    client.put(f"/api/resources/{res['PLUMB']['id']}", json={**{k: res["PLUMB"][k] for k in ("code", "kind", "description", "unit", "supplier")},
                                                             "rate": 100})
    sewer = next(l for s in client.get(f"/api/jobs/{jid}/workbook").json()["sections"] for l in s["lines"] if l["description"] == "DN100 sewer in trench")
    assert sewer["qty"] == 18 and sewer["labour_cost"] == 18 * 0.25 * 100
    cmp = client.get(f"/api/jobs/{jid}/versions/compare?a={v1}&b=current").json()
    assert cmp["totals"]["cost"]["change"] > 0
    changed = {c["description"]: c for c in cmp["lines"]}
    assert changed["DN100 sewer in trench"]["qty_a"] == 15 and changed["DN100 sewer in trench"]["qty_b"] == 18
    assert changed["Site supervision"]["sell_b"] == 80 * 100 * 1.2
    assert client.get("/api/jobs/{}/versions".format(jid)).json()[0]["label"] == "Tender v1"
    # Rates library edits need the pricing permission
    uid = client.post("/api/users", json={"email": "wb-noprice@test.local", "password": "password-123", "can_pricing": False}).json()["id"]
    h = _login(client, "wb-noprice@test.local")
    assert uid and client.post("/api/resources", headers=h, json={"code": "X", "rate": 1}).status_code == 403
    assert client.get("/api/resources", headers=h).status_code == 200


def test_subcontract_quotes_levelled_and_awarded(client, wb):
    jid = wb["job"]["id"]
    pkg = client.post(f"/api/jobs/{jid}/packages", json={"name": "Concrete cutting and coring", "scope": "Core 12 x 100 mm through slab",
                                                         "margin_pct": 10}).json()
    a = client.post(f"/api/packages/{pkg['id']}/quotes", json={"company": "Coast Cutting", "email": "quotes@coastcut.example",
                                                               "amount": 5000, "exclusions": "Traffic control"}).json()
    qa = a["quotes"][0]
    b = client.post(f"/api/packages/{pkg['id']}/quotes", json={"company": "Sunny Core Drilling", "amount": 5500}).json()
    qb = next(q for q in b["quotes"] if q["company"] == "Sunny Core Drilling")
    assert qa["lowest"]  # before levelling
    # Level: Coast Cutting left out traffic control, plug $800
    lv = client.put(f"/api/package-quotes/{qa['id']}", json={**{k: qa[k] for k in ("company", "email", "amount", "exclusions")},
                                                            "status": "received", "adjustments": [{"description": "Traffic control", "amount": 800}]}).json()
    rows = {q["company"]: q for q in lv["quotes"]}
    assert rows["Coast Cutting"]["levelled"] == 5800 and rows["Sunny Core Drilling"]["lowest"] and rows["Coast Cutting"]["over_lowest"] == 300
    assert lv["spread_pct"] == round(100 * 300 / 5500, 1)
    aw = client.post(f"/api/packages/{pkg['id']}/award", json={"quote_id": qb["id"]}).json()
    line = next(l for s in client.get(f"/api/jobs/{jid}/workbook").json()["sections"] for l in s["lines"] if l["id"] == aw["line_id"])
    assert line["subcontract_cost"] == 5500 and line["sell"] == 6050 and line["description"] == "Concrete cutting and coring – Sunny Core Drilling"
    # Their revised price flows through to the awarded row
    client.put(f"/api/package-quotes/{qb['id']}", json={"company": "Sunny Core Drilling", "amount": 5600, "status": "received"})
    line = next(l for s in client.get(f"/api/jobs/{jid}/workbook").json()["sections"] for l in s["lines"] if l["id"] == aw["line_id"])
    assert line["subcontract_cost"] == 5600
    assert client.get(f"/api/jobs/{jid}/pricing").json()["summary"]["subcontract_cost"] == 5600
    # Inviting: emails for invited firms with an address, once
    pkg2 = client.post(f"/api/jobs/{jid}/packages", json={"name": "Fire services", "due": "2026-11-20"}).json()
    client.post(f"/api/packages/{pkg2['id']}/quotes", json={"company": "Firewise", "email": "est@firewise.example"})
    assert client.post(f"/api/packages/{pkg2['id']}/invite").json()["sent"] == 1
    assert client.post(f"/api/packages/{pkg2['id']}/invite").json()["sent"] == 0
    with SessionLocal() as db:
        m = db.query(OutboundMessage).filter(OutboundMessage.to == "est@firewise.example").one()
        assert "Fire services" in m.subject and "20/11/2026" in m.body


def test_programme_cash_flow_board_and_budget(client, wb):
    jid = wb["job"]["id"]
    g = client.get(f"/api/jobs/{jid}/programme").json()
    assert g["programme"]["saved"] is False and g["programme"]["activities"]
    stages = [a["stages"][0] for a in g["programme"]["activities"] if a["stages"]]
    acts = [{"name": "Prelims and drainage", "stages": stages, "start_week": 0, "weeks": 8, "curve": "s"}]
    r = client.put(f"/api/jobs/{jid}/programme", json={"start": "2026-11-02", "retention_pct": 5, "retention_cap_pct": 5, "terms_days": 30,
                                                     "pay_suppliers_days": 30, "activities": acts})
    assert r.status_code == 200, r.text
    cf = r.json()["cashflow"]
    months = cf["months"]
    assert months[0]["month"] == "2026-11"
    assert sum(m["value"] for m in months) == pytest.approx(cf["contract"], abs=0.1)
    assert sum(m["receipts"] for m in months) == pytest.approx(cf["contract"], abs=0.1)  # retention all back in the end
    assert sum(m["retention_released"] for m in months) == pytest.approx(cf["retention_held"], abs=0.05)
    assert cf["peak_funding"] > 0 and months[0]["receipts"] == 0  # first claim is paid the month after
    board = client.post(f"/api/jobs/{jid}/programme/to-board").json()["board_id"]
    items = client.get(f"/api/boards/{board}").json()["items"]
    assert items[0]["name"] == "Prelims and drainage" and items[0]["values"]["when"]["start"] == "2026-11-02"
    # Copy the workbook into another job as a starting point
    other = new_job(client, name="Peregian Surf Club", quote_no="Q-WB2")
    src = next(s for s in client.get("/api/workbook/sources").json() if s["id"] == jid)
    assert "Preliminaries" in src["sections"]
    assert client.post(f"/api/jobs/{other['id']}/workbook/copy", json={"from_job_id": jid, "sections": ["Preliminaries"]}).json()["copied"] == 2
    assert client.get(f"/api/jobs/{other['id']}/workbook").json()["variables"][0]["name"] == "weeks"
    # Won: the budget carries labour, materials, plant and subcontract from the estimate
    live = client.post(f"/api/jobs/{jid}/start-work").json()
    assert live["work_status"] == "scheduled"
    cats = {b["category"] for b in client.get(f"/api/jobs/{jid}/budget").json()}
    assert {"labour", "materials", "plant", "subcontract"} <= cats
