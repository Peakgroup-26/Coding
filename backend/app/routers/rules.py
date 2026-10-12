"""Admin: fitting and sundry rules, the materials catalogue, and check-measure benchmarks."""
import csv
import io

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..audit import record, snapshot
from ..auth import current_user, require_admin
from ..db import get_db
from ..expr import FormulaError, validate
from ..models import Benchmark, CatalogueItem, Rule, Stage, User
from ..rules import DISCLAIMER, TRIGGERS
from ..schemas import (BenchmarkIn, BenchmarkOut, CatalogueItemIn, CatalogueItemOut, RuleCondition, RuleIn,
                       RuleOut)
from . import get_or_404

router = APIRouter(prefix="/api", tags=["rules"])

CSV_COLUMNS = ["name", "trigger_type", "service_codes", "materials", "dn_min", "dn_max", "item_types",
               "angle_min", "angle_max", "io_at_ends", "io_at_bends", "io_interval_m",
               "formula", "output_description", "uom", "stage", "active"]


def _check_rule(db: Session, body: RuleIn) -> None:
    if body.trigger_type not in TRIGGERS:
        raise HTTPException(422, f"Trigger must be one of {', '.join(TRIGGERS)}")
    try:
        validate(body.formula)
    except FormulaError as e:
        raise HTTPException(422, f"Formula: {e}")
    if body.stage_id is not None:
        get_or_404(db, Stage, body.stage_id)
    if body.output_item_id is not None:
        get_or_404(db, CatalogueItem, body.output_item_id)
    if body.trigger_type == "per_io":
        c = body.condition
        if not (c.io_at_ends or c.io_at_bends or (c.io_interval_m or 0) > 0):
            raise HTTPException(422, "An IO rule needs at least one of: at ends, at bends, or an interval")


@router.get("/rules", response_model=list[RuleOut])
def list_rules(db: Session = Depends(get_db), _: User = Depends(current_user)):
    return db.scalars(select(Rule).order_by(Rule.trigger_type, Rule.name)).all()


@router.get("/rules/meta")
def rules_meta(_: User = Depends(current_user)):
    return {"triggers": TRIGGERS, "disclaimer": DISCLAIMER}


