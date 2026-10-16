"""Phase 13b: Boards (the Monday.com side): templates, columns, items and subitems, updates with @mentions, files,
automations (instant, dated and recurring), views, forms, My work, the phone and the export."""
import io
from datetime import date, datetime, timedelta, timezone

from openpyxl import load_workbook

from app import boards as bd
from app.db import SessionLocal
from app.models import Notification
from app.timesheets import local_day


def _login(client, email, password="password-123"):
    tok = client.post("/api/auth/login", json={"email": email, "password": password}).json()["token"]
    return {"Authorization": f"Bearer {tok}"}


def _user(client, email, **kw):
    body = {"email": email, "name": kw.pop("name", email.split("@")[0].title()), "password": "password-123", **kw}
    r = client.post("/api/users", json=body)
    assert r.status_code == 200, r.text
    return r.json()["id"], _login(client, email)


def _notes(uid, like=""):
    with SessionLocal() as db:
        q = db.query(Notification).filter(Notification.user_id == uid)
        if like:
            q = q.filter(Notification.text.like(f"%{like}%"))
        return [n.text for n in q]


def test_board_from_template_items_values_and_automations(client):
    kim, kim_h = _user(client, "kim-office@test.local", name="Kim Office", role="estimator")
    b = client.post("/api/boards", json={"template": "office"}).json()
    assert b["name"] == "Office tasks" and [g["title"] for g in b["groups"]] == ["This week", "Next week", "Done"]
    assert {c["key"] for c in b["columns"]} >= {"owner", "status", "priority", "due"}
    week, done = b["groups"][0]["id"], b["groups"][2]["id"]
    it = client.post(f"/api/boards/{b['id']}/items", json={"name": "Renew QBCC licence", "group_id": week,
                                                           "values": {"owner": [kim], "status": "working", "due": str(date.today())}})
    assert it.status_code == 200, it.text
    item = it.json()
    assert _notes(kim, "Renew QBCC licence")  # assigned
    # A bad value is refused with a reason
    r = client.patch(f"/api/boards/items/{item['id']}", json={"values": {"status": "finished"}})
    assert r.status_code == 422 and "Status must be one of" in r.json()["detail"]
    # Done -> the automation moves it to the Done group, and the change is in the activity log
    r = client.patch(f"/api/boards/items/{item['id']}", headers=kim_h, json={"values": {"status": "done"}})
    assert r.json()["group_id"] == done
    det = client.get(f"/api/boards/items/{item['id']}").json()
    assert any(a["what"] == "Status" and a["new"] == "Done" and a["by"] == "Kim Office" for a in det["activity"])
    assert any(a["what"] == "group" and a["new"] == "Done" for a in det["activity"])
    auto = next(a for a in client.get(f"/api/boards/{b['id']}").json()["automations"] if a["name"] == "Done goes to Done")
    assert auto["runs"] == 1
    # Subitems drive a progress column, and "all subitems done" sets the parent's status
    p = client.post("/api/boards", json={"template": "programme", "name": "Maroochydore Apartments programme"}).json()
    parent = client.post(f"/api/boards/{p['id']}/items", json={"name": "Level 3 rough-in", "values": {"status": "working"}}).json()
    subs = [client.post(f"/api/boards/{p['id']}/items", json={"name": n, "parent_id": parent["id"]}).json() for n in ("Sanitary", "Water", "Gas")]
    client.patch(f"/api/boards/items/{subs[0]['id']}", json={"values": {"status": "done"}})
    assert client.get(f"/api/boards/items/{parent['id']}").json()["values"]["progress"] == 33
    for s in subs[1:]:
        client.patch(f"/api/boards/items/{s['id']}", json={"values": {"status": "done"}})
    pv = client.get(f"/api/boards/items/{parent['id']}").json()["values"]
    assert pv["progress"] == 100 and pv["status"] == "done"
    # Subitems can't have subitems
    assert client.post(f"/api/boards/{p['id']}/items", json={"name": "x", "parent_id": subs[0]["id"]}).status_code == 422


