"""Phase 5 acceptance: revision compare highlights added and removed runs between two revisions of a
test sheet. Also carry-forward, the marked-up PDF and Microsoft 365 sign-on."""
import time
import urllib.parse

import jwt
import pymupdf
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app import sso
from app.db import SessionLocal
from app.models import Sheet
from app.revision import raster_diff

from .conftest import make_sheet_page, mm
from .helpers import calibrate, new_job, run, settings

BROWN = (0.55, 0.27, 0.07)


def _rev(rev: str, lines) -> bytes:
    doc = pymupdf.open()
    page = make_sheet_page(doc, "H-700", "SANITARY DRAINAGE PLAN", rev=rev)
    for a, b in lines:
        page.draw_line((mm(a[0]), mm(a[1])), (mm(b[0]), mm(b[1])), color=BROWN, width=2)
    data = doc.tobytes()
    doc.close()
    return data


REV_A = [((100, 300), (200, 300)), ((200, 300), (200, 350)), ((300, 300), (360, 300))]
# Rev B: the 5 m leg at x=200 is gone, the 6 m run at y=300 is unchanged, and a new 8 m run appears.
REV_B = [((100, 300), (200, 300)), ((300, 300), (360, 300)), ((400, 380), (480, 380))]


@pytest.fixture(scope="module")
def revs(client):
    job = new_job(client, name="Revision job")
    a = client.post(f"/api/jobs/{job['id']}/files", files=[("files", ("a.pdf", _rev("A", REV_A), "application/pdf"))]).json()[0]
    calibrate(client, a["id"])
    services, _ = settings(client)
    san = services["SAN"]["id"]
    leg = run(client, a["id"], san, 100, "PVC DWV", [(100, 300), (200, 300), (200, 350)])  # on the changed line work
    other = run(client, a["id"], san, 100, "PVC DWV", [(300, 300), (360, 300)])  # untouched
    client.post(f"/api/sheets/{a['id']}/counts", json={"service_id": san, "item_type": "WC", "x": mm(360), "y": mm(300)})
    b = client.post(f"/api/jobs/{job['id']}/files", files=[("files", ("b.pdf", _rev("B", REV_B), "application/pdf"))]).json()[0]
    return {"job": job, "a": a, "b": b, "leg": leg, "other": other, "san": san}


def test_new_revision_supersedes_old(client, revs):
    sheets = {s["id"]: s for s in client.get(f"/api/jobs/{revs['job']['id']}/sheets?include_duplicates=true").json()}
    assert sheets[revs["b"]["id"]]["is_current"] and not sheets[revs["a"]["id"]]["is_current"]
    revisions = client.get(f"/api/sheets/{revs['b']['id']}/revisions").json()
    assert [r["revision"] for r in revisions] == ["A", "B"] and revisions[0]["runs"] == 2


def test_compare_highlights_added_and_removed(client, revs):
    d = client.get(f"/api/sheets/{revs['b']['id']}/compare").json()
    assert d["method"] == "vector" and d["old_revision"] == "A" and d["new_revision"] == "B"
    brown = "#8c4512"
    added = [p for p in d["added"] if p["colour"] == brown]
    removed = [p for p in d["removed"] if p["colour"] == brown]
    assert len(added) == 1 and len(removed) == 1
    assert added[0]["points"][0][1] == pytest.approx(mm(380), abs=0.5)  # the new 8 m run
    assert {round(p[0] / mm(1)) for p in removed[0]["points"]} == {200}  # the deleted leg at x=200
    assert d["added_length_pt"] == pytest.approx(mm(80), abs=1) and d["removed_length_pt"] == pytest.approx(mm(50), abs=2)  # less the join tolerance
    assert len(d["regions"]) == 2
    # The run measured along the deleted leg is flagged; the untouched one isn't
    affected = {a["run_id"] for a in d["affected_runs"]}
    assert revs["leg"]["id"] in affected and revs["other"]["id"] not in affected
    assert d["unmeasured_new_work"] is True


def test_carry_forward(client, revs):
    b = revs["b"]["id"]
    assert client.post(f"/api/sheets/{b}/carry-forward", json={}).status_code == 409  # scale not verified yet
    calibrate(client, b)
    r = client.post(f"/api/sheets/{b}/carry-forward", json={}).json()
    assert r["runs"] == 2 and r["counts"] == 1 and r["on_changed_line_work"] == 1 and r["from_revision"] == "A"
    runs = client.get(f"/api/sheets/{b}/runs").json()
    assert all(x["status"] == "suggested" and x["source"] == "carried" for x in runs)
    assert sum("line work changed" in x["note"] for x in runs) == 1
    # Running it again doesn't duplicate anything
    assert client.post(f"/api/sheets/{b}/carry-forward", json={}).json()["runs"] == 0


