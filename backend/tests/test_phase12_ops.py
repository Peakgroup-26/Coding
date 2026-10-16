"""Phase 12: live jobs, scheduling, clocking in on the phone, plant pre-starts, purchasing, variations, invoices,
finance (WIP, month to date, cash flow), the CRM, supplier prices, Xero and Ask Peak. No real AI or Xero calls."""
import io
import json
from datetime import date, datetime, timedelta, timezone

import httpx
from openpyxl import Workbook

from app import chat, crm, messaging, scheduler, xero
from app import timesheets as ts
from app.db import SessionLocal
from app.models import PlantCheck, TimeEntry

PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00"
       b"\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82")


def _user(client, email, **kw):
    body = {"email": email, "name": kw.pop("name", email.split("@")[0].title()), "password": "password-123", **kw}
    r = client.post("/api/users", json=body)
    assert r.status_code == 200, r.text
    tok = client.post("/api/auth/login", json={"email": email, "password": "password-123"}).json()["token"]
    return r.json()["id"], {"Authorization": f"Bearer {tok}"}


def _photo(client, h, name="p.png", job_id=None):
    data = {"folder": "Photos"} | ({"job_id": str(job_id)} if job_id else {})
    r = client.post("/api/field/upload", files={"file": (name, PNG, "image/png")}, data=data, headers=h)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _job(client, name="Strata blocked drain", sector="maintenance", **kw):
    r = client.post("/api/work", json={"name": name, "sector": sector, "customer_name": kw.pop("customer_name", "Coastal Strata"),
                                       "customer_kind": kw.pop("customer_kind", "strata"), "address": "12 Ocean St, Mooloolaba", **kw})
    assert r.status_code == 200, r.text
    return r.json()


def test_new_job_and_won_quote_become_live_jobs(client):
    j = _job(client, billing="charge", priority="urgent", description="Blocked sewer at unit 4")
    assert j["job_no"].startswith("J") and j["work_status"] == "scheduled" and j["customer"] == "Coastal Strata" and j["site_id"]
    assert j["quote_no"].startswith("MNT-")
    # A quote won later becomes a job with a budget from its estimate (none priced here: no lines)
    q = client.post("/api/leads", json={"name": "Maroochydore Apartments", "sector": "commercial", "client": "Hutchinson Builders"}).json()
    live = client.post(f"/api/jobs/{q['id']}/start-work").json()
    assert live["job_no"] and live["work_status"] == "scheduled"
    assert client.get(f"/api/jobs/{q['id']}").json()["tender_result"] == "won"
    cust = next(c for c in client.get("/api/customers?q=Hutchinson").json())
    assert cust["kind"] == "builder" and cust["jobs"] == 1
    # Budget lines by hand, and the work list
    client.put(f"/api/jobs/{q['id']}/work", json={"contract_value": 100000, "finish_date": str(date.today() + timedelta(days=60))})
    for cat, hrs, cost in (("labour", 400, 30000), ("materials", 0, 40000)):
        assert client.post(f"/api/jobs/{q['id']}/budget", json={"category": cat, "description": cat, "hours": hrs, "cost": cost}).status_code == 200
    rows = client.get("/api/work").json()
    assert any(r["id"] == q["id"] and r["fin"]["revenue"] == 100000 for r in rows)