def test_updates_mentions_files_timer_and_private_boards(client):
    amy, amy_h = _user(client, "amy-mention@test.local", name="Amy Estimator", role="estimator")
    bob, bob_h = _user(client, "bob-private@test.local", name="Bob", role="estimator")
    b = client.post("/api/boards", json={"template": "blank", "name": "Hot water tender"}).json()
    client.post(f"/api/boards/{b['id']}/columns", json={"title": "Hours", "type": "time"})
    item = client.post(f"/api/boards/{b['id']}/items", json={"name": "Price the Rheem units"}).json()
    r = client.post(f"/api/boards/items/{item['id']}/updates", json={"body": "@Amy can you check the supplier quote?"})
    assert amy in r.json()["mentions"]
    assert _notes(amy, "mentioned you")
    # Amy replies; the admin who wrote first hears about it
    client.post(f"/api/boards/items/{item['id']}/updates", headers=amy_h, json={"body": "Done, Reece is cheapest", "reply_to": r.json()["id"]})
    det = client.get(f"/api/boards/items/{item['id']}").json()
    assert len(det["updates"]) == 2 and det["updates"][0]["by"] == "Amy Estimator"
    up = client.post(f"/api/boards/items/{item['id']}/files", files=[("files", ("quote.pdf", b"%PDF-1.4", "application/pdf"))])
    fid = up.json()[0]
    assert client.get(f"/api/boards/files/{fid}").content == b"%PDF-1.4"
    # Time tracking: start then stop
    key = next(c["key"] for c in client.get(f"/api/boards/{b['id']}").json()["columns"] if c["type"] == "time")
    assert client.post(f"/api/boards/items/{item['id']}/timer", json={"column": key, "start": True}).json()["running_since"]
    stopped = client.post(f"/api/boards/items/{item['id']}/timer", json={"column": key, "start": False}).json()
    assert stopped["running_since"] is None and stopped["seconds"] >= 0
    # Private: Bob can't see it until he's a member
    client.patch(f"/api/boards/{b['id']}", json={"private": True, "members": [amy]})
    assert client.get(f"/api/boards/{b['id']}", headers=bob_h).status_code == 404
    assert not any(x["id"] == b["id"] for x in client.get("/api/boards", headers=bob_h).json())
    assert client.get(f"/api/boards/{b['id']}", headers=amy_h).status_code == 200
    assert client.get(f"/api/boards/files/{fid}", headers=bob_h).status_code == 404


def test_dated_and_recurring_automations_my_work_and_the_phone(client):
    tradie, th = _user(client, "tradie-board@test.local", name="Tradie Tom", role="field", trade="plumber")
    b = client.post("/api/boards", json={"template": "tenders"}).json()
    tomorrow2 = local_day(datetime.now(timezone.utc)) + timedelta(days=2)  # Brisbane's date, as the automations use
    t = client.post(f"/api/boards/{b['id']}/items", json={"name": "Sippy Downs school", "values": {
        "estimator": [tradie], "stage": "pricing", "due": str(tomorrow2), "value": 250000}}).json()
    with SessionLocal() as db:
        n = bd.scheduled(db, datetime.combine(local_day(datetime.now(timezone.utc)), datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=1))
        db.commit()
        again = bd.scheduled(db)
        db.commit()
    assert n >= 1 and again == 0
    assert _notes(tradie, "closes in 2 days")
    # Won: moved to Closed and the owner told, with the value in the message
    client.patch(f"/api/boards/items/{t['id']}", json={"values": {"stage": "won"}})
    with SessionLocal() as db:
        assert db.query(Notification).filter(Notification.text.like("Won: Sippy Downs school ($250,000.00)%")).count() == 1
    # My work on the phone: a safety item assigned to him
    s = client.post("/api/boards", json={"template": "safety"}).json()
    hz = client.post(f"/api/boards/{s['id']}/items", json={"name": "Trench edge collapsing at lot 12",
                                                           "values": {"action_by": [tradie], "severity": "critical",
                                                                      "status": "todo"}}).json()
    assert client.get(f"/api/boards/items/{hz['id']}").json()["values"]["when"] == local_day(datetime.now(timezone.utc)).isoformat()
    mine = client.get("/api/field/my-work", headers=th).json()
    assert any(i["item_id"] == hz["id"] for i in mine["items"])
    assert client.patch(f"/api/field/my-work/items/{hz['id']}", headers=th, json={"values": {"status": "done"}}).status_code == 200
    assert client.post(f"/api/field/my-work/items/{hz['id']}/updates", headers=th, json={"body": "Benched and shored"}).status_code == 200
    assert not any(i["item_id"] == hz["id"] for i in client.get("/api/field/my-work", headers=th).json()["items"])
    # The phone can't open the office board pages
    assert client.get(f"/api/boards/{s['id']}", headers=th).status_code == 403
    # Recurring: once on its day, not twice
    w = client.post("/api/boards", json={"template": "weekly"}).json()
    monday = date.today() - timedelta(days=date.today().weekday())
    at = datetime.combine(monday, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=1)
    with SessionLocal() as db:
        bd.scheduled(db, at)
        db.commit()
        bd.scheduled(db, at + timedelta(minutes=5))
        db.commit()
    items = client.get(f"/api/boards/{w['id']}").json()["items"]
    assert [i["name"] for i in items] == ["Yard and store check"]


