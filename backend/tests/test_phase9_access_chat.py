"""Phase 9: permissions, the AI chat panel with tools, and the AI's memory. No real AI calls."""
from types import SimpleNamespace

import pytest

from app import ai, chat

from .test_phase7_autopilot import FakeReader, _plan_pdf
from .test_phase7_civil import _civil_pdf


def _user(client, email, **perms):
    r = client.post("/api/users", json={"email": email, "name": email.split("@")[0], "password": "password-123", **perms})
    assert r.status_code == 200, r.text
    tok = client.post("/api/auth/login", json={"email": email, "password": "password-123"}).json()["token"]
    return {"Authorization": f"Bearer {tok}"}


def _start(client, kind, pdf, name, headers=None, client_name="Perm Co"):
    return client.post("/api/quick-start", data={"kind": kind, "name": name, "client": client_name},
                       files=[("files", ("set.pdf", pdf, "application/pdf"))], headers=headers or {})


def test_permissions_limit_what_people_see(client):
    admin_hyd = _start(client, "hydraulic", _plan_pdf(), "Admin plumbing job").json()
    admin_civ = _start(client, "civil", _civil_pdf(), "Admin civil job").json()
    civil_only = _user(client, "civil@test.local", can_hydraulic=False, can_all_jobs=False, can_past_rates=False)
    civil_team = _user(client, "civilteam@test.local", can_hydraulic=False, can_all_jobs=True)

    # Civil-only, own jobs only: can't see the admin's jobs at all, or reach them by id.
    assert client.get("/api/jobs", headers=civil_only).json() == []
    for url in (f"/api/jobs/{admin_hyd['id']}", f"/api/jobs/{admin_hyd['id']}/sheets", f"/api/jobs/{admin_civ['id']}/civil/boq"):
        assert client.get(url, headers=civil_only).status_code == 404, url
    sheet_id = client.get(f"/api/jobs/{admin_hyd['id']}/sheets").json()[0]["id"]
    assert client.get(f"/api/sheets/{sheet_id}", headers=civil_only).status_code == 404
    assert client.get(f"/api/sheets/{sheet_id}/runs", headers=civil_only).status_code == 404
    assert _start(client, "hydraulic", _plan_pdf(), "Nope", civil_only).status_code == 403
    assert client.get("/api/civil/rate-sets", headers=civil_only).status_code == 403
    own = _start(client, "civil", _civil_pdf(), "My civil job", civil_only).json()
    assert [j["name"] for j in client.get("/api/jobs", headers=civil_only).json()] == ["My civil job"]
    assert client.get(f"/api/jobs/{own['id']}/civil/boq", headers=civil_only).status_code == 200

    # Civil team (everyone's jobs, civil only): sees all civil jobs but no plumbing.
    names = {j["name"] for j in client.get("/api/jobs", headers=civil_team).json()}
    assert {"Admin civil job", "My civil job"} <= names and "Admin plumbing job" not in names
    assert client.get(f"/api/jobs/{admin_civ['id']}", headers=civil_team).status_code == 200
    assert client.get(f"/api/jobs/{admin_hyd['id']}", headers=civil_team).status_code == 404

    # The admin sees everything, and can filter by kind.
    kinds = {j["kind"] for j in client.get("/api/jobs?kind=civil").json()}
    assert kinds == {"civil"}
    me = client.get("/api/auth/me", headers=civil_only).json()
    assert me["can_hydraulic"] is False and me["can_civil"] is True

    # Admins change permissions; people change their own password.
    uid = me["id"]
    assert client.patch(f"/api/users/{uid}", json={"can_all_jobs": True}).json()["can_all_jobs"] is True
    assert client.post("/api/auth/password", json={"current_password": "wrong", "new_password": "newpass-123"}, headers=civil_only).status_code == 403
    assert client.post("/api/auth/password", json={"current_password": "password-123", "new_password": "newpass-123"}, headers=civil_only).status_code == 204
    assert client.post("/api/auth/login", json={"email": "civil@test.local", "password": "newpass-123"}).status_code == 200
    assert client.patch(f"/api/users/{uid}", json={"can_pricing": False}, headers=civil_only).status_code == 403  # not an admin