def test_field_app_clocking_schedule_and_timesheets(client):
    job = _job(client, "Body corp hot water", customer_name="Seaview Body Corp")
    uid, h = _user(client, "dave@test.local", role="field", trade="plumber", cost_rate=70, name="Dave Plumber")
    # Field staff can only reach the phone app
    assert client.get("/api/jobs", headers=h).status_code == 403
    assert client.get("/api/finance/wip", headers=h).status_code == 403
    assert client.get("/api/field/today", headers=h).status_code == 200
    # The schedule shows up on the phone only once it's published
    today = ts.local_day(ts.now())
    client.post("/api/schedule", json={"user_id": uid, "job_id": job["id"], "day": str(today), "start": "07:00", "end": "15:30"})
    assert client.get("/api/field/today", headers=h).json()["schedule"] == []
    client.post("/api/schedule/publish", json={"start": str(ts.week_start(today)), "days": 7})
    t = client.get("/api/field/today", headers=h).json()
    assert t["schedule"][0]["job_id"] == job["id"]
    assert client.get("/api/field/jobs", headers=h).json()[0]["id"] == job["id"]  # today's job first
    # Clock in (offline retry isn't doubled), switch jobs, break, clock out
    start = ts.now() - timedelta(hours=3)
    a = client.post("/api/field/clock-in", json={"job_id": job["id"], "lat": -26.68, "lng": 153.12, "client_ref": "abc", "at": start.isoformat()},
                    headers=h).json()
    b = client.post("/api/field/clock-in", json={"job_id": job["id"], "client_ref": "abc"}, headers=h).json()
    assert a["id"] == b["id"] and a["start_lat"] == -26.68
    other = _job(client, "Leaking tap unit 2", customer_name="Seaview Body Corp")
    client.post("/api/field/clock-in", json={"job_id": other["id"], "task": "Repairs"}, headers=h)
    client.post("/api/field/break/start", headers=h)
    assert client.get("/api/field/today", headers=h).json()["current"]["on_break"] is True
    client.post("/api/field/break/end", headers=h)
    out = client.post("/api/field/clock-out", json={"notes": "Replaced cartridge"}, headers=h).json()
    assert out["job_id"] == other["id"] and out["end_at"]
    mine = client.get("/api/field/timesheet", headers=h).json()
    assert len(mine["entries"]) == 2 and 2.9 < mine["total"] < 3.1 and mine["can_submit"]
    assert client.post("/api/field/timesheet/submit", json={"start": mine["start"]}, headers=h).json()["submitted"] == 2
    assert client.get(f"/api/jobs/{job['id']}/work").json()["work_status"] == "in_progress"
    # The office approves the week: the cost rate is frozen on the entries
    week = client.get("/api/timesheets").json()
    me = next(p for p in week["people"] if p["user_id"] == uid)
    assert me["submitted"] == 2 and me["ordinary"] == me["total"]
    assert client.post("/api/timesheets/approve", json={"user_id": uid, "start": week["start"]}).json()["approved"] == 2
    with SessionLocal() as db:
        assert {e.cost_rate for e in db.query(TimeEntry).filter(TimeEntry.user_id == uid)} == {70}
    csv = client.get(f"/api/timesheets/payroll.csv?start={week['start']}").text
    assert "Dave Plumber" in csv and "Ordinary" in csv
    # Editing approved time needs a reason and sends it back for approval
    e = client.get("/api/field/timesheet", headers=h).json()["entries"][0]
    bad = client.put(f"/api/timesheets/entries/{e['id']}", json={"user_id": uid, "day": e["local_day"], "start": "06:00", "end": "09:00"})
    assert bad.status_code == 422
    ok = client.put(f"/api/timesheets/entries/{e['id']}", json={"user_id": uid, "day": e["local_day"], "start": "06:00", "end": "09:00",
                                                               "job_id": job["id"], "reason": "Started early"}).json()
    assert ok["status"] == "submitted" and ok["hours"] == 3.0 and "edited" in ok["flags"]
    # Forgot to clock in: added by hand on the phone, flagged
    m = client.post("/api/field/timesheet/manual", json={"job_id": job["id"], "day": str(today - timedelta(days=1)), "start": "07:00",
                                                         "end": "11:00", "notes": "Phone was flat"}, headers=h).json()
    assert m["source"] == "manual" and "added by hand" in m["flags"]
    # Leave request reaches the office
    assert client.post("/api/field/time-off", json={"kind": "annual", "start_date": str(today + timedelta(days=30)),
                                                    "end_date": str(today + timedelta(days=34))}, headers=h).status_code == 200
    assert any(t["name"] == "Dave Plumber" for t in client.get("/api/time-off?status=requested").json())


def test_overtime_split(client):
    with SessionLocal() as db:
        assert ts.overtime(db, {"mon": 10, "tue": 10, "wed": 10, "thu": 10}) == {"ordinary": 38.0, "overtime": 2.0}


