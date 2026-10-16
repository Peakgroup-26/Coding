"""Phase 13a: People (the BambooHR side): records, pay, licences, leave balances, onboarding, policies, reviews,
surveys, hiring, offboarding and the HR reports."""
import json
from datetime import date, datetime, time, timedelta, timezone

from app import hr
from app.db import SessionLocal
from app.models import Notification, SurveyResponse, TimeEntry, TimeOff, User

PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00"
       b"\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82")


def _login(client, email, password="password-123"):
    tok = client.post("/api/auth/login", json={"email": email, "password": password}).json()["token"]
    return {"Authorization": f"Bearer {tok}"}


def _user(client, email, **kw):
    body = {"email": email, "name": kw.pop("name", email.split("@")[0].title()), "password": "password-123", **kw}
    r = client.post("/api/users", json=body)
    assert r.status_code == 200, r.text
    return r.json()["id"], _login(client, email)


def _types(client):
    return {t["name"]: t["id"] for t in client.get("/api/people/options").json()["credential_types"]}


def test_people_needs_the_hr_permission(client):
    _uid, est = _user(client, "est-nohr@test.local", role="estimator")
    assert client.get("/api/people", headers=est).status_code == 403
    _hid, hr_h = _user(client, "office-hr@test.local", role="estimator", can_hr=True)
    assert client.get("/api/people", headers=hr_h).status_code == 200
    # Everyone can see the directory and their own record, and nothing of anyone else's
    assert client.get("/api/field/me/directory", headers=est).status_code == 200
    assert client.get("/api/field/me", headers=est).json()["profile"]["name"] == "Est-Nohr"


def test_new_starter_onboarding_licences_and_pay(client):
    opts = client.get("/api/people/options").json()
    starter = next(c for c in opts["checklists"] if c["name"] == "New starter")
    mgr_id, mgr_h = _user(client, "boss-mick@test.local", name="Mick", role="estimator", trade="supervisor")
    r = client.post("/api/people", json={"name": "Dave Pipes", "email": "dave-pipes@test.local", "password": "password-123", "role": "field",
                                         "trade": "plumber", "position": "Plumber", "department": "plumbing",
                                         "start_date": str(date.today()), "manager_id": mgr_id, "checklist_id": starter["id"]})
    assert r.status_code == 200, r.text
    dave = r.json()["user_id"]
    dave_h = _login(client, "dave-pipes@test.local")
    rec = client.get(f"/api/people/{dave}").json()
    assert len(rec["tasks"]) == len(starter["tasks"])
    assert rec["compliance"]["missing"] == ["Driver licence", "Plumbing licence (QBCC)", "White card (general construction induction)"] or \
        set(rec["compliance"]["missing"]) == {"Driver licence", "Plumbing licence (QBCC)", "White card (general construction induction)"}
    # The manager has their steps, the starter has theirs (on the phone)
    me = client.get("/api/field/me", headers=dave_h).json()
    assert any("emergency" in t["title"] for t in me["tasks"])
    mine_mgr = client.get("/api/field/me", headers=mgr_h).json()["tasks"]
    assert any(t["title"].startswith("Issue van") and t["person"] == "Dave Pipes" for t in mine_mgr)
    # Dave fills in his details and uploads his white card from the phone
    assert client.put("/api/field/me/profile", headers=dave_h, json={
        "emergency_contacts": [{"name": "Sue", "relationship": "Partner", "phone": "0400 000 000"}], "boot_size": "10",
        "shirt_size": "L"}).status_code == 200
    types = _types(client)
    r = client.post("/api/field/me/credentials", headers=dave_h, data={"type_id": str(types["White card (general construction induction)"]),
                                                                       "number": "WC123", "issued": "2020-01-01"},
                    files={"file": ("card.png", PNG, "image/png")})
    assert r.status_code == 200, r.text
    assert r.json()["has_file"] and not r.json()["verified"] and r.json()["status"] == "current"
    rec = client.get(f"/api/people/{dave}").json()
    assert "White card (general construction induction)" not in rec["compliance"]["missing"]
    assert rec["profile"]["boot_size"] == "10" and rec["profile"]["emergency_contacts"][0]["name"] == "Sue"
    assert any(t["title"].startswith("Upload white card") and t["done"] for t in rec["tasks"])
    with SessionLocal() as db:
        assert db.query(Notification).filter(Notification.kind == "licence", Notification.text.like("Dave Pipes uploaded%")).count() >= 1
    # The office ticks it as checked; the plumbing licence goes in with an expiry worked out from its 12-month renewal
    cid = r.json()["id"]
    assert client.patch(f"/api/people/credentials/{cid}", json={"verified": True}).json()["verified"]
    r = client.post(f"/api/people/{dave}/credentials", data={"type_id": str(types["Plumbing licence (QBCC)"]), "number": "QBCC 1234",
                                                           "issued": str(date.today() - timedelta(days=350))})
    assert r.json()["expires"] == str(hr.default_expiry(SessionLocal(), types["Plumbing licence (QBCC)"], date.today() - timedelta(days=350)))
    assert r.json()["status"] == "expiring"
    # Pay: $40/h with 25% on-costs sets the cost rate used on jobs
    r = client.post(f"/api/people/{dave}/pay", json={"effective": str(date.today()), "amount": 40, "reason": "Starting rate"})
    assert r.json()["cost_rate"] == 50.0
    assert client.get(f"/api/people/{dave}").json()["hourly_rate"] == 40
    # Licence reminders go to Dave and the office, once
    with SessionLocal() as db:
        n1 = hr.daily(db)
        db.commit()
        n2 = hr.daily(db)
        db.commit()
        assert n1 >= 1 and n2 == 0
        assert db.query(Notification).filter(Notification.user_id == dave, Notification.kind == "licence").count() >= 1
    # Gear issued
    assert client.post(f"/api/people/{dave}/gear", json={"item": "Milwaukee M18 kit", "serial": "M18-77", "value": 1200,
                                                         "issued": str(date.today())}).status_code == 200
    assert client.get("/api/field/me", headers=dave_h).json()["gear"][0]["item"] == "Milwaukee M18 kit"


