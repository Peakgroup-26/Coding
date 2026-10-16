"""Phase 16: tool tracking, the Geotab vehicle map, safety (SWMS, pre-starts, incidents, toolbox talks), ITPs with
daily prompts, and PDFs to share or email."""
import json
from datetime import date, datetime, timedelta, timezone

import httpx
import pymupdf as fitz

from app import geotab, messaging
from app import tools as tl
from app.db import SessionLocal
from app.models import Notification, Plant, PlantCheck
from app.timesheets import local_day

PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00"
       b"\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82")
SIG = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4z8DwHwAFAAH/q842iQAAAABJRU5ErkJggg=="


def _login(client, email, password="password-123"):
    tok = client.post("/api/auth/login", json={"email": email, "password": password}).json()["token"]
    return {"Authorization": f"Bearer {tok}"}


def _user(client, email, **kw):
    r = client.post("/api/users", json={"email": email, "name": kw.pop("name", email.split("@")[0].title()), "password": "password-123", **kw})
    assert r.status_code == 200, r.text
    return r.json()["id"], _login(client, email)


def _notes(uid, like):
    with SessionLocal() as db:
        return [n.text for n in db.query(Notification).filter(Notification.user_id == uid, Notification.text.like(f"%{like}%"))]


def test_tools_who_has_it_request_and_hand_over(client):
    dave, dh = _user(client, "tool-dave@test.local", name="Dave Tools", role="field", trade="plumber", phone="0411 222 333")
    sam, sh = _user(client, "tool-sam@test.local", name="Sam Tools", role="field", trade="apprentice", phone="0499 888 777")
    t = client.post("/api/tools", json={"name": "Milwaukee M18 press tool", "category": "Press tool", "asset_no": "PT-07",
                                         "test_tag_due": str(date.today() + timedelta(days=10))}).json()
    client.post(f"/api/tools/{t['id']}/assign", json={"user_id": dave})
    # Everyone sees who has it, with their number to ring
    lst = client.get("/api/field/tools", headers=sh).json()
    row = next(x for x in lst["tools"] if x["id"] == t["id"])
    assert row["holder"] == "Dave Tools" and row["holder_phone"] == "0411 222 333" and row["status"] == "with_person"
    # Sam asks for it: Dave hears about it with Sam's number
    client.post(f"/api/field/tools/{t['id']}/request", headers=sh, json={"note": "For the Coolum job tomorrow"})
    assert _notes(dave, "0499 888 777")
    # They meet up; Dave hands it over and Sam confirms he's got it
    client.post(f"/api/field/tools/{t['id']}/give", headers=dh, json={"to_user_id": sam})
    client.post(f"/api/field/tools/{t['id']}/give", headers=dh, json={"to_user_id": sam})  # a double tap doesn't make two
    assert len([m for m in client.get("/api/field/tools", headers=sh).json()["to_confirm"] if m["kind"] == "handover"]) == 1
    assert next(x for x in client.get("/api/field/tools", headers=sh).json()["tools"] if x["id"] == t["id"])["holder"] == "Dave Tools"  # not yet
    pend = client.get("/api/field/tools", headers=sh).json()["to_confirm"]
    give = next(m for m in pend if m["kind"] == "handover")
    assert client.post(f"/api/field/tool-moves/{give['id']}/confirm", headers=dh).status_code == 403  # Dave can't confirm his own
    client.post(f"/api/field/tool-moves/{give['id']}/confirm", headers=sh)
    after = next(x for x in client.get("/api/field/tools", headers=dh).json()["tools"] if x["id"] == t["id"])
    assert after["holder"] == "Sam Tools" and after["pending"] == []  # Sam's old request is closed off
    # Sam says he took it from the yard after dropping it back: straight away
    client.post(f"/api/field/tools/{t['id']}/return", headers=sh, json={"location": "Yard – cage 2"})
    assert next(x for x in client.get("/api/field/tools", headers=dh).json()["tools"] if x["id"] == t["id"])["location"] == "Yard – cage 2"
    client.post(f"/api/field/tools/{t['id']}/take", headers=dh, json={})
    assert next(x for x in client.get("/api/field/tools", headers=dh).json()["tools"] if x["id"] == t["id"])["holder"] == "Dave Tools"
    hist = client.get(f"/api/tools/{t['id']}/history").json()
    assert [m["kind"] for m in hist][:3] == ["handover", "return", "handover"]
    # Test-and-tag reminder to the holder
    with SessionLocal() as db:
        tl.daily(db)
        db.commit()
    assert _notes(dave, "test and tag")
    # The phone can't use the office register
    assert client.post("/api/tools", headers=dh, json={"name": "x"}).status_code == 403


