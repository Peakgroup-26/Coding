from .conftest import mm, pdf_bytes


def new_job(api, **kw):
    r = api.post("/api/jobs", json={"name": "Phase 2 job", "client": "Acme", **kw})
    assert r.status_code == 200, r.text
    return r.json()


def upload(client, job_id, pages):
    r = client.post(f"/api/jobs/{job_id}/files", files=[("files", ("set.pdf", pdf_bytes(pages), "application/pdf"))])
    assert r.status_code == 200, r.text
    return r.json()


def calibrate(client, sheet_id, known=10.0, check=5.0):
    """Calibrate on the 100 mm test line and check on the 50 mm line. At 1:100 known=10, check=5."""
    r = client.post(f"/api/sheets/{sheet_id}/calibrate", json={
        "method": "two_point", "p1": [mm(100), mm(100)], "p2": [mm(200), mm(100)], "known_m": known})
    assert r.status_code == 200, r.text
    r = client.post(f"/api/sheets/{sheet_id}/verify", json={
        "p1": [mm(100), mm(150)], "p2": [mm(100), mm(200)], "known_m": check})
    assert r.json()["scale_verified"], r.text


def settings(client):
    s = client.get("/api/settings").json()
    return ({x["code"]: x for x in s["services"]}, {x["name"]: x for x in s["stages"]})


def run(client, sheet_id, service_id, dn, material, pts_mm, **kw):
    r = client.post(f"/api/sheets/{sheet_id}/runs", json={
        "service_id": service_id, "dn": dn, "material": material,
        "geometry": [[mm(x), mm(y)] for x, y in pts_mm], **kw})
    assert r.status_code == 200, r.text
    return r.json()


def count(client, sheet_id, service_id, item_type, x_mm, y_mm, **kw):
    r = client.post(f"/api/sheets/{sheet_id}/counts", json={
        "service_id": service_id, "item_type": item_type, "x": mm(x_mm), "y": mm(y_mm), **kw})
    assert r.status_code == 200, r.text
    return r.json()
