"""Phase 2 acceptance: each generated item traces to its rule and source; stage totals reconcile."""
import pytest

from .helpers import calibrate, count, new_job, run, settings, upload


def _rule(client, **body):
    r = client.post("/api/rules", json=body)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture(scope="module")
def drainage_job(client):
    """A DN100 main with one 90° change of direction (10 m + 5 m), a 3 m DN100 branch from a WC
    joining the main part-way along, and a CW run to the WC."""
    services, stages = settings(client)
    job = new_job(client, name="Rules job")
    sheet = upload(client, job["id"], [{"sheet_no": "H-801", "title": "SANITARY DRAINAGE PLAN"}])[0]
    calibrate(client, sheet["id"])
    san, cw = services["SAN"]["id"], services["CW"]["id"]
    main = run(client, sheet["id"], san, 100, "PVC DWV", [(100, 100), (200, 100), (200, 150)])
    branch = run(client, sheet["id"], san, 100, "PVC DWV", [(150, 130), (150, 100)])
    water = run(client, sheet["id"], cw, 20, "Copper", [(170, 130), (150, 130)])
    wc = count(client, sheet["id"], san, "WC", 150, 130)
    rules = {
        "bend": _rule(client, name="T SAN 88 bends", trigger_type="per_bend", formula="n",
                      condition={"service_codes": ["SAN"], "angle_min": 67.5, "angle_max": 95},
                      output_description="{material} DN{dn} 88° bend"),
        "junction": _rule(client, name="T SAN junctions", trigger_type="per_branch", formula="n",
                          condition={"service_codes": ["SAN"]}, output_description="{material} DN{main_dn} x DN{branch_dn} junction"),
        "clips": _rule(client, name="T SAN clips", trigger_type="per_metre", formula="ceil(m / 1.2)",
                       condition={"service_codes": ["SAN"], "dn_min": 80}, output_description="DN{dn} pipe clip",
                       stage_id=stages["Rough-in"]["id"]),
        "pan": _rule(client, name="T WC pan connector", trigger_type="per_fixture", formula="n",
                     condition={"item_types": ["WC"]}, output_description="Pan connector"),
        "io": _rule(client, name="T SAN IOs", trigger_type="per_io", formula="n",
                    condition={"service_codes": ["SAN"], "io_at_ends": True, "io_interval_m": 30},
                    output_description="DN{dn} inspection opening"),
        "glue": _rule(client, name="T SAN solvent cement", trigger_type="per_job", formula="ceil(m / 50)",
                      condition={"service_codes": ["SAN"]}, output_description="Solvent cement 500 mL", uom="tin",
                      stage_id=stages["Under slab"]["id"]),
    }
    r = client.post(f"/api/jobs/{job['id']}/generate")
    assert r.status_code == 200 and r.json()["errors"] == [], r.text
    return {"job": job, "sheet": sheet, "main": main, "branch": branch, "water": water, "wc": wc,
            "rules": rules, "stages": stages, "services": services}


def _lines(client, d, rule_key):
    rid = d["rules"][rule_key]["id"]
    return [g for g in client.get(f"/api/jobs/{d['job']['id']}/generated").json() if g["rule_id"] == rid]


def test_bends_from_polyline_vertices(client, drainage_job):
    d = drainage_job
    [line] = _lines(client, d, "bend")
    assert line["description"] == "PVC DWV DN100 88° bend"
    assert line["qty"] == 1 and line["source_ref"] == f"run:{d['main']['id']}"
    assert line["stage_id"] == d["stages"]["Under slab"]["id"]  # takes the run's stage


def test_branch_junction(client, drainage_job):
    d = drainage_job
    [line] = _lines(client, d, "junction")
    assert line["source_ref"] == f"run:{d['branch']['id']}"
    assert line["description"] == "PVC DWV DN100 x DN100 junction" and line["qty"] == 1


def test_per_metre_with_rule_stage(client, drainage_job):
    d = drainage_job
    by_src = {g["source_ref"]: g for g in _lines(client, d, "clips")}
    assert by_src[f"run:{d['main']['id']}"]["qty"] == 13  # ceil(15 / 1.2)
    assert by_src[f"run:{d['main']['id']}"]["source_qty"] == pytest.approx(15)
    assert by_src[f"run:{d['branch']['id']}"]["qty"] == 3  # ceil(3 / 1.2)
    assert all(g["stage_id"] == d["stages"]["Rough-in"]["id"] for g in by_src.values())
    assert f"run:{d['water']['id']}" not in by_src  # CW excluded by service filter