def test_leave_builds_up_with_hours_worked(client):
    uid, h = _user(client, "leave-lee@test.local", name="Lee", role="field", trade="plumber")
    start = date.today() - timedelta(days=60)
    client.put(f"/api/people/{uid}/profile", json={"start_date": str(start), "employment_type": "full_time", "hours_per_week": 38})
    monday = date.today() - timedelta(days=date.today().weekday() + 14)
    with SessionLocal() as db:
        for wk in range(2):  # two weeks of 5 x 8 h = 40 h a week; only 38 count
            for d in range(5):
                day = monday + timedelta(days=7 * wk + d)
                s = datetime.combine(day, time(7, 0), tzinfo=timezone(timedelta(hours=10)))
                db.add(TimeEntry(user_id=uid, start_at=s, end_at=s + timedelta(hours=8), status="approved", source="office"))
        db.add(TimeEntry(user_id=uid, start_at=datetime.now(timezone.utc) - timedelta(hours=3), end_at=datetime.now(timezone.utc),
                         status="submitted", source="office"))  # not approved yet: doesn't count
        db.add(TimeOff(user_id=uid, kind="annual", start_date=monday + timedelta(days=21), end_date=monday + timedelta(days=21),
                       status="requested"))
        db.commit()
    client.post(f"/api/people/{uid}/leave-adjustments", json={"kind": "annual", "day": str(start), "hours": 20, "reason": "Opening balance"})
    bal = {b["kind"]: b for b in client.get(f"/api/people/{uid}").json()["leave"]}
    assert bal["annual"]["accrued"] == round(76 * 152 / 1976, 2)
    assert bal["annual"]["balance"] == round(20 + 76 * 152 / 1976, 2)
    assert bal["sick"]["accrued"] == round(76 * 76 / 1976, 2)
    assert bal["annual"]["booked_or_requested"] == 7.6  # the one-day request, at a 7.6 h day
    assert bal["long_service"]["available"] is False
    # The day off is approved and taken: it comes off, and counts as hours for building up leave
    with SessionLocal() as db:
        t = db.query(TimeOff).filter(TimeOff.user_id == uid).one()
        t.status = "approved"
        t.start_date = t.end_date = monday + timedelta(days=4 + 7)  # moved back into the second week (a Friday already worked)
        db.commit()
    bal = {b["kind"]: b for b in client.get("/api/field/me", headers=h).json()["leave"]}
    assert bal["annual"]["taken"] == 7.6
    # Casuals don't build up annual leave
    client.put(f"/api/people/{uid}/profile", json={"start_date": str(start), "employment_type": "casual"})
    kinds = {b["kind"] for b in client.get(f"/api/people/{uid}").json()["leave"]}
    assert "annual" not in kinds and "long_service" in kinds
    # Projection for Christmas
    client.put(f"/api/people/{uid}/profile", json={"start_date": str(start), "employment_type": "full_time"})
    proj = client.get(f"/api/field/me/leave/projected?on={date.today() + timedelta(days=70)}", headers=h).json()
    ann = next(b for b in proj if b["kind"] == "annual")
    assert ann["projected"] > ann["balance"]
    assert any(r["user_id"] == uid for r in client.get("/api/people/leave").json())