def test_vehicle_and_plant_prestarts_gate_clocking(client):
    uid, h = _user(client, "operator@test.local", role="field", trade="labourer", name="Olly Operator")
    job = _job(client, "Kunda Park civil works", sector="commercial", kind="civil", customer_name="Civil Co", customer_kind="civil")
    ute = client.post("/api/plant", json={"kind": "vehicle", "name": "Hilux 12", "rego": "123ABC", "assigned_user_id": uid}).json()
    exc = client.post("/api/plant", json={"kind": "plant", "name": "5t excavator", "category": "Excavator", "hire_rate": 90}).json()
    # No clocking in this week until the vehicle pre-start is done
    r = client.post("/api/field/clock-in", json={"job_id": job["id"]}, headers=h)
    assert r.status_code == 409 and "pre-start" in r.json()["detail"]["message"]
    spec = client.get(f"/api/field/plant/{ute['id']}/checklist?kind=weekly", headers=h).json()
    answers = {f["key"]: True for f in spec["fields"]}
    assert client.post(f"/api/field/plant/{ute['id']}/check", json={"kind": "weekly", "answers": answers, "odometer": 45210}, headers=h).status_code == 422
    photos = {k: _photo(client, h) for k in spec["photos"]}
    assert client.post(f"/api/field/plant/{ute['id']}/check", json={"kind": "weekly", "answers": answers, "odometer": 45210, "photo_ids": photos},
                       headers=h).json()["passed"]
    # Operating the excavator: needs today's pre-start with machine and fuel photos
    r = client.post("/api/field/clock-in", json={"job_id": job["id"], "plant_id": exc["id"]}, headers=h)
    assert r.status_code == 409 and "pre-start on 5t excavator" in r.json()["detail"]["message"]
    pspec = client.get(f"/api/field/plant/{exc['id']}/checklist?kind=prestart", headers=h).json()
    assert pspec["photos"] == ["machine", "fuel"]
    pans = {f["key"]: True for f in pspec["fields"]}
    chk = client.post(f"/api/field/plant/{exc['id']}/check", headers=h, json={
        "kind": "prestart", "answers": pans, "hours": 1520.5, "fuel_pct": 80,
        "photo_ids": {"machine": _photo(client, h), "fuel": _photo(client, h)}}).json()
    assert chk["passed"]
    clock = client.post("/api/field/clock-in", json={"job_id": job["id"], "plant_id": exc["id"]}, headers=h)
    assert clock.status_code == 200, clock.text
    # Can't clock off without the end-of-day photos
    r = client.post("/api/field/clock-out", json={}, headers=h)
    assert r.status_code == 409 and "fuel gauge" in r.json()["detail"]["message"]
    client.post(f"/api/field/plant/{exc['id']}/check", headers=h, json={
        "kind": "end_day", "hours": 1528, "fuel_pct": 35, "photo_ids": {"machine": _photo(client, h), "fuel": _photo(client, h)}})
    assert client.post("/api/field/clock-out", json={}, headers=h).status_code == 200
    with SessionLocal() as db:
        e = db.query(TimeEntry).filter(TimeEntry.user_id == uid).one()
        e.start_at = e.end_at - timedelta(hours=8)  # a full day on the machine
        db.commit()
    fin = client.get(f"/api/jobs/{job['id']}/work").json()["financials"]
    plant_row = next(r for r in fin["categories"] if r["category"] == "plant")
    assert plant_row["actual"] == 720.0  # 8 h x $90
    # A failed pre-start item raises a defect; a critical one takes the machine out of service
    pans["guards"] = False
    res = client.post(f"/api/field/plant/{exc['id']}/check", headers=h, json={
        "kind": "prestart", "answers": pans, "photo_ids": {"machine": _photo(client, h), "fuel": _photo(client, h)}}).json()
    assert res["passed"] is False and res["failed"]
    d = client.post(f"/api/field/plant/{exc['id']}/defects", json={"severity": "critical", "description": "Hydraulic hose burst",
                                                                    "photo_ids": [_photo(client, h)]}, headers=h).json()
    assert d["plant_status"] == "out_of_service"
    assert "out of service" in client.post("/api/field/clock-in", json={"job_id": job["id"], "plant_id": exc["id"]}, headers=h).json()["detail"]["message"]
    detail = client.get(f"/api/plant/{exc['id']}").json()
    assert len(detail["defects"]) == 2 and detail["hours"] == 1528
    for x in detail["defects"]:
        client.put(f"/api/plant-defects/{x['id']}", json={"status": "fixed", "repair_notes": "Replaced hose"})
    assert client.get(f"/api/plant/{exc['id']}").json()["status"] == "in_service"
    # Monthly wash reminder goes to the driver once
    from app import plant
    with SessionLocal() as db:
        n1 = plant.monthly_reminders(db)
        n2 = plant.monthly_reminders(db)
        db.commit()
    assert n1 >= 1 and n2 == 0
    assert any(n["kind"] == "wash" for n in client.get("/api/field/today", headers=h).json()["notifications"])
    comp = {r["name"]: r for r in client.get("/api/plant-compliance").json()}
    assert comp["Hilux 12"]["weekly_done"] and not comp["Hilux 12"]["wash_done"]