class ScriptedChat:
    """Plays back a script of model turns, and records exactly what was sent."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []
        self.summaries = []

    def respond(self, system, tools, messages):
        self.calls.append({"system": system, "tools": [t["name"] for t in tools], "messages": [dict(m) for m in messages]})
        step = self.script.pop(0)
        return step(messages) if callable(step) else step

    def summarise(self, prompt):
        self.summaries.append(prompt)
        return "Earlier: changed sanitary to DN150."


def _tool(id_, name, **inp):
    return ("tool_use", [{"type": "thinking", "thinking": "", "signature": f"sig-{id_}"},
                         {"type": "tool_use", "id": id_, "name": name, "input": inp}], "fake")


def _say(text):
    return ("end_turn", [{"type": "text", "text": text}], "fake")


@pytest.fixture
def reader():
    fake = FakeReader()
    ai.set_reader(fake)
    yield fake
    ai.set_reader(None)


def test_chat_changes_the_takeoff_and_remembers(client, reader):
    job = _start(client, "hydraulic", _plan_pdf(), "Chat job", client_name="Chatty Consultants").json()
    runs = client.get(f"/api/sheets/{client.get(f'/api/jobs/{job['id']}/sheets').json()[0]['id']}/runs").json()
    assert {r["dn"] for r in runs} == {100}

    # Off without a model.
    assert client.get(f"/api/jobs/{job['id']}/chat").json()["enabled"] is False
    assert client.post(f"/api/jobs/{job['id']}/chat", json={"text": "hi"}).status_code == 503

    fake = ScriptedChat([
        _tool("t1", "change_runs", service_code="SAN", set_service_code="", set_dn=150, set_material=""),
        _tool("t2", "remember", text="Chatty Consultants' sanitary drains are DN150 unless marked otherwise.", scope="client"),
        _tool("t3", "change_runs", service_code="XYZ", set_service_code="", set_dn=150, set_material=""),  # a mistake
        _say("Done. I've changed the 2 sanitary runs to DN150 and I'll remember that for Chatty Consultants."),
        _tool("t4", "approve_takeoff", what="runs", sheet_id=0),
        _say("Approved."),
    ])
    chat.set_model(fake)
    try:
        r = client.post(f"/api/jobs/{job['id']}/chat", json={"text": "Make all the sanitary DN150, and remember that for this consultant"})
        assert r.status_code == 200, r.text
        out = r.json()
        assert out["changed"] is True
        texts = [m["text"] for m in out["messages"]]
        assert texts[0].startswith("Make all the sanitary") and texts[-1].startswith("Done.")
        actions = [a["summary"] for m in out["messages"] for a in m["actions"]]
        assert actions == ["Changed 2 run(s) to DN150",
                           "Remembered (client): Chatty Consultants' sanitary drains are DN150 unless marked otherwise."]
        assert {r["dn"] for r in client.get(f"/api/sheets/{runs[0]['sheet_id']}/runs").json()} == {150}

        # The mistake went back to the AI as an error, and the conversation carried on.
        third = fake.calls[3]["messages"][-1]["content"][0]
        assert third["is_error"] and "Unknown service code XYZ" in third["content"]

        # Every call had the same system prompt and tools, and each history extended the last one unchanged.
        assert len({c["system"] for c in fake.calls}) == 1
        for a, b in zip(fake.calls, fake.calls[1:]):
            assert b["messages"][:len(a["messages"])] == a["messages"]
        assert "<job_state>" in fake.calls[0]["messages"][0]["content"][0]["text"]
        assert "take_off_line_style" in fake.calls[0]["tools"] and "add_boq_line" not in fake.calls[0]["tools"]

        # A second message continues the same conversation.
        client.post(f"/api/jobs/{job['id']}/chat", json={"text": "Approve the runs"})
        assert fake.calls[-1]["messages"][:len(fake.calls[3]["messages"])] == fake.calls[3]["messages"]
        assert {r["status"] for r in client.get(f"/api/sheets/{runs[0]['sheet_id']}/runs").json()} == {"confirmed"}

        # The chat history is there for everyone who opens the job.
        shown = client.get(f"/api/jobs/{job['id']}/chat").json()["messages"]
        assert [(m["role"], bool(m["actions"])) for m in shown] == [
            ("user", False), ("assistant", True), ("assistant", True), ("assistant", False),  # the failed call isn't shown
            ("user", False), ("assistant", True), ("assistant", False)]
        assert shown[0]["user"] == "Admin"
        audit = client.get(f"/api/jobs/{job['id']}/audit").json()
        assert any(a["action"] == "update" and a["entity"] == "run" for a in audit)
    finally:
        chat.set_model(None)

    # The memory is in the admin list, feeds the next job for that client, and the next conversation.
    mems = client.get("/api/memories").json()
    mem = next(m for m in mems if "DN150" in m["text"])
    assert mem["scope"] == "client" and mem["client"] == "Chatty Consultants"
    job2 = _start(client, "hydraulic", _plan_pdf("H-301"), "Next chatty job", client_name="Chatty Consultants").json()
    assert "DN150" in reader.context
    fake2 = ScriptedChat([_say("Hello.")])
    chat.set_model(fake2)
    try:
        client.post(f"/api/jobs/{job2['id']}/chat", json={"text": "hello"})
        assert "DN150 unless marked otherwise" in fake2.calls[0]["system"]
    finally:
        chat.set_model(None)
    # Admins can switch a memory off.
    assert client.patch(f"/api/memories/{mem['id']}", json={"active": False}).status_code == 200
    assert not [m for m in client.get("/api/memories").json() if m["id"] == mem["id"]]


def test_long_conversations_are_summarised(client, reader, monkeypatch):
    job = _start(client, "hydraulic", _plan_pdf(), "Long chat").json()
    fake = ScriptedChat([_say("one"), _say("two")])
    chat.set_model(fake)
    monkeypatch.setattr(chat, "MAX_SESSION_CHARS", 50)
    try:
        client.post(f"/api/jobs/{job['id']}/chat", json={"text": "first"})
        client.post(f"/api/jobs/{job['id']}/chat", json={"text": "second"})
        assert fake.summaries and "first" in fake.summaries[0]
        assert "Earlier: changed sanitary to DN150." in fake.calls[1]["system"]
        assert len(fake.calls[1]["messages"]) == 1  # a fresh session
        shown = client.get(f"/api/jobs/{job['id']}/chat").json()["messages"]
        assert shown[0]["role"] == "note"
    finally:
        chat.set_model(None)


def test_civil_chat_tools(client):
    ai.set_reader(None)
    job = _start(client, "civil", _civil_pdf(), "Civil chat").json()
    fake = ScriptedChat([
        _tool("c1", "add_boq_line", category="Kerb and channel", description="Kerb and channel type B", unit="m", qty=120, rate=85),
        lambda msgs: _tool("c2", "change_boq_line", line_id=_last_line(client, job["id"]), qty=130, rate=-1, approve=True),
        _say("Added the kerb at 130 m and approved it."),
    ])
    chat.set_model(fake)
    try:
        client.post(f"/api/jobs/{job['id']}/chat", json={"text": "add 120 m of kerb at $85, actually make it 130 and approve it"})
    finally:
        chat.set_model(None)
    boq = client.get(f"/api/jobs/{job['id']}/civil/boq").json()
    line = boq["lines"][-1]
    assert line["effective_qty"] == 130 and line["rate"] == 85 and line["status"] == "confirmed"
    assert boq["summary"]["total_confirmed_ex_gst"] == pytest.approx(130 * 85)
    assert "take_off_line_style" not in fake.calls[0]["tools"]


def _last_line(client, job_id):
    return client.get(f"/api/jobs/{job_id}/civil/boq").json()["lines"][-1]["id"]


def test_claude_chat_request_shape():
    import anthropic

    from app.chat import ClaudeChat

    c = ClaudeChat.__new__(ClaudeChat)
    c.anthropic, c.model = anthropic, "claude-opus-5-5"
    sent = {}

    class Block(SimpleNamespace):
        def to_dict(self):
            return dict(self.__dict__)

    def create(**kw):
        sent.update(kw)
        return SimpleNamespace(stop_reason="end_turn", model="claude-opus-5-5", content=[Block(type="text", text="hi")])

    c.client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=create)))
    stop, content, _ = c.respond("sys", [{"name": "t"}], [{"role": "user", "content": "x"}])
    assert stop == "end_turn" and content == [{"type": "text", "text": "hi"}]
    assert sent["system"] == "sys" and sent["fallbacks"] == "default"
    assert "thinking-binding-controls-2026-08-01" in sent["betas"]
    assert sent["thinking"]["block_binding"]["prefix_mismatch_behavior"] == "drop_block"
    assert sent["cache_control"] == {"type": "ephemeral"}
