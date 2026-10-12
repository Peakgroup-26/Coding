"""Price books, mappings, job pricing, Simpro export and the golden-job comparison."""
import json
import re
from collections import defaultdict
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..audit import record, snapshot
from ..auth import current_user, require_admin
from ..db import get_db
from ..models import (AppSetting, Job, JobAllowance, LabourRate, PriceBookVersion, PriceItem, PriceMapping, Prebuild,
                      ReferenceLine, Service, Stage, User)
from ..pricebook_import import import_items, import_prebuilds, import_rates, read_rows
from ..pricing import price_job
from ..schemas import (AllowanceIn, AllowanceOut, JobOut, LabourRateIn, LabourRateOut, MappingIn, MappingOut,
                       PrebuildIn, PrebuildOut, PriceBookIn, PriceBookOut, PriceBookPatch, PriceItemIn, PriceItemOut,
                       PricingSettingsIn)
from ..simpro import FIELDS, build_csv, get_template, validate_template
from ..takeoff import job_totals
from . import ensure_open, get_or_404

router = APIRouter(prefix="/api", tags=["pricing"])

MAX_IMPORT_BYTES = 20 * 1024 * 1024


# --- price books ---
def _book_unlocked(db: Session, version_id: int) -> PriceBookVersion:
    v = get_or_404(db, PriceBookVersion, version_id)
    if v.locked:
        raise HTTPException(409, "This price book is locked. Make a new version (copy it) to change prices.")
    return v


@router.get("/price-books")
def list_books(db: Session = Depends(get_db), _: User = Depends(current_user)):
    out = []
    for v in db.scalars(select(PriceBookVersion).order_by(PriceBookVersion.id.desc())):
        counts = {
            "items": db.scalar(select(func.count()).select_from(PriceItem).where(PriceItem.version_id == v.id)),
            "prebuilds": db.scalar(select(func.count()).select_from(Prebuild).where(Prebuild.version_id == v.id)),
            "rates": db.scalar(select(func.count()).select_from(LabourRate).where(LabourRate.version_id == v.id)),
            "jobs": db.scalar(select(func.count()).select_from(Job).where(Job.price_book_version_id == v.id)),
        }
        out.append({**PriceBookOut.model_validate(v).model_dump(), **counts})
    return out


