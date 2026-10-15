"""Phase 4: AI sheet reading, line-style run suggestions, symbol matching, and suggestion stats."""
import math
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import storage
from ..ai import AIUnavailable, ai_status, get_reader
from ..assist import create_suggested_runs, read_and_apply
from ..audit import record, snapshot
from ..auth import current_user
from ..db import get_db
from ..models import AiOutcome, CountItem, CountType, Job, Run, Service, Sheet, StyleMapping, User
from ..suggest import extract_segments, match_symbols, style_summary
from . import ensure_open, get_or_404

router = APIRouter(prefix="/api", tags=["ai"])


@router.get("/ai/status")
def status(_: User = Depends(current_user)):
    return ai_status()


# --- AI sheet reading ---
def _read_one(db: Session, sheet: Sheet, user: User) -> dict:
    reader = get_reader()
    if reader is None:
        raise HTTPException(409, "AI sheet reading is switched off. Set TAKEOFF_AI=claude on the server to turn it on.")
    try:
        return read_and_apply(db, reader, sheet, user)
    except AIUnavailable as e:
        raise HTTPException(503, str(e))


@router.post("/sheets/{sheet_id}/ai-read")
def ai_read_sheet(sheet_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    sheet = get_or_404(db, Sheet, sheet_id)
    ensure_open(db, sheet.job_id)
    out = _read_one(db, sheet, user)
    db.commit()
    return out


@router.post("/jobs/{job_id}/ai-read")
def ai_read_job(job_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Read every current sheet that hasn't been confirmed yet."""
    get_or_404(db, Job, job_id)
    ensure_open(db, job_id)
    done, errors = 0, []
    for sheet in db.scalars(select(Sheet).where(Sheet.job_id == job_id, Sheet.confirmed.is_(False), Sheet.is_duplicate.is_(False))):
        try:
            _read_one(db, sheet, user)
            db.commit()
            done += 1
        except HTTPException as e:
            db.rollback()
            errors.append({"sheet_id": sheet.id, "error": e.detail})
            if e.status_code == 409:
                break
    return {"read": done, "errors": errors}


# --- line styles -> suggested runs ---
def _client(db: Session, sheet: Sheet) -> str:
    return db.get(Job, sheet.job_id).client or ""


@router.get("/sheets/{sheet_id}/line-styles")
def line_styles(sheet_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    sheet = get_or_404(db, Sheet, sheet_id)
    styles = extract_segments(sheet)
    summary = style_summary(styles, sheet.calibrated_scale if sheet.scale_verified else None)
    saved = {m.style_key: m for m in db.scalars(select(StyleMapping).where(StyleMapping.client == _client(db, sheet)))}
    for s in summary:
        m = saved.get(s["key"])
        s["mapping"] = {"service_id": m.service_id, "dn": m.dn, "material": m.material} if m else None
    return {"styles": summary}


class StyleAssign(BaseModel):
    key: str
    service_id: int
    dn: int = Field(gt=0)
    material: str


class SuggestRunsIn(BaseModel):
    styles: list[StyleAssign] = []  # empty = use the client's saved style mappings
    remember: bool = True
    min_length_m: float = Field(default=0.5, ge=0)


@router.post("/sheets/{sheet_id}/suggest-runs")
def suggest_runs(sheet_id: int, body: SuggestRunsIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    sheet = get_or_404(db, Sheet, sheet_id)
    ensure_open(db, sheet.job_id)
    if not sheet.is_current:
        raise HTTPException(409, "This sheet has been superseded")
    if not sheet.scale_verified:
        raise HTTPException(409, "Verify this sheet's scale before suggesting runs")
    client = _client(db, sheet)
    assigns = [a.model_dump() for a in body.styles]
    if not assigns:
        styles = extract_segments(sheet)
        saved = db.scalars(select(StyleMapping).where(StyleMapping.client == client))
        assigns = [{"key": m.style_key, "service_id": m.service_id, "dn": m.dn, "material": m.material}
                   for m in saved if m.style_key in styles]
        if not assigns:
            raise HTTPException(422, "Assign at least one line style to a service, size and material")
    for a in assigns:
        get_or_404(db, Service, a["service_id"])
    try:
        result = create_suggested_runs(db, sheet, assigns, user, client=client, remember=body.remember,
                                       min_length_m=body.min_length_m)
    except KeyError as e:
        raise HTTPException(422, f"Line style {e.args[0]} isn't on this sheet")
    db.commit()
    return result


# --- symbol matching -> suggested counts ---
class SuggestCountsIn(BaseModel):
    count_id: int | None = None  # an existing count to use as the example
    x: float | None = None
    y: float | None = None
    item_type: str | None = None
    service_id: int | None = None
    box_pt: float = Field(default=24.0, ge=6, le=200)
    threshold: float = Field(default=0.75, ge=0.4, le=0.99)


@router.post("/sheets/{sheet_id}/suggest-counts")
def suggest_counts(sheet_id: int, body: SuggestCountsIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    sheet = get_or_404(db, Sheet, sheet_id)
    ensure_open(db, sheet.job_id)
    if not sheet.is_current:
        raise HTTPException(409, "This sheet has been superseded")
    example = get_or_404(db, CountItem, body.count_id) if body.count_id else None
    x, y = (example.x, example.y) if example else (body.x, body.y)
    item_type = body.item_type or (example.item_type if example else None)
    service_id = body.service_id or (example.service_id if example else None)
    if x is None or y is None or not item_type or not service_id:
        raise HTTPException(422, "Give an example count, or a point plus item type and service")
    svc = get_or_404(db, Service, service_id)
    try:
        matches = match_symbols(str(storage.local_path(sheet.image_key)), sheet, x, y, body.box_pt, body.threshold)
    except ValueError as e:
        raise HTTPException(422, str(e))
    near = body.box_pt * 0.75
    existing = [(c.x, c.y) for c in db.scalars(select(CountItem).where(CountItem.sheet_id == sheet.id, CountItem.item_type == item_type))]
    ct = db.scalar(select(CountType).where(CountType.name == item_type))
    stage_id = (example.stage_id if example else None) or (ct.default_stage_id if ct else None) or svc.default_stage_id
    created = 0
    for mx, my, _score in matches:
        if any(math.hypot(mx - ex, my - ey) < near for ex, ey in existing):
            continue
        db.add(CountItem(job_id=sheet.job_id, sheet_id=sheet.id, service_id=service_id, item_type=item_type, x=mx, y=my,
                         level_id=example.level_id if example else None, stage_id=stage_id,
                         status="suggested", source="ai", created_by=user.id))
        existing.append((mx, my))
        created += 1
    record(db, user.id, "sheet", sheet.id, "suggest_counts", after={"job_id": sheet.job_id, "created": created, "item_type": item_type})
    db.commit()
    return {"created": created, "matches": len(matches)}


# --- bulk accept / reject ---
class BulkIn(BaseModel):
    kind: str = "all"  # run | count | all


@router.post("/sheets/{sheet_id}/suggestions/{action}")
def bulk_suggestions(sheet_id: int, action: str, body: BulkIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if action not in ("accept", "reject"):
        raise HTTPException(404, "Unknown action")
    sheet = get_or_404(db, Sheet, sheet_id)
    ensure_open(db, sheet.job_id)
    n = 0
    targets = []
    if body.kind in ("run", "all"):
        targets += [("run", r) for r in db.scalars(select(Run).where(Run.sheet_id == sheet_id, Run.status == "suggested"))]
    if body.kind in ("count", "all"):
        targets += [("count", c) for c in db.scalars(select(CountItem).where(CountItem.sheet_id == sheet_id, CountItem.status == "suggested"))]
    for kind, obj in targets:
        if obj.source == "ai":
            outcome = "rejected" if action == "reject" else ("edited" if obj.ai_edited else "accepted")
            db.add(AiOutcome(job_id=obj.job_id, sheet_id=obj.sheet_id, kind=kind, outcome=outcome))
        if action == "accept":
            before = snapshot(obj)
            obj.status = "confirmed"
            record(db, user.id, kind, obj.id, "update", before, snapshot(obj))
        else:
            record(db, user.id, kind, obj.id, "delete", before=snapshot(obj))
            db.delete(obj)
        n += 1
    db.commit()
    return {action + "ed": n}


# --- stats ---
def _accuracy(sheets: list[Sheet]) -> dict:
    """How often the first proposal matched what a person confirmed."""
    judged = [s for s in sheets if s.confirmed and s.proposed]
    by_source: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    type_ok = svc_ok = both_ok = 0
    for s in judged:
        t = s.proposed.get("classification") == s.classification
        v = sorted(s.proposed.get("services") or []) == sorted(s.services_shown or [])
        type_ok += t
        svc_ok += v
        both_ok += t and v
        b = by_source[s.proposed.get("source", "keywords")]
        b[0] += 1
        b[1] += t and v
    n = len(judged)
    pct = (lambda k: round(100 * k / n, 1) if n else None)
    return {"sheets_confirmed": n, "type_correct_pct": pct(type_ok), "services_correct_pct": pct(svc_ok),
            "both_correct_pct": pct(both_ok), "target_pct": 90,
            "by_source": {k: {"sheets": v[0], "correct_pct": round(100 * v[1] / v[0], 1)} for k, v in by_source.items()}}


@router.get("/jobs/{job_id}/ai-stats")
def ai_stats(job_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    get_or_404(db, Job, job_id)
    sheets = list(db.scalars(select(Sheet).where(Sheet.job_id == job_id)))
    per: dict[int, dict] = {s.id: {"sheet_id": s.id, "sheet_no": s.sheet_no or f"p{s.page_no}", "accepted": 0, "edited": 0,
                                   "rejected": 0, "pending": 0} for s in sheets}
    for o in db.scalars(select(AiOutcome).where(AiOutcome.job_id == job_id)):
        if o.sheet_id in per:
            per[o.sheet_id][o.outcome] += 1
    for model in (Run, CountItem):
        for obj in db.scalars(select(model).where(model.job_id == job_id, model.source == "ai", model.status == "suggested")):
            per[obj.sheet_id]["pending"] += 1
    rows = [r for r in per.values() if any(r[k] for k in ("accepted", "edited", "rejected", "pending"))]
    return {"sheets": rows, "classification": _accuracy(sheets), "ai": ai_status()}


@router.get("/ai/classification-accuracy")
def classification_accuracy(db: Session = Depends(get_db), _: User = Depends(current_user)):
    """Across every job: the test set is all sheets people have confirmed."""
    return _accuracy(list(db.scalars(select(Sheet))))