def test_per_fixture_and_per_job(client, drainage_job):
    d = drainage_job
    [pan] = _lines(client, d, "pan")
    assert pan["source_ref"] == f"count:{d['wc']['id']}" and pan["stage_id"] == d["stages"]["Fit-off"]["id"]
    [glue] = _lines(client, d, "glue")
    assert glue["source_ref"] == "job" and glue["qty"] == 1 and glue["uom"] == "tin" and glue["source_qty"] == pytest.approx(18)


def test_io_at_free_ends(client, drainage_job):
    d = drainage_job
    by_src = {g["source_ref"]: g["qty"] for g in _lines(client, d, "io")}
    # Main: both ends free. Branch: start free (at the WC), end joins the main.
    assert by_src == {f"run:{d['main']['id']}": 2, f"run:{d['branch']['id']}": 1}


def test_overrides_survive_regeneration_and_rule_edits(client, drainage_job):
    d = drainage_job
    jid = d["job"]["id"]
    main_clips = next(g for g in _lines(client, d, "clips") if g["source_ref"] == f"run:{d['main']['id']}")
    r = client.patch(f"/api/generated/{main_clips['id']}", json={"overridden_qty": 20, "note": "Extra hangers at bulkhead"})
    assert r.status_code == 200
    # Edit the rule: version goes up, regenerate keeps the override and recomputes the generated qty
    rule = d["rules"]["clips"]
    upd = client.put(f"/api/rules/{rule['id']}", json={**{k: rule[k] for k in ("name", "trigger_type", "condition", "output_description", "stage_id")},
                                                        "formula": "ceil(m / 1.5)"}).json()
    assert upd["version"] == 2
    client.post(f"/api/jobs/{jid}/generate")
    again = next(g for g in _lines(client, d, "clips") if g["source_ref"] == f"run:{d['main']['id']}")
    assert again["id"] == main_clips["id"] and again["overridden_qty"] == 20 and again["qty"] == 10 and again["rule_version"] == 2
    assert again["note"] == "Extra hangers at bulkhead"
    # Rule-generated lines can't be deleted, only zeroed
    assert client.delete(f"/api/generated/{again['id']}").status_code == 409


def test_manual_line_and_summary(client, drainage_job):
    d = drainage_job
    jid = d["job"]["id"]
    r = client.post(f"/api/jobs/{jid}/generated", json={"description": "Core hole 100", "uom": "ea", "qty": 2,
                                                         "stage_id": d["stages"]["Rough-in"]["id"]})
    assert r.status_code == 200
    summary = client.get(f"/api/jobs/{jid}/fittings-summary").json()
    assert "AS/NZS 3500" in summary["disclaimer"]
    descs = {(row["stage"], row["description"]): row["qty"] for row in summary["rows"]}
    assert descs[("Rough-in", "Core hole 100")] == 2
    assert descs[("Rough-in", "DN100 pipe clip")] == 20 + 2  # override (20) + branch (ceil(3/1.5)=2)


def test_stage_matrix_reconciles(client, drainage_job):
    m = client.get(f"/api/jobs/{drainage_job['job']['id']}/stage-matrix").json()
    for code in m["services"]:
        assert sum(r["cells"].get(code, 0) for r in m["rows"]) == pytest.approx(m["service_totals"][code])
    assert sum(r["total_m"] for r in m["rows"]) == pytest.approx(m["grand_total_m"])


def test_invalid_rules_rejected(client):
    assert client.post("/api/rules", json={"name": "x", "trigger_type": "per_metre", "formula": "import os"}).status_code == 422
    assert client.post("/api/rules", json={"name": "x", "trigger_type": "per_banana", "formula": "n"}).status_code == 422
    assert client.post("/api/rules", json={"name": "x", "trigger_type": "per_io", "formula": "n"}).status_code == 422


def test_rules_csv_round_trip(client, drainage_job):
    csv_text = client.get("/api/rules/export.csv").text
    assert csv_text.splitlines()[0].startswith("name,trigger_type,service_codes")
    assert "T SAN clips" in csv_text
    new_csv = ("name,trigger_type,service_codes,materials,dn_min,dn_max,item_types,angle_min,angle_max,io_at_ends,io_at_bends,io_interval_m,formula,output_description,uom,stage,active\n"
               "T CSV bends 45,per_bend,SAN,PVC DWV,,,,22.5,67.5,,,,n,{material} DN{dn} 45° bend,ea,,yes\n"
               "T bad row,per_metre,SAN,,,,,,,,,,m +,,ea,,yes\n"
               "T bad stage,per_metre,SAN,,,,,,,,,,m,,ea,Nowhere,yes\n")
    r = client.post("/api/rules/import", files={"file": ("rules.csv", new_csv.encode(), "text/csv")})
    body = r.json()
    assert body["created"] == 1 and len(body["errors"]) == 2, body
    rules = {x["name"]: x for x in client.get("/api/rules").json()}
    assert rules["T CSV bends 45"]["condition"]["angle_min"] == 22.5