def test_geotab_vehicles_on_one_map(client, monkeypatch):
    with SessionLocal() as db:
        p = Plant(kind="vehicle", name="Hilux – Dave", rego="GTX123")
        db.add(p)
        db.commit()
        pid = p.id
    assert client.get("/api/vehicles/live").json()["connected"] is False  # not set up yet: says so
    calls = []

    def handler(req: httpx.Request):
        body = json.loads(req.content)
        calls.append(body["method"])
        if body["method"] == "Authenticate":
            return httpx.Response(200, json={"result": {"credentials": {"database": "peak", "userName": "api", "sessionId": "s1"}, "path": "my9.geotab.com"}})
        assert req.url.host == "my9.geotab.com" and body["params"]["credentials"]["sessionId"] == "s1"
        tn = body["params"]["typeName"]
        if tn == "Device":
            return httpx.Response(200, json={"result": [{"id": "b1", "name": "Hilux 01", "licensePlate": "GTX 123", "vehicleIdentificationNumber": "VIN1"},
                                                        {"id": "b2", "name": "Tipper 2", "licensePlate": "999ZZZ"}]})
        if tn == "DeviceStatusInfo":
            return httpx.Response(200, json={"result": [{"device": {"id": "b1"}, "latitude": -26.65, "longitude": 153.09, "speed": 62, "isDriving": True,
                                                         "dateTime": "2026-10-16T01:00:00Z", "driver": {"id": "u1"}},
                                                        {"device": {"id": "b2"}, "latitude": -26.7, "longitude": 153.1, "speed": 0, "isDriving": False}]})
        return httpx.Response(200, json={"result": [{"id": "u1", "firstName": "Dave", "lastName": "Pipes"}]})

    monkeypatch.setattr(geotab, "_transport", httpx.MockTransport(handler))
    monkeypatch.setattr(geotab, "_session", None)
    monkeypatch.setattr(geotab, "_cache", {"at": 0.0, "data": None})
    for k, v in (("GEOTAB_DATABASE", "peak"), ("GEOTAB_USERNAME", "api"), ("GEOTAB_PASSWORD", "x")):
        monkeypatch.setattr(geotab.config, k, v)
    r = client.get("/api/vehicles/live").json()
    assert r["connected"] and len(r["vehicles"]) == 2
    hilux = next(v for v in r["vehicles"] if v["id"] == "b1")
    assert hilux["plant_id"] == pid and hilux["driver"] == "Dave Pipes" and hilux["driving"] and hilux["lat"] == -26.65  # matched on rego
    n = len(calls)
    client.get("/api/vehicles/live")
    assert len(calls) == n  # cached for 30 seconds
    client.put(f"/api/vehicles/link/{pid}", json={"geotab_id": "b2"})
    r = client.get("/api/vehicles/live?fresh=true").json()
    assert next(v for v in r["vehicles"] if v["id"] == "b2")["plant_id"] == pid


def _live_job(client, name):
    r = client.post("/api/work", json={"name": name, "sector": "commercial", "customer_name": "Hutchinson Builders", "customer_kind": "builder",
                                       "address": "1 Ocean St, Maroochydore"})
    assert r.status_code == 200, r.text
    return r.json()