def test_purchasing_variations_invoices_and_finance(client):
    job = _job(client, "Noosa Medical Centre fit-out", sector="commercial", customer_name="Noosa Builders", customer_kind="builder",
               billing="fixed", contract_value=50000)
    jid = job["id"]
    for cat, hrs, cost in (("labour", 100, 7000), ("materials", 0, 20000)):
        client.post(f"/api/jobs/{jid}/budget", json={"category": cat, "hours": hrs, "cost": cost})
    sup = client.post("/api/suppliers", json={"name": "Reece Noosaville", "terms_days": 30}).json()
    uid, h = _user(client, "sam@test.local", role="field", trade="plumber", cost_rate=60, name="Sam Sparky")
    # A PO number at the trade counter, from the phone
    po = client.post(f"/api/field/jobs/{jid}/po", json={"supplier_id": sup["id"], "lines": [{"description": "100 DN PVC", "qty": 12, "unit_cost": 25}]},
                     headers=h).json()
    assert po["po_no"].startswith(job["job_no"] + "-PO") and po["status"] == "sent" and po["value"] == 300
    fin = client.get(f"/api/jobs/{jid}/work").json()["financials"]
    assert fin["committed"] == 300 and fin["cost_to_date"] == 0
    billed = client.post(f"/api/purchase-orders/{po['id']}/bill", json={"bill_ref": "INV-778", "bill_amount": 310, "bill_date": str(date.today())}).json()
    assert billed["status"] == "billed" and billed["bill_variance"] == 10
    # Van stock used on site, an office cost
    client.post(f"/api/field/jobs/{jid}/materials", json={"description": "Teflon tape", "qty": 2, "unit_cost": 3.5}, headers=h)
    client.post(f"/api/jobs/{jid}/costs", json={"day": str(date.today()), "category": "subcontract", "description": "Core drilling", "unit_cost": 1200})
    assert client.post(f"/api/jobs/{jid}/costs", json={"day": str(date.today()), "category": "labour", "unit_cost": 1}).status_code == 422
    # Time on the job
    with SessionLocal() as db:
        db.add(TimeEntry(user_id=uid, job_id=jid, start_at=ts.now() - timedelta(hours=10), end_at=ts.now() - timedelta(hours=2), status="submitted"))
        db.commit()
    # An approved variation adds to the contract and the budget
    v = client.post(f"/api/jobs/{jid}/variations", json={"title": "Extra basin", "sell": 3000, "cost": 1500, "hours": 10}).json()
    assert v["number"] == 1
    client.put(f"/api/variations/{v['id']}", json={**{k: v[k] for k in ("title", "sell", "cost", "hours")}, "status": "approved"})
    f = client.get(f"/api/jobs/{jid}/work").json()["financials"]
    assert f["revenue"] == 53000 and f["variations_approved"] == 3000
    assert f["hours_budget"] == 110 and f["hours_actual"] == 8.0
    cats = {r["category"]: r for r in f["categories"]}
    assert cats["labour"]["actual"] == 480.0  # 8 h x $60
    assert cats["materials"]["actual"] == 317.0  # bill 310 + tape 7
    assert cats["subcontract"]["actual"] == 1200 and cats["subcontract"]["budget"] == 0 and cats["subcontract"]["forecast"] == 1200
    assert f["over_budget"] is True  # subcontract had no budget
    # Progress claim from % complete; sending it queues the builder's follow-up only for final invoices
    client.put(f"/api/jobs/{jid}/work", json={"percent_complete": 40})
    sug = client.get(f"/api/invoices/suggest/{jid}").json()
    assert sug["amount"] == 21200.0  # 40% of 53,000
    inv = client.post("/api/invoices", json={"job_id": jid, "percent": 40, "status": "sent"}).json()
    assert inv["amount"] == 21200 and inv["status"] == "sent" and inv["invoice_no"].startswith("INV-")
    assert inv["due_date"] == str(date.today() + timedelta(days=30))  # the customer's terms
    w = client.get("/api/finance/wip").json()
    row = next(r for r in w["rows"] if r["job_id"] == jid)
    assert row["percent_complete"] == 40 and row["invoiced"] == 21200 and abs(row["over_under_billed"]) < 0.01
    # Month to date, cash flow and the dashboard all run
    client.put("/api/budget-months", json={"month": date.today().strftime("%Y-%m"), "revenue": 100000, "labour": 30000, "materials": 25000})
    mtd = client.get("/api/finance/month").json()
    lab = next(l for l in mtd["lines"] if l["key"] == "labour")
    assert mtd["forecast_source"] == "budget" and lab["forecast"] == 30000 and lab["prorated"] <= 30000
    assert lab["state"] in ("under", "on", "over")
    cf = client.get("/api/finance/cashflow?weeks=8").json()
    assert len(cf["weeks"]) == 8 and cf["in_total"] > 0
    dash = client.get("/api/finance/dashboard").json()
    assert dash["active_jobs"] >= 1 and "buckets" not in dash["debtors"]
    paid = client.put(f"/api/invoices/{inv['id']}/status", json={"status": "paid"}).json()
    assert paid["status"] == "paid" and paid["paid_amount"] == paid["total"]


