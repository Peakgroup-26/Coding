"""Phase 2 acceptance: all check-measure tests trigger on a seeded faulty job; sign-off needs every
flag resolved or accepted; a final estimate is locked."""
from app.db import SessionLocal
from app.models import Run

from .helpers import calibrate, count, new_job, run, settings, upload


def test_check_measure_on_faulty_job(client):
    services, _ = settings(client)
    san, cw = services["SAN"]["id"], services["CW"]["id"]

    # An active rule exists, but fittings haven't been generated for this job
    client.post("/api/rules", json={"name": "C gas test rule", "trigger_type": "per_metre", "formula": "m",
                                    "condition": {"service_codes": ["GAS"]}})
    b = client.post("/api/benchmarks", json={"name": "Drainage m per fixture", "service_codes": ["SAN"], "max_value": 5})
    assert b.status_code == 200, b.text

    job = new_job(client, name="Faulty job")
    jid = job["id"]
    a, bsheet, empty = upload(client, jid, [
        {"sheet_no": "H-901", "title": "SANITARY DRAINAGE PLAN GROUND"},
        {"sheet_no": "H-902", "title": "SANITARY DRAINAGE PLAN LEVEL 1"},
        {"sheet_no": "H-903", "title": "SANITARY DRAINAGE PLAN ROOF"},
    ])
    calibrate(client, a["id"])
    calibrate(client, bsheet["id"], known=10.5, check=5.25)  # self-consistent but 5% off the other 1:100 sheet

    r1 = run(client, a["id"], san, 100, "PVC DWV", [(100, 100), (200, 100)])
    r2 = run(client, a["id"], san, 80, "PVC DWV", [(200, 100), (200, 150)])  # DN100 flows into DN80
    dup = run(client, a["id"], san, 100, "PVC DWV", [(101, 100), (199, 100)])  # traced twice
    run(client, a["id"], san, 100, "PVC DWV", [(300, 100), (350, 100)], status="suggested")
    wc = count(client, a["id"], san, "WC", 300, 300)  # nothing connected
    run(client, bsheet["id"], cw, 20, "Copper", [(100, 100), (150, 100)])

    # Corrupt a stored length so the second-pass total disagrees
    with SessionLocal() as db:
        db.get(Run, r2["id"]).length_m = 4.0
        db.commit()

    flags = client.post(f"/api/jobs/{jid}/checks").json()
    by_type: dict[str, list] = {}
    for f in flags:
        by_type.setdefault(f["check_type"], []).append(f)

    assert set(by_type) >= {"no_measurements", "open_end", "fixture_unconnected", "size_jump", "scale_mismatch",
                            "benchmark", "duplicate_run", "second_pass", "unconfirmed", "fittings_missing"}, set(by_type)
    assert [f["sheet_id"] for f in by_type["no_measurements"]] == [empty["id"]]
    assert any(f["ref"] == f"run:{r1['id']}>run:{r2['id']}" for f in by_type["size_jump"])
    assert any(f["ref"] == f"count:{wc['id']}" and "drainage or water" in f["message"] for f in by_type["fixture_unconnected"])
    assert any(str(dup["id"]) in f["ref"] for f in by_type["duplicate_run"])
    assert {f["sheet_id"] for f in by_type["scale_mismatch"]} <= {a["id"], bsheet["id"]}
    assert any(f["ref"] == f"run:{r2['id']}" for f in by_type["second_pass"])
    # Flags point at a location on the drawing
    open_end = next(f for f in by_type["open_end"] if f["sheet_id"] == a["id"])  # sheet b has open ends too; order isn't fixed
    assert open_end["x"] is not None

    # Sign-off is blocked while flags are open
    assert client.post(f"/api/jobs/{jid}/finalise").status_code == 409
    # Accepting needs a note
    assert client.patch(f"/api/flags/{flags[0]['id']}", json={"status": "accepted"}).status_code == 422

    # Re-running keeps a flag's status and note while the problem is still there
    client.patch(f"/api/flags/{open_end['id']}", json={"status": "accepted", "note": "Capped for future stage"})
    again = {f["id"]: f for f in client.post(f"/api/jobs/{jid}/checks").json()}
    assert again[open_end["id"]]["status"] == "accepted" and again[open_end["id"]]["note"] == "Capped for future stage"

    # Fixing the stored length removes that flag on the next run
    client.patch(f"/api/runs/{r2['id']}", json={"note": "re-saved"})
    after_fix = client.post(f"/api/jobs/{jid}/checks").json()
    assert not any(f["check_type"] == "second_pass" for f in after_fix)

    for f in after_fix:
        if f["status"] == "open":
            assert client.patch(f"/api/flags/{f['id']}", json={"status": "accepted", "note": "Reviewed"}).status_code == 200
    r = client.post(f"/api/jobs/{jid}/finalise")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "final" and r.json()["signed_off_by"] is not None

    # Final estimates are locked
    assert client.post(f"/api/sheets/{a['id']}/counts", json={"service_id": san, "item_type": "WC", "x": 10, "y": 10}).status_code == 409
    assert client.post(f"/api/jobs/{jid}/generate").status_code == 409
    assert client.patch(f"/api/jobs/{jid}", json={"name": "renamed"}).status_code == 409

    assert client.post(f"/api/jobs/{jid}/reopen").json()["status"] == "draft"
    assert client.post(f"/api/sheets/{a['id']}/counts", json={"service_id": san, "item_type": "WC", "x": 10, "y": 10}).status_code == 200

    # Audit trail includes the deleted and edited items for this job
    client.delete(f"/api/runs/{dup['id']}")
    audit = client.get(f"/api/jobs/{jid}/audit").json()
    actions = {(e["entity"], e["action"]) for e in audit}
    assert {("run", "delete"), ("job", "finalise"), ("job", "reopen"), ("flag", "update"), ("job", "check_measure")} <= actions


def test_estimator_cannot_sign_off(client):
    from fastapi.testclient import TestClient

    from app.main import app
    client.post("/api/users", json={"email": "est2@test.local", "role": "estimator", "password": "estimator-pw"})
    anon = TestClient(app)
    tok = anon.post("/api/auth/login", json={"email": "est2@test.local", "password": "estimator-pw"}).json()["token"]
    job = new_job(client, name="Clean job")
    r = anon.post(f"/api/jobs/{job['id']}/finalise", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 403