def test_custom_automation_views_summary_forms_duplicate_and_export(client):
    b = client.post("/api/boards", json={"template": "requests"}).json()
    cols = {c["key"]: c for c in b["columns"]}
    assert client.post(f"/api/boards/{b['id']}/automations", json={"trigger": {"type": "nope"}, "actions": []}).status_code == 422
    r = client.post(f"/api/boards/{b['id']}/automations", json={
        "name": "Expensive requests are flagged", "trigger": {"type": "column_change", "column": "cost"},
        "actions": [{"type": "create_subitems", "names": ["Get two quotes", "Manager approval"]}]})
    assert r.status_code == 200, r.text
    it = client.post(f"/api/boards/{b['id']}/items", json={"name": "New hilti breaker", "values": {"status": "todo"}}).json()
    client.patch(f"/api/boards/items/{it['id']}", json={"values": {"cost": 1800}})
    assert [s["name"] for s in client.get(f"/api/boards/items/{it['id']}").json()["subitems"]] == ["Get two quotes", "Manager approval"]
    v = client.post(f"/api/boards/{b['id']}/views", json={"name": "By status", "type": "kanban", "settings": {"column": "status"}})
    assert v.status_code == 200
    summ = client.get(f"/api/boards/{b['id']}/summary").json()
    assert summ["items"] == 1 and summ["numbers"][0]["total"] == 1800
    st = next(x for x in summ["status"] if x["column"] == "status")
    assert st["counts"]["todo"] == 1
    # A public form: customers or subbies add items without signing in
    f = client.post(f"/api/boards/{b['id']}/forms", json={"title": "Request gear", "columns": ["needed", "notes", "cost"]}).json()
    anon = {"Authorization": ""}
    pub = client.get(f"/api/public/forms/{f['token']}", headers=anon).json()
    assert [x["key"] for x in pub["fields"]] == ["needed", "notes", "cost"]
    assert client.post(f"/api/public/forms/{f['token']}", headers=anon, json={"name": "Hi-vis shirts x 6",
                                                                             "values": {"notes": "Size L", "status": "done"}}).status_code == 200
    names = [i["name"] for i in client.get(f"/api/boards/{b['id']}").json()["items"]]
    assert "Hi-vis shirts x 6" in names
    sub = next(i for i in client.get(f"/api/boards/{b['id']}").json()["items"] if i["name"] == "Hi-vis shirts x 6")
    assert "status" not in sub["values"]  # only the form's columns are taken
    # Duplicate with items, then export to Excel
    d = client.post(f"/api/boards/{b['id']}/duplicate", json={"with_items": True}).json()
    dup = client.get(f"/api/boards/{d['id']}").json()
    assert len(dup["items"]) == len(client.get(f"/api/boards/{b['id']}").json()["items"]) and len(dup["automations"]) == 2
    x = client.get(f"/api/boards/{b['id']}/export.xlsx")
    ws = load_workbook(io.BytesIO(x.content)).active
    rows = list(ws.values)
    assert rows[0][:3] == ("Group", "Item", "Subitem of") and any(r[1] == "Get two quotes" and r[2] == "New hilti breaker" for r in rows)
    assert cols["cost"]["type"] == "money"