def test_crm_follow_ups_feedback_and_nps(client):
    outbox = messaging.capture_for_tests()
    try:
        cust = client.post("/api/customers", json={"name": "Jane Homeowner", "kind": "residential", "email": "jane@example.com"}).json()
        client.put("/api/ops-settings", json={"google_review_url": "https://g.page/r/peak/review"})
        job = client.post("/api/work", json={"name": "Kitchen tap", "sector": "residential", "customer_id": cust["id"], "billing": "fixed",
                                             "contract_value": 450}).json()
        inv = client.post("/api/invoices", json={"job_id": job["id"], "kind": "final", "amount": 450, "status": "sent"}).json()
        msgs = [m for m in client.get("/api/crm/messages").json() if m["customer_id"] == cust["id"]]
        assert len(msgs) == 1 and msgs[0]["status"] == "queued" and "/feedback/" in msgs[0]["body"]
        # Not yet due (2 days, 9am); then it's due
        with SessionLocal() as db:
            assert crm.send_due(db)["sent"] == 0
            assert crm.send_due(db, datetime.now(timezone.utc) + timedelta(days=3))["sent"] == 1
            db.commit()
        assert outbox[-1]["to"] == "jane@example.com"
        token = outbox[-1]["body"].split("/feedback/")[1].split()[0]
        form = client.get(f"/api/public/feedback/{token}", headers={"Authorization": ""}).json()
        assert form["job"] == "Kitchen tap" and not form["answered"]
        ans = client.post(f"/api/public/feedback/{token}", json={"score": 10, "ratings": {"quality": 5, "cleanliness": 4}, "comment": "Great"},
                          headers={"Authorization": ""}).json()
        assert ans["review_url"] == "https://g.page/r/peak/review"
        assert client.post(f"/api/public/feedback/{token}", json={"score": 3}).status_code == 409
        # A commercial client gets no review ask; a monthly check-in goes to builders who had work last month
        rules = client.get("/api/crm/rules").json()
        assert any(r["trigger"] == "monthly" for r in rules)
        b = client.post("/api/customers", json={"name": "Big Builder Pty Ltd", "kind": "builder", "email": "pm@bigbuilder.com.au"}).json()
        bj = client.post("/api/work", json={"name": "Tower fit-out", "sector": "commercial", "customer_id": b["id"]}).json()
        uid, _h = _user(client, "monthly@test.local", role="field")
        first = date.today().replace(day=1)
        last_month = first - timedelta(days=10)
        with SessionLocal() as db:
            db.add(TimeEntry(user_id=uid, job_id=bj["id"], start_at=datetime.combine(last_month, datetime.min.time(), tzinfo=ts.TZ) + timedelta(hours=7),
                             end_at=datetime.combine(last_month, datetime.min.time(), tzinfo=ts.TZ) + timedelta(hours=15)))
            db.commit()
            assert crm.monthly(db, first) == 1
            assert crm.monthly(db, first) == 0  # once a month
            crm.send_due(db)
            db.commit()
        token2 = outbox[-1]["body"].split("/feedback/")[1].split()[0]
        r = client.post(f"/api/public/feedback/{token2}", json={"score": 5, "comment": "Slow to respond"}).json()
        assert r["review_url"] == ""
        tasks = client.get("/api/crm/tasks").json()
        assert any("5/10" in t["text"] and t["customer"] == "Big Builder Pty Ltd" for t in tasks)
        nps = client.get("/api/crm/nps").json()
        assert nps["overall"]["responses"] == 2 and nps["overall"]["nps"] == 0.0  # one promoter, one detractor
        depts = {d["key"]: d for d in nps["by_department"]}
        assert depts["residential"]["nps"] == 100.0 and depts["commercial"]["nps"] == -100.0
        detail = client.get(f"/api/customers/{b['id']}").json()
        assert detail["nps"] == -100.0 and detail["feedback"][0]["score"] == 5
    finally:
        messaging._test_outbox = None