def test_policies_signed_on_the_phone(client):
    uid, h = _user(client, "sign-sam@test.local", name="Sam", role="field", trade="labourer")
    r = client.post("/api/people/policies", data={"title": "Drug and alcohol policy", "body": "Zero tolerance on site.", "audience": "field"})
    pid = r.json()["id"]
    me = client.get("/api/field/me", headers=h).json()
    assert any(p["id"] == pid for p in me["policies"])
    assert client.post(f"/api/field/me/policies/{pid}/sign", headers=h, json={"typed_name": "Sam", "agree": False}).status_code == 422
    r = client.post(f"/api/field/me/policies/{pid}/sign", headers=h, json={"typed_name": "Sam Smith", "agree": True,
                                                                          "signature": "data:image/png;base64,AAA"})
    assert r.status_code == 200 and r.json()["version"] == 1
    assert not any(p["id"] == pid for p in client.get("/api/field/me", headers=h).json()["policies"])
    pol = next(p for p in client.get("/api/people/policies").json() if p["id"] == pid)
    assert "Sam" not in pol["not_signed"]
    # A new version asks everyone again
    client.post("/api/people/policies", data={"title": "Drug and alcohol policy", "body": "Updated.", "audience": "field",
                                              "policy_id": str(pid), "new_version": "true"})
    assert any(p["id"] == pid and p["version"] == 2 for p in client.get("/api/field/me", headers=h).json()["policies"])


def test_reviews_goals_and_anonymous_surveys(client):
    boss, boss_h = _user(client, "rev-boss@test.local", name="Boss", role="estimator", trade="manager")
    emp, emp_h = _user(client, "rev-emp@test.local", name="Emp", role="field", trade="plumber")
    client.put(f"/api/people/{emp}/profile", json={"manager_id": boss, "department": "plumbing"})
    cid = client.post("/api/people/reviews", json={"name": "2026 annual review", "user_ids": [emp]}).json()["id"]
    cyc = next(c for c in client.get("/api/people/reviews").json() if c["id"] == cid)
    rid = cyc["reviews"][0]["id"]
    assert cyc["reviews"][0]["reviewer"] == "Boss"
    assert any(r["id"] == rid and r["as"] == "self" for r in client.get("/api/field/me", headers=emp_h).json()["reviews"])
    assert any(r["id"] == rid and r["as"] == "manager" for r in client.get("/api/field/me", headers=boss_h).json()["reviews"])
    client.put(f"/api/field/me/reviews/{rid}", headers=emp_h, json={"answers": {"quality": 4, "wins": "Finished Maroochydore on time"}})
    client.put(f"/api/field/me/reviews/{rid}", headers=boss_h, json={"answers": {"quality": 4, "safety": 5, "customers": 3, "teamwork": 4,
                                                                                 "next": "Gasfitting licence"}})
    # Not shared yet: the person can't see the manager's side
    assert client.get(f"/api/field/me/reviews/{rid}", headers=emp_h).json()["manager_answers"] == {}
    assert client.patch(f"/api/people/reviews/item/{rid}", json={"share": True}).json()["overall"] == 4.0
    assert client.get(f"/api/field/me/reviews/{rid}", headers=emp_h).json()["manager_answers"]["safety"] == 5
    g = client.post(f"/api/people/{emp}/goals", json={"title": "Get gasfitting licence", "due": str(date.today() + timedelta(days=180))}).json()
    assert client.put(f"/api/field/me/goals/{g['id']}?progress=100", headers=emp_h).json()["status"] == "done"
    # eNPS survey: anonymous, one answer each
    others = [_user(client, f"sv{i}@test.local", role="field", trade="plumber") for i in range(3)]
    sid = client.post("/api/people/surveys", json={"title": "October pulse", "audience": "field"}).json()["id"]
    for i, (oid, oh) in enumerate(others):
        client.put(f"/api/people/{oid}/profile", json={"department": "plumbing"})
        assert client.post(f"/api/field/me/surveys/{sid}", headers=oh, json={"answers": {"enps": [10, 9, 4][i], "why": f"reason {i}"}}).status_code == 200
    assert client.post(f"/api/field/me/surveys/{sid}", headers=others[0][1], json={"answers": {"enps": 10}}).status_code == 409
    res = client.get(f"/api/people/surveys/{sid}").json()
    q = next(x for x in res["questions"] if x["key"] == "enps")
    assert res["responses"] == 3 and round(q["enps"]) == 33
    assert q["by_department"][0]["department"] == "plumbing"
    with SessionLocal() as db:
        assert all(r.user_id is None for r in db.query(SurveyResponse).filter(SurveyResponse.survey_id == sid))


