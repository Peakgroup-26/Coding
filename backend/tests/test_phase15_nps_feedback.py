"""Phase 15: team surveys that must be answered, feedback to your manager, and the director's NPS dashboard."""
from datetime import datetime, timezone

from app.db import SessionLocal
from app.models import Customer, Feedback, Notification


def _login(client, email, password="password-123"):
    tok = client.post("/api/auth/login", json={"email": email, "password": password}).json()["token"]
    return {"Authorization": f"Bearer {tok}"}


def _user(client, email, **kw):
    r = client.post("/api/users", json={"email": email, "name": kw.pop("name", email.split("@")[0].title()), "password": "password-123", **kw})
    assert r.status_code == 200, r.text
    return r.json()["id"], _login(client, email)


def test_required_survey_stays_until_answered(client):
    uid, h = _user(client, "pop-pat@test.local", role="field", trade="plumber")
    sid = client.post("/api/people/surveys", json={"title": "November pulse", "audience": "field"}).json()["id"]
    opt = client.post("/api/people/surveys", json={"title": "Optional: Christmas party ideas", "audience": "field", "required": False}).json()["id"]
    pend = client.get("/api/field/me/pending-surveys", headers=h).json()
    assert [p["id"] for p in pend] == [sid]  # only the must-answer one pops up
    assert pend[0]["questions"][0]["type"] == "enps"
    # Still there after a reload, until it's answered
    assert client.get("/api/field/me/pending-surveys", headers=h).json()[0]["id"] == sid
    client.post(f"/api/field/me/surveys/{sid}", headers=h, json={"answers": {"enps": 9}})
    assert client.get("/api/field/me/pending-surveys", headers=h).json() == []
    # Closing a survey stops it popping up for those who didn't answer
    uid2, h2 = _user(client, "pop-quinn@test.local", role="field", trade="plumber")
    sid2 = client.post("/api/people/surveys", json={"title": "December pulse", "audience": "field"}).json()["id"]
    assert any(p["id"] == sid2 for p in client.get("/api/field/me/pending-surveys", headers=h2).json())
    client.put(f"/api/people/surveys/{sid2}/status?status=closed")
    assert not any(p["id"] == sid2 for p in client.get("/api/field/me/pending-surveys", headers=h2).json())
    assert opt and uid and uid2


def test_feedback_goes_to_their_manager_and_back(client):
    mid, mh = _user(client, "fb-boss@test.local", name="Boss Barry", role="estimator")
    eid, eh = _user(client, "fb-emp@test.local", name="Emp Ella", role="field", trade="plumber")
    client.put(f"/api/people/{eid}/profile", json={"manager_id": mid})
    me = client.get("/api/field/me/feedback", headers=eh).json()
    assert me["goes_to"]["name"] == "Boss Barry" and "safety" in me["kinds"]
    r = client.post("/api/field/me/feedback", headers=eh, json={"kind": "safety", "subject": "Trench shoring at Coolum", "body": "We need the bigger box.", "mood": 3})
    assert r.status_code == 200 and r.json()["to"] == "Boss Barry"
    with SessionLocal() as db:
        assert db.query(Notification).filter(Notification.user_id == mid, Notification.kind == "feedback").count() == 1
    inbox = client.get("/api/field/me/feedback", headers=mh).json()["received"]
    assert inbox[0]["from"] == "Emp Ella" and inbox[0]["status"] == "sent"
    assert client.get("/api/my-work", headers=mh).json()["feedback_waiting"] == 1
    # Only the person it went to can answer it
    assert client.put(f"/api/field/me/feedback/{inbox[0]['id']}", headers=eh, json={"reply": "x"}).status_code == 404
    client.put(f"/api/field/me/feedback/{inbox[0]['id']}", headers=mh, json={"reply": "Ordered, on site Thursday.", "status": "actioned"})
    sent = client.get("/api/field/me/feedback", headers=eh).json()["sent"][0]
    assert sent["status"] == "actioned" and sent["reply"].startswith("Ordered")
    # No manager: it goes to an admin
    nid, nh = _user(client, "fb-nomgr@test.local", role="field")
    assert client.get("/api/field/me/feedback", headers=nh).json()["goes_to"] is not None


def test_director_dashboard_team_and_client_nps(client):
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    people = [_user(client, f"dir-{i}@test.local", role="field", trade="plumber") for i in range(4)]
    sid = client.post("/api/people/surveys", json={"title": "Director test pulse", "audience": "field"}).json()["id"]
    for (uid, h), score in zip(people, (10, 9, 7, 3)):
        client.put(f"/api/people/{uid}/profile", json={"department": "plumbing"})
        client.post(f"/api/field/me/surveys/{sid}", headers=h, json={"answers": {"enps": score}})
    with SessionLocal() as db:
        c = Customer(name="Director test strata", kind="strata")
        db.add(c)
        db.flush()
        for i, s in enumerate((10, 10, 8, 2)):
            db.add(Feedback(customer_id=c.id, token=f"dir-{c.id}-{i}", kind="job", department="maintenance", score=s,
                            responded_at=datetime.now(timezone.utc)))
        db.commit()
    d = client.get("/api/director").json()
    assert len(d["team"]) == 12 and d["team"][-1]["month"] == month
    now = d["team"][-1]
    assert now["responses"] >= 4 and now["enps"] is not None and "plumbing" in now["departments"]
    assert d["clients"][-1]["month"] == month and d["clients"][-1]["responses"] >= 4
    assert "money" in d  # the admin sees the month's money too
    # Hidden for an estimator on the Estimator preset
    pos = {p["name"]: p["id"] for p in client.get("/api/positions").json()}
    eid, eh = _user(client, "dir-est@test.local", role="estimator")
    client.put(f"/api/users/{eid}/access", json={"position_id": pos["Estimator"]})
    assert client.get("/api/director", headers=eh).status_code == 403
    assert next(p for p in client.get("/api/positions").json() if p["name"] == "Director")["features"]["director"] == "edit"