@router.post("/rules", response_model=RuleOut)
def create_rule(body: RuleIn, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    _check_rule(db, body)
    rule = Rule(**body.model_dump())
    db.add(rule)
    db.flush()
    record(db, user.id, "rule", rule.id, "create", after=snapshot(rule))
    db.commit()
    return rule


@router.put("/rules/{rule_id}", response_model=RuleOut)
def update_rule(rule_id: int, body: RuleIn, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    rule = get_or_404(db, Rule, rule_id)
    _check_rule(db, body)
    before = snapshot(rule)
    for k, v in body.model_dump().items():
        setattr(rule, k, v)
    rule.version += 1
    record(db, user.id, "rule", rule.id, "update", before, snapshot(rule))
    db.commit()
    return rule


@router.delete("/rules/{rule_id}", status_code=204)
def delete_rule(rule_id: int, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    """Generated lines from this rule stay on existing jobs (rule link cleared) until they're regenerated."""
    rule = get_or_404(db, Rule, rule_id)
    record(db, user.id, "rule", rule.id, "delete", before=snapshot(rule))
    db.delete(rule)
    db.commit()


def _list(v: str) -> list[str]:
    return [x.strip() for x in (v or "").replace(";", ",").split(",") if x.strip()]


def _num(v: str):
    v = (v or "").strip()
    return float(v) if v else None


def _bool(v: str) -> bool:
    return (v or "").strip().lower() in ("1", "true", "yes", "y")


@router.get("/rules/export.csv")
def export_rules(db: Session = Depends(get_db), _: User = Depends(current_user)):
    stages = {s.id: s.name for s in db.scalars(select(Stage))}
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(CSV_COLUMNS)
    for r in db.scalars(select(Rule).order_by(Rule.trigger_type, Rule.name)):
        c = r.condition or {}
        w.writerow([r.name, r.trigger_type, ", ".join(c.get("service_codes") or []), ", ".join(c.get("materials") or []),
                    c.get("dn_min") or "", c.get("dn_max") or "", ", ".join(c.get("item_types") or []),
                    "" if c.get("angle_min") is None else c["angle_min"], "" if c.get("angle_max") is None else c["angle_max"],
                    "yes" if c.get("io_at_ends") else "", "yes" if c.get("io_at_bends") else "", c.get("io_interval_m") or "",
                    r.formula, r.output_description, r.uom, stages.get(r.stage_id, ""), "yes" if r.active else "no"])
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="peak_fitting_rules.csv"'})


@router.post("/rules/import")
async def import_rules(file: UploadFile = File(...), db: Session = Depends(get_db), user: User = Depends(require_admin)):
    """Add or update rules from a CSV (matched by name). Rows with errors are skipped and reported."""
    text = (await file.read()).decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    missing = {"name", "trigger_type", "formula"} - set(reader.fieldnames or [])
    if missing:
        raise HTTPException(422, f"CSV is missing columns: {', '.join(sorted(missing))}")
    stages = {s.name.lower(): s.id for s in db.scalars(select(Stage))}
    existing = {r.name: r for r in db.scalars(select(Rule))}
    created = updated = 0
    errors = []
    for i, row in enumerate(reader, start=2):
        name = (row.get("name") or "").strip()
        if not name:
            continue
        try:
            stage_name = (row.get("stage") or "").strip()
            if stage_name and stage_name.lower() not in stages:
                raise HTTPException(422, f"Unknown stage '{stage_name}'")
            body = RuleIn(
                name=name, trigger_type=(row.get("trigger_type") or "").strip(),
                condition=RuleCondition(
                    service_codes=[c.upper() for c in _list(row.get("service_codes"))], materials=_list(row.get("materials")),
                    dn_min=_num(row.get("dn_min")), dn_max=_num(row.get("dn_max")), item_types=_list(row.get("item_types")),
                    angle_min=_num(row.get("angle_min")), angle_max=_num(row.get("angle_max")),
                    io_at_ends=_bool(row.get("io_at_ends")), io_at_bends=_bool(row.get("io_at_bends")),
                    io_interval_m=_num(row.get("io_interval_m"))),
                formula=(row.get("formula") or "n").strip(), output_description=(row.get("output_description") or "").strip(),
                uom=(row.get("uom") or "ea").strip() or "ea", stage_id=stages.get(stage_name.lower()) if stage_name else None,
                active=(row.get("active") or "yes").strip().lower() not in ("no", "n", "false", "0"),
            )
            _check_rule(db, body)
        except HTTPException as e:
            errors.append({"row": i, "name": name, "error": e.detail})
            continue
        except (ValueError, TypeError) as e:
            errors.append({"row": i, "name": name, "error": str(e)})
            continue
        rule = existing.get(name)
        if rule:
            before = snapshot(rule)
            for k, v in body.model_dump().items():
                setattr(rule, k, v)
            rule.version += 1
            db.flush()
            record(db, user.id, "rule", rule.id, "update", before, snapshot(rule))
            updated += 1
        else:
            rule = Rule(**body.model_dump())
            db.add(rule)
            db.flush()
            existing[name] = rule
            record(db, user.id, "rule", rule.id, "create", after=snapshot(rule))
            created += 1
    db.commit()
    return {"created": created, "updated": updated, "errors": errors}


# --- catalogue ---
@router.get("/catalogue", response_model=list[CatalogueItemOut])
def list_catalogue(db: Session = Depends(get_db), _: User = Depends(current_user)):
    return db.scalars(select(CatalogueItem).order_by(CatalogueItem.code)).all()


@router.post("/catalogue", response_model=CatalogueItemOut)
def create_catalogue_item(body: CatalogueItemIn, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    item = CatalogueItem(**body.model_dump())
    db.add(item)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "That code is already used")
    return item


@router.put("/catalogue/{item_id}", response_model=CatalogueItemOut)
def update_catalogue_item(item_id: int, body: CatalogueItemIn, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    item = get_or_404(db, CatalogueItem, item_id)
    for k, v in body.model_dump().items():
        setattr(item, k, v)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "That code is already used")
    return item


# --- benchmarks ---
@router.get("/benchmarks", response_model=list[BenchmarkOut])
def list_benchmarks(db: Session = Depends(get_db), _: User = Depends(current_user)):
    return db.scalars(select(Benchmark).order_by(Benchmark.name)).all()


def _check_benchmark(b: BenchmarkIn):
    if not b.service_codes:
        raise HTTPException(422, "Choose at least one service")
    if b.min_value is None and b.max_value is None:
        raise HTTPException(422, "Set a minimum, a maximum, or both")
    if b.min_value is not None and b.max_value is not None and b.min_value > b.max_value:
        raise HTTPException(422, "Minimum is above maximum")


@router.post("/benchmarks", response_model=BenchmarkOut)
def create_benchmark(body: BenchmarkIn, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    _check_benchmark(body)
    b = Benchmark(**body.model_dump())
    db.add(b)
    db.commit()
    return b


@router.put("/benchmarks/{bid}", response_model=BenchmarkOut)
def update_benchmark(bid: int, body: BenchmarkIn, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    _check_benchmark(body)
    b = get_or_404(db, Benchmark, bid)
    for k, v in body.model_dump().items():
        setattr(b, k, v)
    db.commit()
    return b
