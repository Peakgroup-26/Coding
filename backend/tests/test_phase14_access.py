"""Phase 14: per-person access to each feature (hidden / view only / can change), with position presets."""
from app import features


def _login(client, email, password="password-123"):
    tok = client.post("/api/auth/login", json={"email": email, "password": password}).json()["token"]
    return {"Authorization": f"Bearer {tok}"}


def _user(client, email, **kw):
    r = client.post("/api/users", json={"email": email, "name": email.split("@")[0].title(), "password": "password-123", **kw})
    assert r.status_code == 200, r.text
    return r.json()["id"], _login(client, email)


def test_every_api_path_family_maps_to_the_right_feature():
    cases = {"/api/boards/3/items": "boards", "/api/jobs/5/workbook": "workbook", "/api/jobs/5/pricing": "tenders", "/api/jobs/5/costs": "purchasing",
             "/api/jobs/5/work": "live_jobs", "/api/jobs/5/chat": "assistant", "/api/people/4/pay": "hr_pay", "/api/people/4/credentials": "hr_licences",
             "/api/people/4": "hr_records", "/api/people/surveys/2": "hr_surveys", "/api/finance/wip": "finance", "/api/field/clock-in": "field_clock",
             "/api/field/me": "field_me", "/api/field/me/reviews/3": "field_me", "/api/field/plant/2/check": "field_prestart",
             "/api/supplier-prices/compare": "supplier_prices", "/api/jobs": "tenders", "/api/time-off/3": "timesheets"}
    for path, key in cases.items():
        assert features.feature_for(path) == key, path
    # Shared things every page needs stay open
    for path in ("/api/auth/me", "/api/settings", "/api/notifications", "/api/field/me/directory", "/api/field/today", "/api/jobs/5", "/api/staff",
                 "/api/sales/settings", "/api/sales/clients"):
        assert features.feature_for(path) is None, path


def test_positions_and_personal_overrides_are_enforced(client):
    pos = {p["name"]: p for p in client.get("/api/positions").json()}
    assert {"Director", "Estimator", "Supervisor", "Plumber", "Accounts"} <= set(pos)
    assert pos["Estimator"]["features"]["tenders"] == "edit" and pos["Estimator"]["features"]["finance"] == "none"
    uid, h = _user(client, "acc-est@test.local", role="estimator", can_finance=True)
    # No position: everything as before
    assert client.get("/api/finance/wip", headers=h).status_code != 403
    # Estimator preset: finance hidden, live jobs view only, boards editable
    r = client.put(f"/api/users/{uid}/access", json={"position_id": pos["Estimator"]["id"], "features": {}})
    assert r.json()["effective"]["finance"] == "none" and r.json()["effective"]["live_jobs"] == "view"
    assert client.get("/api/finance/wip", headers=h).status_code == 403
    assert client.get("/api/work", headers=h).status_code == 200
    w = client.post("/api/work", headers=h, json={"name": "Blocked drain", "sector": "maintenance", "customer_name": "X"})
    assert w.status_code == 403 and "only look" in w.json()["detail"]
    assert client.post("/api/boards", headers=h, json={"template": "blank"}).status_code == 200
    me = client.get("/api/auth/me", headers=h).json()
    assert me["access"]["finance"] == "none" and me["position_id"] == pos["Estimator"]["id"]
    # A personal change on top of the preset: this estimator can see finance
    client.put(f"/api/users/{uid}/access", json={"position_id": pos["Estimator"]["id"], "features": {"finance": "view", "boards": "none", "junk": "edit"}})
    acc = client.get(f"/api/users/{uid}/access").json()
    assert acc["features"] == {"finance": "view", "boards": "none"}
    assert client.get("/api/finance/wip", headers=h).status_code != 403
    assert client.get("/api/boards", headers=h).status_code == 403
    # Changing the preset changes everyone on it (except their own changes)
    est = pos["Estimator"]
    client.put(f"/api/positions/{est['id']}", json={"name": est["name"], "description": est["description"], "features": {**est["features"], "live_jobs": "none"}})
    assert client.get("/api/work", headers=h).status_code == 403
    row = next(r for r in client.get("/api/access/overview").json() if r["user_id"] == uid)
    assert row["position"] == "Estimator" and row["own"] == ["boards", "finance"]
    # Only admins manage it
    assert client.get("/api/positions", headers=h).status_code == 403
    assert client.put(f"/api/users/{uid}/access", headers=h, json={"features": {}}).status_code == 403


def test_phone_features_and_pay_hidden(client):
    pos = {p["name"]: p for p in client.get("/api/positions").json()}
    uid, h = _user(client, "acc-lab@test.local", role="field", trade="labourer")
    client.put(f"/api/users/{uid}/access", json={"position_id": pos["Labourer / operator"]["id"], "features": {"field_prestart": "none"}})
    assert client.get("/api/field/today", headers=h).status_code == 200
    assert client.get("/api/field/plant", headers=h).status_code == 403
    assert client.get("/api/field/me", headers=h).status_code == 200
    # An HR person who may not see pay
    hid, hh = _user(client, "acc-hr@test.local", role="estimator", can_hr=True)
    client.put(f"/api/users/{hid}/access", json={"features": {"hr_pay": "none"}})
    client.post(f"/api/people/{uid}/pay", json={"effective": "2026-01-01", "amount": 35})
    rec = client.get(f"/api/people/{uid}", headers=hh).json()
    assert rec["pay"] == [] and rec["hourly_rate"] is None and rec["see_pay"] is False
    assert client.post(f"/api/people/{uid}/pay", headers=hh, json={"effective": "2026-02-01", "amount": 36}).status_code == 403
    assert client.get(f"/api/people/{uid}").json()["hourly_rate"] == 35  # the admin still sees it


def test_sqlite_migrations_run_on_a_database_with_data(tmp_path):
    """Rebuilding users (to add position_id) must work when other tables point at users with real rows."""
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, event, text

    from app.migrate import INI, migrate

    eng = create_engine(f"sqlite:///{tmp_path}/old.db")

    @event.listens_for(eng, "connect")
    def _fk(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    cfg = Config(str(INI))
    with eng.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "0010")
        conn.execute(text("INSERT INTO users (id, email, name, role, password_hash, active, can_hydraulic, can_civil, can_all_jobs, can_past_rates,"
                          " can_pricing, can_ops, can_finance, can_hr, trade, phone, cost_rate, charge_rate, colour)"
                          " VALUES (1, 'a@b.c', 'A', 'admin', 'x', 1, 1, 1, 1, 1, 1, 1, 1, 1, '', '', 0, 0, '')"))
        conn.execute(text("INSERT INTO pay_changes (user_id, effective, pay_type, amount, position, reason, notes, created_at)"
                          " VALUES (1, '2026-01-01', 'hourly', 40, '', '', '', '2026-01-01')"))
    migrate(eng)
    with eng.connect() as conn:
        from alembic.script import ScriptDirectory

        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == ScriptDirectory.from_config(cfg).get_current_head()
        assert conn.execute(text("SELECT count(*) FROM pay_changes")).scalar() == 1
        assert conn.execute(text("PRAGMA foreign_keys")).scalar() == 1
    eng.dispose()