def test_swms_prestart_itp_prompts_and_pdfs(client):
    tim, th = _user(client, "safe-tim@test.local", name="Tim Trench", role="field", trade="plumber")
    job = _live_job(client, "Maroochydore Apartments drainage")
    jid = job["id"]
    client.post("/api/schedule", json={"user_id": tim, "job_id": jid, "day": str(local_day(datetime.now(timezone.utc)))})
    opts = client.get("/api/safety/options").json()
    trench = next(t for t in opts["swms_templates"] if t["title"] == "Excavation and trenching")
    sani = next(t for t in opts["itp_templates"] if t["name"].startswith("Sanitary"))
    js = client.post(f"/api/jobs/{jid}/swms", json={"template_id": trench["id"], "site_notes": "Live 11 kV overhead on the east boundary"}).json()
    ji = client.post(f"/api/jobs/{jid}/itps", json={"template_id": sani["id"], "area": "Basement"}).json()
    # The phone prompts Tim: sign the SWMS, the site pre-start, the daily ITP check and the next items
    today = client.get("/api/field/safety/today", headers=th).json()
    p = next(j for j in today["jobs"] if j["job_id"] == jid)
    assert p["swms_to_sign"][0]["title"] == "Excavation and trenching" and p["prestart"]["done"] is False
    assert any(d["daily"] and d["activity"].startswith("Daily trench") for d in p["itp_due"])
    client.post(f"/api/field/safety/swms/{js['id']}/sign", headers=th, json={"typed_name": "Tim Trench", "signature": SIG})
    client.post("/api/field/safety/prestart", headers=th, json={"job_id": jid, "answers": {"weather": "Fine", "services": True, "ppe": True},
                                                                 "signature": SIG})
    # A second worker signs the same pre-start
    _, h2 = _user(client, "safe-ann@test.local", name="Ann Offsider", role="field", trade="labourer")
    sp = client.post("/api/field/safety/prestart", headers=h2, json={"job_id": jid}).json()
    assert [a["name"] for a in sp["attendees"]] == ["Tim Trench", "Ann Offsider"] and sp["answers"]["weather"] == "Fine"
    # ITP: a hold point can't pass without the signer; a reading is needed for the test
    r = client.post(f"/api/field/safety/itps/{ji['id']}/check", headers=th, json={"item_key": "d7", "result": "pass", "reading": "1.5 m head 15 min, no drop"})
    assert r.status_code == 422 and "Hold point" in r.json()["detail"]
    r = client.post(f"/api/field/safety/itps/{ji['id']}/check", headers=th, json={"item_key": "d7", "result": "pass", "reading": "1.5 m head 15 min, no drop",
                                                                             "signed_name": "Ray Certifier", "signed_role": "Plumbing inspector", "signature": SIG})
    assert r.status_code == 200 and next(i for i in r.json()["items"] if i["key"] == "d7")["done"]
    client.post(f"/api/field/safety/itps/{ji['id']}/check", headers=th, json={"item_key": "d0", "result": "pass", "notes": "Shored to 1.8 m"})
    r = client.post(f"/api/field/safety/itps/{ji['id']}/check", headers=th, json={"item_key": "d4", "result": "fail", "reading": "0.9%", "notes": "Back-fall at IO"})
    assert r.json()["failed"] == 1
    with SessionLocal() as db:
        assert db.query(Notification).filter(Notification.kind == "itp", Notification.text.like("%ITP failed%")).count() >= 1
    after = next(j for j in client.get("/api/field/safety/today", headers=th).json()["jobs"] if j["job_id"] == jid)
    assert after["swms_to_sign"] == [] and after["prestart"]["signed"] and not any(d["daily"] for d in after["itp_due"])
    # Changing the SWMS asks everyone to sign again
    client.patch(f"/api/job-swms/{js['id']}", json={"site_notes": "Live 11 kV overhead – spotter required"})
    assert next(j for j in client.get("/api/field/safety/today", headers=th).json()["jobs"] if j["job_id"] == jid)["swms_to_sign"]
    # PDFs: ITP, site pre-start, SWMS
    for kind, rid in (("itp", ji["id"]), ("prestart", sp["id"]), ("swms", js["id"])):
        r = client.get(f"/api/field/pdf/{kind}/{rid}", headers=th)
        assert r.status_code == 200 and r.headers["content-type"] == "application/pdf", (kind, r.text[:200])
        doc = fitz.open("pdf", r.content)
        text = " ".join("".join(pg.get_text(flags=0) for pg in doc).split())
        assert "page 1 of" in text
        if kind == "itp":
            assert "Ray Certifier" in text and "FAIL" in text and "Inspection and Test Plan" in text
        if kind == "prestart":
            assert "Ann Offsider" in text and "Fine" in text
        if kind == "swms":
            assert "Live 11 kV" in text and "Excavation and trenching" in text
    # Email it with the PDF attached
    out = messaging.capture_for_tests()
    try:
        r = client.post(f"/api/field/pdf/itp/{ji['id']}/email", headers=th, json={"to": "site@hutchinson.example", "message": "ITP for the basement"})
        assert r.status_code == 200 and out[-1]["attachments"][0].endswith(".pdf")
    finally:
        messaging._test_outbox = None