def _price_file(rows, headers):
    wb = Workbook()
    ws = wb.active
    ws.append(headers)
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_supplier_price_files_and_cheapest_supplier(client):
    reece = client.post("/api/suppliers", json={"name": "Reece Plumbing"}).json()
    tl = client.post("/api/suppliers", json={"name": "Tradelink"}).json()
    rfile = _price_file([["R100", "PVC DWV 100 bend 88", "Holman", "HOL-B100", "PVC fittings", "ea", 12.40],
                         ["R200", "Flick mixer chrome", "Caroma", "CAR-90123", "Tapware", "ea", 189.00]],
                        ["Product Code", "Description", "Brand", "Manufacturer Code", "Product Group", "UOM", "Nett Price"])
    pre = client.post("/api/supplier-prices/preview", files={"file": ("maX.xlsx", rfile)}, data={"supplier_id": reece["id"]}).json()
    assert pre["columns"]["code"] == "Product Code" and pre["columns"]["price"] == "Nett Price" and pre["columns"]["mfr_code"] == "Manufacturer Code"
    r = client.post("/api/supplier-prices/import", files={"file": ("maX.xlsx", rfile)}, data={"supplier_id": reece["id"], "source": "reece_max"}).json()
    assert r == {"rows": 2, "new_items": 2, "price_up": 0, "price_down": 0}
    tcsv = "Item Code,Item Description,Supplier Part Number,Trade Price,Category\nT-55,Holman 100mm 88deg bend,HOL B100,11.10,PVC fittings\n" \
           "T-77,Caroma flick mixer,CAR90123,199.50,Tapware\n"
    client.post("/api/supplier-prices/import", files={"file": ("tradelink.csv", tcsv.encode())}, data={"supplier_id": tl["id"]})
    cmp = client.get("/api/supplier-prices/compare").json()
    assert cmp["products"] == 2
    bend = next(x for x in cmp["rows"] if "bend" in x["description"].lower())
    assert bend["cheapest_supplier"] == "Tradelink" and bend["cheapest_price"] == 11.10
    mixer = next(x for x in cmp["rows"] if "mixer" in x["description"].lower())
    assert mixer["cheapest_supplier"] == "Reece Plumbing"
    # Next month's file: a price rise is counted and the history kept
    rfile2 = _price_file([["R100", "PVC DWV 100 bend 88", "Holman", "HOL-B100", "PVC fittings", "ea", 10.95]],
                         ["Product Code", "Description", "Brand", "Manufacturer Code", "Product Group", "UOM", "Nett Price"])
    r2 = client.post("/api/supplier-prices/import", files={"file": ("maX2.xlsx", rfile2)}, data={"supplier_id": reece["id"]}).json()
    assert r2["price_down"] == 1
    assert [p["price"] for p in client.get(f"/api/supplier-prices/history?supplier_id={reece['id']}&code=R100").json()] == [12.40, 10.95]
    assert client.get("/api/supplier-prices/compare").json()["rows"][0]["prices"][0]["supplier"] in ("Reece Plumbing", "Tradelink")
    assert "Cheapest" in client.get("/api/supplier-prices/compare.csv").text


class FakeXero(httpx.BaseTransport):
    def __init__(self):
        self.calls = []
        self.invoices = {}

    def handle_request(self, request):
        url, m = str(request.url), request.method
        self.calls.append((m, url))
        if url.startswith(xero.TOKEN_URL):
            return httpx.Response(200, json={"access_token": "at", "refresh_token": "rt", "expires_in": 1800})
        if url.startswith(xero.CONNECTIONS_URL):
            return httpx.Response(200, json=[{"tenantId": "t1", "tenantName": "Peak Plumbing", "tenantType": "ORGANISATION"}])
        if "/Contacts" in url and m == "GET":
            return httpx.Response(200, json={"Contacts": []})
        if "/Contacts" in url:
            return httpx.Response(200, json={"Contacts": [{"ContactID": "c-1"}]})
        if "/Invoices" in url and m == "POST":
            body = json.loads(request.content)["Invoices"][0]
            self.invoices[body["InvoiceNumber"]] = body
            return httpx.Response(200, json={"Invoices": [{"InvoiceID": "x-" + body["InvoiceNumber"]}]})
        if "/Invoices" in url and "IDs=" in url:
            ids = request.url.params["IDs"].split(",")
            return httpx.Response(200, json={"Invoices": [{"InvoiceID": i, "Status": "PAID", "AmountPaid": 99, "FullyPaidOnDate": "2026-10-10T00:00:00"}
                                                          for i in ids]})
        if "/Invoices" in url and "ACCPAY" in request.url.params.get("where", ""):
            return httpx.Response(200, json={"Invoices": [{"InvoiceID": "bill-1", "Type": "ACCPAY", "Status": "AUTHORISED", "SubTotal": 455.0,
                                                           "InvoiceNumber": "S99", "Reference": self.po_no, "DateString": "2026-10-12T00:00:00",
                                                           "Contact": {"Name": "Reece Plumbing"}}]})
        if "/Invoices" in url:
            return httpx.Response(200, json={"Invoices": []})
        if "BankSummary" in url:
            return httpx.Response(200, json={"Reports": [{"Rows": [{"RowType": "Section", "Rows": [
                {"RowType": "Row", "Cells": [{"Value": "Cheque"}, {"Value": "1"}, {"Value": "2"}, {"Value": "3"}, {"Value": "84250.55"}]}]}]}]})
        return httpx.Response(404, json={})


