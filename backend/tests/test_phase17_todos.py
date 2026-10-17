"""Phase 17: daily to-do lists. Supervisors, foremen, managers and the office set them; nobody clocks off until every task
is ticked off or has a reason it couldn't be finished."""
from datetime import timedelta

from app import todos as td
from tests.test_phase16_tools_safety import _notes, _user


def test_todos_block_clock_off_until_ticked_or_explained(client):
    fore, fh = _user(client, "todo-fore@test.local", name="Fred Foreman", role="field", trade="foreman")
    ben, bh = _user(client, "todo-ben@test.local", name="Ben Plumber", role="field", trade="plumber")
    amy, ah = _user(client, "todo-amy@test.local", name="Amy Apprentice", role="field", trade="apprentice")
    # The foreman sets the day's list for two of the crew; they're told
    r = client.post("/api/field/todos", headers=fh, json={"user_ids": [ben, amy], "texts": ["Pressure test level 2", "Clean up the slab", " "]})
    assert r.status_code == 200 and len(r.json()) == 4
    assert _notes(ben, "Fred Foreman set 2 to-dos for you today")
    # A plumber can keep his own list, but can't set one for anyone else
    assert client.post("/api/field/todos", headers=bh, json={"texts": ["Order 100 mm bends"]}).status_code == 200
    assert client.post("/api/field/todos", headers=bh, json={"user_ids": [amy], "texts": ["Sweep up"]}).status_code == 403
    mine = client.get("/api/field/todos", headers=bh).json()
    assert [t["text"] for t in mine["tasks"]] == ["Pressure test level 2", "Clean up the slab", "Order 100 mm bends"] and mine["open"] == 3
    assert mine["leads_team"] is False and client.get("/api/field/todos", headers=fh).json()["leads_team"] is True

    # Ben clocks on, then can't clock off with tasks still open
    client.post("/api/field/clock-in", headers=bh, json={})
    r = client.post("/api/field/clock-out", headers=bh, json={})
    assert r.status_code == 409 and "to-dos" in r.json()["detail"]["message"] and "Pressure test level 2" in r.json()["detail"]["message"]
    test, slab, order = mine["tasks"]
    client.patch(f"/api/field/todos/{test['id']}", headers=bh, json={"status": "done"})
    # "Couldn't finish" needs a reason, which goes back to the foreman
    assert client.patch(f"/api/field/todos/{slab['id']}", headers=bh, json={"status": "not_done", "comment": ""}).status_code == 422
    client.patch(f"/api/field/todos/{slab['id']}", headers=bh, json={"status": "not_done", "comment": "Concrete truck late, slab still wet"})
    assert _notes(fore, "slab still wet")
    # He can't delete a task the foreman set, only his own
    assert client.delete(f"/api/field/todos/{test['id']}", headers=bh).status_code == 403
    assert client.delete(f"/api/field/todos/{order['id']}", headers=bh).status_code == 204
    assert client.post("/api/field/clock-out", headers=bh, json={}).status_code == 200

    # The crew clock-off skips anyone whose list isn't finished
    client.post("/api/field/clock-in", headers=ah, json={})
    r = client.post("/api/field/crew", headers=fh, json={"user_ids": [amy], "out": True}).json()
    assert r["done"] == [] and r["skipped"] == ["Amy Apprentice"]

    # The foreman sees the whole crew's day, then carries the unfinished work to tomorrow
    team = {p["name"]: p for p in client.get("/api/field/todos/team", headers=fh).json()["people"]}
    assert team["Ben Plumber"]["done"] == 1 and team["Ben Plumber"]["not_done"] == 1 and team["Amy Apprentice"]["open"] == 2
    assert team["Ben Plumber"]["tasks"][1]["comment"] == "Concrete truck late, slab still wet"
    today = td.today()
    r = client.post("/api/field/todos/carry", headers=fh, json={"from_day": str(today), "to_day": str(today + timedelta(days=1)), "user_ids": [ben, amy]})
    assert r.json()["carried"] == 3  # Ben's slab, and both of Amy's untouched ones
    assert client.post("/api/field/todos/carry", headers=fh, json={"from_day": str(today), "to_day": str(today + timedelta(days=1)),
                                                                   "user_ids": [ben, amy]}).json()["carried"] == 0  # not twice
    tomorrow = client.get(f"/api/field/todos?day={today + timedelta(days=1)}", headers=bh).json()["tasks"]
    assert [t["text"] for t in tomorrow] == ["Clean up the slab"] and tomorrow[0]["set_by"] == "Fred Foreman"


def test_managers_and_the_office_set_lists_for_their_people(client):
    boss, bh = _user(client, "todo-boss@test.local", name="Pat Plumber", role="field", trade="plumber")
    kid, kh = _user(client, "todo-kid@test.local", name="Kid Apprentice", role="field", trade="apprentice")
    other, _ = _user(client, "todo-other@test.local", name="Other Labourer", role="field", trade="labourer")
    client.put(f"/api/people/{kid}/profile", json={"manager_id": boss})
    # A plumber with an apprentice reporting to him can set the apprentice's list, and only his
    assert client.get("/api/field/todos", headers=bh).json()["leads_team"] is True
    assert client.post("/api/field/todos", headers=bh, json={"user_ids": [kid], "texts": ["Cut and deburr the copper"]}).status_code == 200
    assert client.post("/api/field/todos", headers=bh, json={"user_ids": [other], "texts": ["x"]}).status_code == 403
    names = [p["name"] for p in client.get("/api/field/todos/team", headers=bh).json()["people"]]
    assert names == ["Pat Plumber", "Kid Apprentice"]
    # The office (an admin here) can set anyone's, for tomorrow too
    tomorrow = td.today() + timedelta(days=1)
    r = client.post("/api/field/todos", json={"user_ids": [other], "texts": ["Collect the skip permit"], "day": str(tomorrow)})
    assert r.status_code == 200 and _notes(other, "for you tomorrow")
    # Nothing on today's list: clocking off works as before
    client.post("/api/field/clock-in", headers=kh, json={})
    item = client.get("/api/field/todos", headers=kh).json()["tasks"][0]
    client.patch(f"/api/field/todos/{item['id']}", headers=kh, json={"status": "done", "comment": "Done, 40 lengths"})
    assert client.post("/api/field/clock-out", headers=kh, json={}).status_code == 200