def test_incident_actions_toolbox_dashboard_and_plant_prestart_pdf(client):
    bob, bh = _user(client, "safe-bob@test.local", name="Bob Hurt", role="field", trade="labourer")
    job = _live_job(client, "Kawana carpark drainage")
    up = client.post("/api/field/upload", headers=bh, files={"file": ("cut.png", PNG, "image/png")}, data={"folder": "Safety"}).json()
    r = client.post("/api/field/safety/report", headers=bh, json={"kind": "injury", "title": "Cut hand on pipe saw", "severity": "high",
                                                                  "treatment": "first_aid", "job_id": job["id"], "description": "Guard removed",
                                                                  "photos": [up["id"]]})
    eid = r.json()["id"]
    with SessionLocal() as db:
        assert db.query(Notification).filter(Notification.text.like("%🚨 Injury reported by Bob Hurt%")).count() >= 1
    ev = client.post(f"/api/safety/events/{eid}/actions", json={"description": "Replace guard and retrain on pipe saw", "assignee_id": bob,
                                                                "due": str(date.today() - timedelta(days=1))}).json()
    assert ev["status"] == "investigating" and ev["actions"][0]["overdue"]
    mine = client.get("/api/field/safety/today", headers=bh).json()["actions"]
    client.post(f"/api/field/safety/actions/{mine[0]['id']}/done", headers=bh, json={"note": "Guard back on"})
    client.patch(f"/api/safety/events/{eid}", json={"status": "closed", "root_cause": "Guard removed to cut a short length"})
    tb = client.post("/api/field/safety/toolbox", headers=bh, json={"topic": "Pipe saw guarding", "notes": "Never remove guards", "signature": SIG}).json()
    _, h2 = _user(client, "safe-cal@test.local", name="Cal Crew", role="field")
    tb = client.post(f"/api/field/safety/toolbox/{tb['id']}/sign", headers=h2, json={"typed_name": "Cal Crew", "signature": SIG}).json()
    assert len(tb["attendees"]) == 2
    d = client.get("/api/safety/dashboard").json()
    assert d["events_12m"] >= 1 and d["toolbox_this_month"] >= 1 and d["days_since_lti"] is None  # first aid only, no lost time
    for kind, rid in (("incident", eid), ("toolbox", tb["id"])):
        r = client.get(f"/api/field/pdf/{kind}/{rid}")
        assert r.status_code == 200 and r.content[:4] == b"%PDF"
    # A plant pre-start as a PDF
    with SessionLocal() as db:
        p = Plant(kind="plant", name="5t excavator", fleet_no="EX5")
        db.add(p)
        db.flush()
        pc = PlantCheck(plant_id=p.id, user_id=bob, kind="prestart", answers={"tracks": True, "hydraulics": True}, passed=True, hours=1234.5, fuel_pct=80)
        db.add(pc)
        db.commit()
        pcid = pc.id
    r = client.get(f"/api/field/pdf/plant-check/{pcid}?download=true", headers=bh)
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    assert "5t excavator" in "".join(pg.get_text() for pg in fitz.open("pdf", r.content))
    # People who may not use safety on the phone don't get it
    pos = {p["name"]: p["id"] for p in client.get("/api/positions").json()}
    client.put(f"/api/users/{bob}/access", json={"position_id": pos["Plumber"], "features": {"field_safety": "none"}})
    assert client.get("/api/field/safety/today", headers=bh).status_code == 403