def test_xero_sync(client, monkeypatch):
    from app import config

    monkeypatch.setattr(config, "XERO_CLIENT_ID", "id")
    monkeypatch.setattr(config, "XERO_CLIENT_SECRET", "secret")
    fake = FakeXero()
    monkeypatch.setattr(xero, "_transport", fake)
    url = client.get("/api/integrations/xero/connect").json()["url"]
    assert url.startswith(xero.AUTH_URL) and "accounting.invoices" in url
    state = httpx.URL(url).params["state"]
    job = _job(client, "Xero test job", customer_name="Xero Customer", billing="fixed", contract_value=1000)
    po = client.post("/api/purchase-orders", json={"job_id": job["id"], "supplier_name": "Reece Plumbing", "status": "sent",
                                                   "lines": [{"description": "Pipe", "qty": 1, "unit_cost": 450}]}).json()
    fake.po_no = po["po_no"]
    inv = client.post("/api/invoices", json={"job_id": job["id"], "amount": 1000, "status": "sent"}).json()
    r = client.get(f"/api/public/xero-callback?code=abc&state={state}", follow_redirects=False)
    assert r.status_code in (302, 307) and "xero=connected" in r.headers["location"]
    st = client.get("/api/integrations").json()["xero"]
    assert st["status"] == "connected" and st["organisation"] == "Peak Plumbing" and not st["last_error"], st
    assert inv["invoice_no"] in fake.invoices and fake.invoices[inv["invoice_no"]]["Reference"].startswith(job["job_no"])
    assert client.get(f"/api/purchase-orders/{po['id']}").json()["bill_amount"] == 455.0
    assert client.get("/api/ops-settings").json()["opening_bank_balance"] == 84250.55
    out = client.post("/api/integrations/xero/sync").json()  # the first round (at connect) already pulled the payment
    assert out["errors"] == [] and out["payments"] == 0 and out["bills"] == 0  # nothing new: the bill isn't counted twice
    assert next(i for i in client.get("/api/invoices").json() if i["id"] == inv["id"])["status"] == "paid"
    assert client.get("/api/public/xero-callback?code=abc&state=wrong", follow_redirects=False).headers["location"].find("xero_error") > 0


class AskModel:
    """Plays Ask Peak: finds the job, gets labour hours, shows a report, then answers."""

    def respond(self, system, tools, messages):
        n = sum(1 for m in messages if m["role"] == "assistant")
        last = messages[-1]["content"]
        if n == 0:
            return "tool_use", [{"type": "tool_use", "id": "t1", "name": "find_jobs", "input": {"query": "noosa medical"}}], "fake"
        if n == 1:
            found = json.loads(last[0]["content"])
            assert isinstance(found, list), found
            jid = found[0]["job_id"]
            return "tool_use", [{"type": "tool_use", "id": "t2", "name": "labour_hours", "input": {"job_id": jid, "group_by": "person"}}], "fake"
        if n == 2:
            data = json.loads(last[0]["content"])
            self.data = data
            return "tool_use", [{"type": "tool_use", "id": "t3", "name": "show_report", "input": {
                "title": "Labour: actual vs estimated", "columns": ["Measure", "Hours"],
                "rows": [["Estimated", data["budget_hours_total"]], ["Actual", data["actual_hours_total"]]],
                "chart": {"type": "bar", "x": "Measure", "y": ["Hours"]}}}], "fake"
        return "end_turn", [{"type": "text", "text": f"{self.data['actual_hours_total']} hours so far against {self.data['budget_hours_total']} estimated."}], "fake"

    def summarise(self, prompt):
        return ""


def test_ask_peak_makes_a_report(client):
    chat.set_model(AskModel())
    try:
        out = client.post("/api/assistant", json={"text": "How many labour hours on Noosa Medical, actual vs estimated?"}).json()
        msg = out["messages"][-1]
        assert msg["role"] == "assistant" and "8.0 hours so far against 110.0 estimated" in msg["text"]
        rep = msg["reports"][0]
        assert rep["rows"] == [["Estimated", 110.0], ["Actual", 8.0]]
        x = client.get(f"/api/assistant/reports/{msg['id']}/0.xlsx")
        assert x.status_code == 200 and x.content[:2] == b"PK"
        assert len(client.get("/api/assistant").json()["messages"]) == 2
        # Someone without finance can't use the money tools
        _uid, h = _user(client, "nofin@test.local", can_finance=False)
        from app import assistant
        with SessionLocal() as db:
            from app.models import User
            u = db.query(User).filter(User.email == "nofin@test.local").one()
            names = [t["name"] for t in assistant.schemas(u)]
        assert "wip_report" not in names and "labour_hours" in names
    finally:
        chat.set_model(None)