def test_raster_compare_for_scanned_sheets(client, revs):
    with SessionLocal() as db:
        old, new = db.get(Sheet, revs["a"]["id"]), db.get(Sheet, revs["b"]["id"])
        d = raster_diff(old, new)
    assert d["method"] == "image" and d["added"] and d["removed"]
    # Changed areas sit around the new run (y = 380 mm) and the removed leg (x = 200 mm)
    assert any(min(p[1] for p in r["points"]) <= mm(380) <= max(p[1] for p in r["points"]) for r in d["added"])
    assert any(min(p[0] for p in r["points"]) <= mm(200) <= max(p[0] for p in r["points"]) for r in d["removed"])


def test_markup_pdf(client, revs):
    r = client.get(f"/api/jobs/{revs['job']['id']}/markup.pdf")
    assert r.status_code == 200 and r.content[:5] == b"%PDF-"
    doc = pymupdf.open(stream=r.content, filetype="pdf")
    assert doc.page_count == 2  # cover + the current sheet with measurements (Rev A is superseded)
    assert "Revision job" in doc[0].get_text()
    text = doc[1].get_text()
    assert "take-off mark-up" in text and "Dashed / hollow = suggested" in text
    doc.close()


# --- Microsoft 365 sign-on ---
@pytest.fixture
def sso_env(monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setenv("SSO_TENANT_ID", "tenant-1")
    monkeypatch.setenv("SSO_CLIENT_ID", "client-1")
    monkeypatch.setenv("SSO_CLIENT_SECRET", "secret")
    monkeypatch.setenv("SSO_ALLOWED_DOMAINS", "peakpcg.com.au")
    monkeypatch.setattr(sso, "signing_key", lambda token: key.public_key())
    issued = {}

    def token_for(email, nonce, **over):
        claims = {"iss": "https://login.microsoftonline.com/tenant-1/v2.0", "aud": "client-1", "iat": int(time.time()),
                  "exp": int(time.time()) + 600, "nonce": nonce, "preferred_username": email, **over}
        return jwt.encode(claims, key, algorithm="RS256")

    def fake_exchange(code, verifier):
        issued["verifier"] = verifier
        return token_for(*code.split("|"))

    monkeypatch.setattr(sso, "exchange_code", fake_exchange)
    return issued


def _start(anon):
    r = anon.get("/api/auth/sso/start", follow_redirects=False)
    assert r.status_code == 302
    q = urllib.parse.parse_qs(urllib.parse.urlparse(r.headers["location"]).query)
    assert q["code_challenge_method"] == ["S256"] and q["client_id"] == ["client-1"]
    return q["state"][0], sso._unsign(r.cookies["peak_sso"])["nonce"]


def _callback(anon, code, state):
    r = anon.get(f"/api/auth/sso/callback?code={urllib.parse.quote(code)}&state={state}", follow_redirects=False)
    assert r.status_code == 302
    return dict(urllib.parse.parse_qsl(urllib.parse.urlparse(r.headers["location"]).fragment))


def test_sso_signs_in_existing_user(client, sso_env):
    from fastapi.testclient import TestClient

    from app.main import app
    client.post("/api/users", json={"email": "joel@peakpcg.com.au", "name": "Joel", "role": "reviewer", "password": "unused-pass"})
    anon = TestClient(app)
    assert anon.get("/api/auth/sso").json()["enabled"] is True
    state, nonce = _start(anon)
    out = _callback(anon, f"Joel@PeakPCG.com.au|{nonce}", state)
    assert "token" in out, out
    me = anon.get("/api/auth/me", headers={"Authorization": f"Bearer {out['token']}"}).json()
    assert me["email"] == "joel@peakpcg.com.au" and me["role"] == "reviewer"


def test_sso_refusals(client, sso_env):
    from fastapi.testclient import TestClient

    from app.main import app
    anon = TestClient(app)
    state, nonce = _start(anon)
    assert "doesn't have an account" in _callback(anon, f"nobody@peakpcg.com.au|{nonce}", state)["sso_error"]
    state, nonce = _start(anon)
    assert "domain" in _callback(anon, f"someone@gmail.com|{nonce}", state)["sso_error"]
    state, _ = _start(anon)
    assert "doesn't match" in _callback(anon, "joel@peakpcg.com.au|wrong-nonce", state)["sso_error"]
    _start(anon)
    assert "try again" in _callback(anon, "joel@peakpcg.com.au|x", "forged-state")["sso_error"]


def test_sso_off_by_default(client):
    assert client.get("/api/auth/sso").json()["enabled"] is False
    assert client.get("/api/auth/sso/start", follow_redirects=False).status_code == 404