def test_careers_page_hire_and_offboard(client):
    o = client.post("/api/people/openings", json={"title": "2nd year apprentice plumber", "department": "plumbing",
                                                  "employment_type": "apprentice", "questions": [{"key": "licence", "label": "Do you have a C class licence?"}]}).json()
    anon = {"Authorization": ""}
    pub = client.get("/api/public/careers", headers=anon).json()
    assert any(x["id"] == o["id"] for x in pub["openings"])
    r = client.post(f"/api/public/careers/{o['id']}", headers=anon, data={"name": "Jack Apprentice", "email": "jack@example.com",
                                                                         "phone": "0411 111 111", "answers": json.dumps({"licence": "Yes"})},
                    files={"resume": ("resume.pdf", b"%PDF-1.4 test", "application/pdf")})
    assert r.status_code == 200, r.text
    # A bot that fills in the hidden field is ignored
    client.post(f"/api/public/careers/{o['id']}", headers=anon, data={"name": "Spam Bot", "email": "x@y.z", "website": "http://spam"})
    cands = client.get(f"/api/people/candidates?opening_id={o['id']}").json()
    assert [c["name"] for c in cands] == ["Jack Apprentice"] and cands[0]["has_resume"] and cands[0]["answers"]["licence"] == "Yes"
    cid = cands[0]["id"]
    assert client.patch(f"/api/people/candidates/{cid}", json={"stage": "interview", "rating": 4, "note": "Good attitude"}).json()["notes"][0]["text"] == "Good attitude"
    assert client.get(f"/api/people/candidates/{cid}/resume").content.startswith(b"%PDF")
    r = client.post(f"/api/people/candidates/{cid}/hire", json={"role": "field", "trade": "apprentice", "start": str(date.today())})
    assert r.status_code == 200, r.text
    new_id = r.json()["user_id"]
    rec = client.get(f"/api/people/{new_id}").json()
    assert rec["profile"]["position"] == "2nd year apprentice plumber" and rec["profile"]["employment_type"] == "apprentice"
    assert len(rec["tasks"]) > 3
    assert \
        any(x["id"] == o["id"] and x["by_stage"].get("hired") == 1 for x in client.get("/api/people/openings").json())
    # Offboard: last day was yesterday, so the sign-in stops and the gear to collect is listed
    client.post(f"/api/people/{new_id}/gear", json={"item": "Fuel card"})
    leaver = next(c for c in client.get("/api/people/options").json()["checklists"] if c["kind"] == "offboarding")
    r = client.post(f"/api/people/{new_id}/offboard", json={"end_date": str(date.today() - timedelta(days=1)), "end_reason": "resigned",
                                                            "template_id": leaver["id"]})
    assert r.json()["gear_to_collect"] == ["Fuel card"]
    with SessionLocal() as db:
        assert db.get(User, new_id).active is False
    rep = client.get("/api/people/report").json()
    assert rep["leavers_12m"] >= 1 and rep["headcount"] >= 1 and "plumbing" in rep["by_department"]
    assert any(c["missing"] for c in rep["compliance"])


def test_announcements_reach_the_phone(client):
    uid, h = _user(client, "news-ned@test.local", role="field", trade="plumber")
    client.post("/api/people/announcements", json={"title": "Toolbox talk Friday 6:30am", "body": "At the yard.", "audience": "field",
                                                   "pinned": True})
    me = client.get("/api/field/me", headers=h).json()
    assert me["announcements"][0]["title"] == "Toolbox talk Friday 6:30am"
    with SessionLocal() as db:
        assert db.query(Notification).filter(Notification.user_id == uid, Notification.kind == "news").count() == 1