@router.post("/price-books", response_model=PriceBookOut)
def create_book(body: PriceBookIn, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    v = PriceBookVersion(label=body.label, notes=body.notes)
    db.add(v)
    db.flush()
    if body.copy_from_id:
        src = get_or_404(db, PriceBookVersion, body.copy_from_id)
        v.default_labour_rate_code = src.default_labour_rate_code
        for p in db.scalars(select(PriceItem).where(PriceItem.version_id == src.id)):
            db.add(PriceItem(version_id=v.id, code=p.code, description=p.description, uom=p.uom, cost=p.cost, supplier=p.supplier))
        for p in db.scalars(select(Prebuild).where(Prebuild.version_id == src.id)):
            db.add(Prebuild(version_id=v.id, code=p.code, description=p.description, uom=p.uom, labour_hours=p.labour_hours,
                            labour_rate_code=p.labour_rate_code, components=list(p.components or [])))
        for r in db.scalars(select(LabourRate).where(LabourRate.version_id == src.id)):
            db.add(LabourRate(version_id=v.id, code=r.code, description=r.description, rate=r.rate))
    record(db, user.id, "price_book", v.id, "create", after=snapshot(v))
    db.commit()
    return v


@router.patch("/price-books/{vid}", response_model=PriceBookOut)
def update_book(vid: int, body: PriceBookPatch, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    v = get_or_404(db, PriceBookVersion, vid)
    data = body.model_dump(exclude_unset=True)
    if v.locked and set(data) - {"label", "notes"}:
        raise HTTPException(409, "This price book is locked")
    before = snapshot(v)
    for k, val in data.items():
        setattr(v, k, val)
    record(db, user.id, "price_book", v.id, "update", before, snapshot(v))
    db.commit()
    return v


@router.post("/price-books/{vid}/lock", response_model=PriceBookOut)
def lock_book(vid: int, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    v = _book_unlocked(db, vid)
    if v.default_labour_rate_code and not db.scalar(select(LabourRate.id).where(LabourRate.version_id == v.id, LabourRate.code == v.default_labour_rate_code)):
        raise HTTPException(422, f"Default labour rate '{v.default_labour_rate_code}' isn't in this price book")
    v.locked = True
    v.locked_at = datetime.now(timezone.utc)
    record(db, user.id, "price_book", v.id, "lock", after=snapshot(v))
    db.commit()
    return v


@router.delete("/price-books/{vid}", status_code=204)
def delete_book(vid: int, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    v = _book_unlocked(db, vid)
    if db.scalar(select(Job.id).where(Job.price_book_version_id == vid).limit(1)):
        raise HTTPException(409, "Jobs use this price book")
    record(db, user.id, "price_book", v.id, "delete", before=snapshot(v))
    db.delete(v)
    db.commit()


@router.post("/price-books/{vid}/import")
async def import_book(vid: int, kind: str = Form(...), file: UploadFile = File(...), columns: str = Form(""),
                      db: Session = Depends(get_db), user: User = Depends(require_admin)):
    """Import items (price list), prebuilds or labour rates from CSV or Excel into a draft price book.
    `columns` optionally names the file's columns as JSON, e.g. {"code": "Part No", "cost": "Trade"}."""
    _book_unlocked(db, vid)
    data = await file.read()
    if len(data) > MAX_IMPORT_BYTES:
        raise HTTPException(413, "File is too large")
    try:
        explicit = json.loads(columns) if columns.strip() else None
        rows = read_rows(file.filename or "", data)
        fn = {"items": import_items, "prebuilds": import_prebuilds, "rates": import_rates}.get(kind)
        if fn is None:
            raise ValueError("Kind must be items, prebuilds or rates")
        res = fn(db, vid, rows, explicit)
    except (ValueError, json.JSONDecodeError) as e:
        db.rollback()
        raise HTTPException(422, str(e))
    except Exception as e:  # unreadable spreadsheet
        db.rollback()
        raise HTTPException(422, f"Couldn't read {file.filename}: {e}")
    record(db, user.id, "price_book", vid, f"import_{kind}", after={"created": res.created, "updated": res.updated, "errors": len(res.errors)})
    db.commit()
    return res.as_dict()


def _search(q, model, search: str):
    if search:
        like = f"%{search.lower()}%"
        q = q.where(func.lower(model.code).like(like) | func.lower(model.description).like(like))
    return q


@router.get("/price-books/{vid}/items", response_model=list[PriceItemOut])
def list_items(vid: int, search: str = "", limit: int = 200, db: Session = Depends(get_db), _: User = Depends(current_user)):
    q = _search(select(PriceItem).where(PriceItem.version_id == vid), PriceItem, search)
    return db.scalars(q.order_by(PriceItem.code).limit(min(limit, 2000))).all()


@router.get("/price-books/{vid}/prebuilds", response_model=list[PrebuildOut])
def list_prebuilds(vid: int, search: str = "", limit: int = 200, db: Session = Depends(get_db), _: User = Depends(current_user)):
    q = _search(select(Prebuild).where(Prebuild.version_id == vid), Prebuild, search)
    return db.scalars(q.order_by(Prebuild.code).limit(min(limit, 2000))).all()


@router.get("/price-books/{vid}/rates", response_model=list[LabourRateOut])
def list_rates(vid: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    return db.scalars(select(LabourRate).where(LabourRate.version_id == vid).order_by(LabourRate.code)).all()


def _upsert(db, model, vid, body):
    obj = db.scalar(select(model).where(model.version_id == vid, model.code == body.code))
    if obj is None:
        obj = model(version_id=vid, code=body.code)
        db.add(obj)
    for k, v in body.model_dump().items():
        setattr(obj, k, v)
    db.commit()
    return obj


@router.put("/price-books/{vid}/items", response_model=PriceItemOut)
def put_item(vid: int, body: PriceItemIn, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    _book_unlocked(db, vid)
    return _upsert(db, PriceItem, vid, body)


@router.put("/price-books/{vid}/prebuilds", response_model=PrebuildOut)
def put_prebuild(vid: int, body: PrebuildIn, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    _book_unlocked(db, vid)
    for c in body.components:
        if not c.get("code") or float(c.get("qty", 0)) <= 0:
            raise HTTPException(422, "Each component needs a code and a quantity above 0")
    return _upsert(db, Prebuild, vid, body)


@router.put("/price-books/{vid}/rates", response_model=LabourRateOut)
def put_rate(vid: int, body: LabourRateIn, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    _book_unlocked(db, vid)
    return _upsert(db, LabourRate, vid, body)


# --- mappings ---
def _check_mapping(body: MappingIn):
    if body.source_kind not in ("pipe", "count", "fitting"):
        raise HTTPException(422, "Source must be pipe, count or fitting")
    if body.target_kind not in ("prebuild", "item"):
        raise HTTPException(422, "Target must be prebuild or item")
    if not body.target_code.strip():
        raise HTTPException(422, "Enter a prebuild or item code")
    if body.source_kind == "pipe" and not (body.material and body.dn):
        raise HTTPException(422, "A pipe mapping needs a material and DN")
    if body.source_kind == "count" and not body.item_type:
        raise HTTPException(422, "A count mapping needs an item type")
    if body.source_kind == "fitting" and not body.description.strip():
        raise HTTPException(422, "A fitting mapping needs the item description")


@router.get("/mappings", response_model=list[MappingOut])
def list_mappings(db: Session = Depends(get_db), _: User = Depends(current_user)):
    return db.scalars(select(PriceMapping).order_by(PriceMapping.source_kind, PriceMapping.service_code,
                                                    PriceMapping.material, PriceMapping.dn, PriceMapping.item_type,
                                                    PriceMapping.description)).all()


@router.post("/mappings", response_model=MappingOut)
def create_mapping(body: MappingIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    _check_mapping(body)
    m = PriceMapping(**body.model_dump())
    db.add(m)
    db.flush()
    record(db, user.id, "mapping", m.id, "create", after=snapshot(m))
    db.commit()
    return m


@router.put("/mappings/{mid}", response_model=MappingOut)
def update_mapping(mid: int, body: MappingIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    _check_mapping(body)
    m = get_or_404(db, PriceMapping, mid)
    before = snapshot(m)
    for k, v in body.model_dump().items():
        setattr(m, k, v)
    record(db, user.id, "mapping", m.id, "update", before, snapshot(m))
    db.commit()
    return m


@router.delete("/mappings/{mid}", status_code=204)
def delete_mapping(mid: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    m = get_or_404(db, PriceMapping, mid)
    record(db, user.id, "mapping", m.id, "delete", before=snapshot(m))
    db.delete(m)
    db.commit()


# --- job pricing ---
@router.get("/jobs/{job_id}/pricing")
def job_pricing(job_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    get_or_404(db, Job, job_id)
    try:
        return price_job(db, job_id)
    except ValueError as e:
        raise HTTPException(422, str(e))


@router.put("/jobs/{job_id}/pricing-settings", response_model=JobOut)
def pricing_settings(job_id: int, body: PricingSettingsIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    job = get_or_404(db, Job, job_id)
    ensure_open(db, job_id)
    if body.margin_basis not in ("markup", "margin"):
        raise HTTPException(422, "Margin basis must be markup or margin")
    pcts = [body.default_margin_pct, *[v for v in body.service_margins.values() if v is not None],
            *[v for v in body.stage_margins.values() if v is not None]]
    if any(p < 0 for p in pcts) or (body.margin_basis == "margin" and any(p >= 100 for p in pcts)):
        raise HTTPException(422, "Margins must be 0 or more, and under 100% on a margin basis")
    if body.price_book_version_id is not None:
        get_or_404(db, PriceBookVersion, body.price_book_version_id)
    before = snapshot(job)
    for k, v in body.model_dump().items():
        if k in ("service_margins", "stage_margins"):
            v = {key: val for key, val in v.items() if val is not None}
        setattr(job, k, v)
    record(db, user.id, "job", job.id, "pricing_settings", before, snapshot(job))
    db.commit()
    return job


@router.get("/jobs/{job_id}/allowances", response_model=list[AllowanceOut])
def list_allowances(job_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    return db.scalars(select(JobAllowance).where(JobAllowance.job_id == job_id).order_by(JobAllowance.kind, JobAllowance.id)).all()


def _check_allowance(db, body: AllowanceIn):
    if body.kind not in ("pc", "provisional", "exclusion"):
        raise HTTPException(422, "Kind must be pc, provisional or exclusion")
    if body.service_id is not None:
        get_or_404(db, Service, body.service_id)
    if body.stage_id is not None:
        get_or_404(db, Stage, body.stage_id)


@router.post("/jobs/{job_id}/allowances", response_model=AllowanceOut)
def create_allowance(job_id: int, body: AllowanceIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    get_or_404(db, Job, job_id)
    ensure_open(db, job_id)
    _check_allowance(db, body)
    a = JobAllowance(job_id=job_id, **body.model_dump())
    db.add(a)
    db.flush()
    record(db, user.id, "allowance", a.id, "create", after=snapshot(a))
    db.commit()
    return a


@router.put("/allowances/{aid}", response_model=AllowanceOut)
def update_allowance(aid: int, body: AllowanceIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    a = get_or_404(db, JobAllowance, aid)
    ensure_open(db, a.job_id)
    _check_allowance(db, body)
    before = snapshot(a)
    for k, v in body.model_dump().items():
        setattr(a, k, v)
    record(db, user.id, "allowance", a.id, "update", before, snapshot(a))
    db.commit()
    return a


@router.delete("/allowances/{aid}", status_code=204)
def delete_allowance(aid: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    a = get_or_404(db, JobAllowance, aid)
    ensure_open(db, a.job_id)
    record(db, user.id, "allowance", a.id, "delete", before=snapshot(a))
    db.delete(a)
    db.commit()


# --- Simpro export ---
@router.get("/settings/simpro-template")
def simpro_template(db: Session = Depends(get_db), _: User = Depends(current_user)):
    return {"template": get_template(db), "fields": FIELDS}


@router.put("/settings/simpro-template")
def put_simpro_template(body: dict, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    try:
        validate_template(body)
    except ValueError as e:
        raise HTTPException(422, str(e))
    s = db.get(AppSetting, "simpro_template") or AppSetting(key="simpro_template")
    s.value = {k: body[k] for k in ("columns", "group_by_stage", "group_by_service", "include_allowances") if k in body}
    db.add(s)
    db.commit()
    return {"template": get_template(db), "fields": FIELDS}


@router.get("/jobs/{job_id}/simpro.csv")
def simpro_csv(job_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    job = get_or_404(db, Job, job_id)
    p = price_job(db, job_id)
    if p["price_book"] is None:
        raise HTTPException(409, "Choose a price book for this job first")
    if p["unmapped"] or p["missing_codes"]:
        raise HTTPException(409, f"{len(p['unmapped'])} unmapped item(s) and {len(p['missing_codes'])} missing code(s). Map everything before exporting.")
    fname = re.sub(r"[^A-Za-z0-9_-]+", "_", f"{job.quote_no or job.id}_{job.name}")[:80] + "_simpro.csv"
    return Response(build_csv(p, get_template(db)), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{fname}"'})


# --- golden-job comparison ---
@router.post("/jobs/{job_id}/reference")
async def upload_reference(job_id: int, file: UploadFile = File(...), db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Known final quantities from a completed job: columns service, dn, material, qty (metres).
    dn and material may be blank to compare a whole service. Replaces any earlier upload."""
    get_or_404(db, Job, job_id)
    rows = read_rows(file.filename or "reference.csv", await file.read())
    if not rows:
        raise HTTPException(422, "The file is empty")
    keys = {k.lower().strip(): k for k in rows[0]}
    svc_col = keys.get("service") or keys.get("service_code") or keys.get("service code")
    qty_col = keys.get("qty") or keys.get("qty_m") or keys.get("quantity") or keys.get("metres") or keys.get("length")
    if not svc_col or not qty_col:
        raise HTTPException(422, "Needs a service column and a qty column (dn and material are optional)")
    dn_col, mat_col = keys.get("dn"), keys.get("material")
    db.query(ReferenceLine).filter(ReferenceLine.job_id == job_id).delete()
    n = 0
    for r in rows:
        if not r.get(svc_col):
            continue
        try:
            qty = float(r[qty_col])
            dn = int(float(r[dn_col])) if dn_col and r.get(dn_col) else None
        except ValueError:
            raise HTTPException(422, f"Not a number in row: {r}")
        db.add(ReferenceLine(job_id=job_id, service_code=r[svc_col].strip().upper(), dn=dn,
                             material=(r.get(mat_col) or "").strip() if mat_col else "", qty_m=qty))
        n += 1
    record(db, user.id, "job", job_id, "reference_upload", after={"lines": n})
    db.commit()
    return {"lines": n}


@router.get("/jobs/{job_id}/golden-report")
def golden_report(job_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    """Take-off vs a completed job's known quantities, per service and per size/material."""
    job = get_or_404(db, Job, job_id)
    refs = list(db.scalars(select(ReferenceLine).where(ReferenceLine.job_id == job_id)))
    t = job_totals(db, job_id)
    ours_line = {(l["service_code"], l["dn"], l["material"]): l["total_m"] for l in t["lines"]}
    ours_svc: dict[str, float] = defaultdict(float)
    for (svc, _, _), q in ours_line.items():
        ours_svc[svc] += q
    ref_svc: dict[str, float] = defaultdict(float)
    detail = []
    for r in refs:
        ref_svc[r.service_code] += r.qty_m
        if r.dn is not None or r.material:
            ours = sum(q for (s, dn, mat), q in ours_line.items()
                       if s == r.service_code and (r.dn is None or dn == r.dn) and (not r.material or mat == r.material))
            detail.append({"service_code": r.service_code, "dn": r.dn, "material": r.material, "reference_m": r.qty_m,
                           "takeoff_m": round(ours, 2), "variance_pct": round((ours - r.qty_m) / r.qty_m * 100, 2) if r.qty_m else None})

    def var(ours, ref):
        return round((ours - ref) / ref * 100, 2) if ref else None

    services = [{"service_code": s, "reference_m": round(ref_svc.get(s, 0), 2), "takeoff_m": round(ours_svc.get(s, 0), 2),
                 "variance_pct": var(ours_svc.get(s, 0), ref_svc.get(s, 0))}
                for s in sorted(set(ref_svc) | set(ours_svc))]
    out = {"services": services, "detail": detail, "has_reference": bool(refs)}
    if job.reference_total_ex_gst and job.price_book_version_id:
        p = price_job(db, job_id)
        if p["summary"]:
            out["price"] = {"reference_total_ex_gst": job.reference_total_ex_gst, "priced_ex_gst": p["summary"]["sell_ex_gst"],
                            "variance_pct": p["summary"].get("reference_variance_pct")}
    return out