def test_documents_items_diary_assets_and_maintenance(client):
    job = _job(client, "Docs job", customer_name="Docs Co")
    jid = job["id"]
    up = client.post(f"/api/jobs/{jid}/docs", files=[("files", ("contract.pdf", b"%PDF-1.4 a", "application/pdf"))], data={"folder": "Contract"}).json()
    up2 = client.post(f"/api/jobs/{jid}/docs", files=[("files", ("contract.pdf", b"%PDF-1.4 b", "application/pdf"))], data={"folder": "Contract"}).json()
    assert up2[0]["version"] == 2
    docs = client.get(f"/api/jobs/{jid}/docs").json()["documents"]
    assert [d["version"] for d in docs if d["filename"] == "contract.pdf"] == [2]
    assert len(client.get(f"/api/files/{up2[0]['id']}/versions").json()) == 2
    assert client.get(f"/api/files/{up[0]['id']}").content == b"%PDF-1.4 a"
    a = client.post(f"/api/jobs/{jid}/items", json={"kind": "rfi", "title": "Pipe route at grid C?", "due_date": str(date.today() - timedelta(days=1))}).json()
    b = client.post(f"/api/jobs/{jid}/items", json={"kind": "rfi", "title": "Second RFI"}).json()
    assert (a["number"], b["number"], a["ref"], a["overdue"]) == (1, 2, "RFI 1", True)
    v = client.post(f"/api/items/{a['id']}/variation").json()
    assert v["number"] >= 1
    client.post(f"/api/jobs/{jid}/diary", json={"day": str(date.today()), "weather": "Fine", "work_done": "Rough-in level 2"})
    assert client.get(f"/api/jobs/{jid}/diary").json()[0]["weather"] == "Fine"
    # Assets due for service become a job; servicing one moves its next due date on
    site_id = job["site_id"]
    asset = client.post("/api/assets", json={"site_id": site_id, "kind": "Backflow prevention device", "serial": "BF-1", "interval_months": 12,
                                             "next_due": str(date.today() + timedelta(days=5)), "service_price": 180}).json()
    gen = client.post("/api/maintenance/generate", json={"within_days": 30}).json()
    sj = next(j for j in gen["jobs"] if "Scheduled service" in j["name"])
    assert client.post("/api/maintenance/generate", json={"within_days": 30}).json()["jobs"] == []  # not twice
    form = next(t for t in client.get("/api/form-templates").json() if t["name"] == "Backflow test report")
    uid, h = _user(client, "tester@test.local", role="field", name="Tess Tester")
    r = client.post(f"/api/field/jobs/{sj['id']}/forms/{form['id']}", json={"asset_id": asset["id"], "answers": {"result": "Pass", "check1": 35}},
                    headers=h)
    assert r.status_code == 200, r.text
    nxt = next(x for x in client.get("/api/assets").json()["assets"] if x["id"] == asset["id"])
    assert nxt["last_service"] == str(ts.local_day(ts.now())) and nxt["next_due"] > str(date.today() + timedelta(days=300))
    # The tech completes the job with the customer's signature
    done = client.post(f"/api/field/jobs/{sj['id']}/complete", json={"signature": "data:image/png;base64,AAAA", "signed_by_name": "Body corp manager"},
                       headers=h).json()
    assert done["work_status"] == "complete"


def test_scheduler_tick_runs(client):
    scheduler.tick(full_xero=False)  # nothing to do, and nothing breaks


def test_photos_on_a_job_without_being_clocked_in(client):
    job = _job(client, "Photo job", customer_name="Photo Co")
    _uid, h = _user(client, "photographer@test.local", role="field")
    assert client.get("/api/field/today", headers=h).json()["current"] is None
    ids = [_photo(client, h, f"site{i}.jpg", job_id=job["id"]) for i in range(3)]
    docs = client.get(f"/api/field/jobs/{job['id']}", headers=h).json()["documents"]
    assert {d["id"] for d in docs if d["folder"] == "Photos" and d["is_image"]} >= set(ids)
    assert client.get(f"/api/field/documents/{ids[0]}", headers=h).content == PNG
    # and the office sees them in the job's documents
    office = client.get(f"/api/jobs/{job['id']}/docs").json()["documents"]
    assert sum(1 for d in office if d["folder"] == "Photos") == 3
