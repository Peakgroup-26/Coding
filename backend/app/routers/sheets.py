from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import config, storage
from ..audit import record, snapshot
from ..auth import current_user
from ..db import get_db
from ..models import ClassificationCorrection, Job, Run, Sheet, User, Viewport
from ..pdf_processing import refresh_currency
from ..scale import (PAPER_SIZES_MM, ScaleError, calibrate_two_point, parse_stated_scales, pick_title_block_scale,
                     ratio_from_m_per_pt, stated_m_per_pt, verify)
from ..schemas import CalibrateIn, SheetOut, SheetPatch, VerifyIn, ViewportIn, ViewportOut
from ..titleblock import title_key
from . import get_or_404

router = APIRouter(prefix="/api", tags=["sheets"])


@router.get("/jobs/{job_id}/sheets", response_model=list[SheetOut])
def list_sheets(job_id: int, include_duplicates: bool = False, db: Session = Depends(get_db), _: User = Depends(current_user)):
    q = select(Sheet).where(Sheet.job_id == job_id)
    if not include_duplicates:
        q = q.where(Sheet.is_duplicate.is_(False))
    return db.scalars(q.order_by(Sheet.file_id, Sheet.page_no)).all()


@router.get("/sheets/{sheet_id}", response_model=SheetOut)
def get_sheet(sheet_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    return get_or_404(db, Sheet, sheet_id)


@router.patch("/sheets/{sheet_id}", response_model=SheetOut)
def update_sheet(sheet_id: int, body: SheetPatch, db: Session = Depends(get_db), user: User = Depends(current_user)):
    sheet = get_or_404(db, Sheet, sheet_id)
    before = snapshot(sheet)
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(sheet, k, v)
    if "stated_scale" in data:
        st = pick_title_block_scale(sheet.stated_scale or "")
        sheet.stated_m_per_pt = stated_m_per_pt(st.ratio, st.paper, sheet.width_pt, sheet.height_pt) if st else None
    if {"sheet_no", "revision"} & data.keys():
        db.flush()
        refresh_currency(db, sheet.job_id)
    if {"classification", "services_shown", "is_hydraulic"} & data.keys():
        # Remember the correction for this client so the next upload gets it right.
        job = db.get(Job, sheet.job_id)
        key = title_key(sheet.title)
        corr = db.scalar(select(ClassificationCorrection).where(
            ClassificationCorrection.client == (job.client or ""), ClassificationCorrection.title_key == key))
        if not corr:
            corr = ClassificationCorrection(client=job.client or "", title_key=key)
            db.add(corr)
        corr.classification = sheet.classification
        corr.services_shown = sheet.services_shown
        corr.is_hydraulic = sheet.is_hydraulic
    record(db, user.id, "sheet", sheet.id, "update", before, snapshot(sheet))
    db.commit()
    return sheet


@router.get("/sheets/{sheet_id}/image")
def sheet_image(sheet_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    sheet = get_or_404(db, Sheet, sheet_id)
    return FileResponse(storage.local_path(sheet.image_key), media_type="image/png",
                        headers={"Cache-Control": "private, max-age=3600"})


@router.get("/sheets/{sheet_id}/snap-points")
def sheet_snaps(sheet_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    sheet = get_or_404(db, Sheet, sheet_id)
    return FileResponse(storage.local_path(sheet.snap_key), media_type="application/json",
                        headers={"Cache-Control": "private, max-age=3600"})


# --- scale ---
def _calibrate(target, sheet: Sheet, body: CalibrateIn) -> None:
    try:
        if body.method == "two_point":
            if body.p1 is None or body.p2 is None or body.known_m is None:
                raise ScaleError("Pick two points and enter the known distance")
            mpp = calibrate_two_point(body.p1, body.p2, body.known_m)
            data = {"method": "two_point", "p1": list(body.p1), "p2": list(body.p2), "known_m": body.known_m}
        elif body.method == "stated":
            if body.ratio:
                ratio, paper = body.ratio, (body.paper or None)
            else:
                found = parse_stated_scales(sheet.stated_scale or "")
                if not found:
                    raise ScaleError("No stated scale on this sheet. Enter one, or calibrate from two points.")
                ratio, paper = found[0].ratio, found[0].paper
            if paper and paper not in PAPER_SIZES_MM:
                raise ScaleError(f"Unknown paper size {paper}")
            mpp = stated_m_per_pt(ratio, paper, sheet.width_pt, sheet.height_pt)
            data = {"method": "stated", "ratio": ratio, "paper": paper}
        else:
            raise ScaleError("Method must be two_point or stated")
    except ScaleError as e:
        raise HTTPException(422, str(e))

    paper = sheet.page_size if sheet.page_size in PAPER_SIZES_MM else None
    data["implied_ratio_at_page_size"] = round(ratio_from_m_per_pt(mpp, sheet.width_pt, sheet.height_pt, None), 1)
    if sheet.stated_m_per_pt:
        diff = abs(mpp - sheet.stated_m_per_pt) / sheet.stated_m_per_pt
        data["stated_diff_pct"] = round(diff * 100, 2)
        if diff > config.SCALE_TOLERANCE:
            data["warning"] = (
                f"Calibration differs from the stated scale ({sheet.stated_scale}) by {diff * 100:.1f}%. "
                f"This page is {paper or 'a custom size'}; check whether the drawing was saved at a different paper size."
            )
    target.calibrated_scale = mpp
    target.calibration_data = data
    # A new calibration always needs a fresh check.
    target.scale_verified = False
    target.verification_data = None
    if isinstance(target, Sheet):
        target.calibration_method = body.method


def _verify(target, body: VerifyIn) -> None:
    if not target.calibrated_scale:
        raise HTTPException(409, "Calibrate the scale before checking it")
    try:
        v = verify(target.calibrated_scale, body.p1, body.p2, body.known_m, config.SCALE_TOLERANCE)
    except ScaleError as e:
        raise HTTPException(422, str(e))
    target.scale_verified = v.ok
    target.verification_data = {
        "p1": list(body.p1), "p2": list(body.p2), "known_m": v.known_m,
        "measured_m": round(v.measured_m, 3), "error_pct": round(v.error_pct, 3), "ok": v.ok,
    }


def _has_measurements(db: Session, sheet_id: int, viewport_id: int | None = None) -> bool:
    q = select(Run.id).where(Run.sheet_id == sheet_id)
    q = q.where(Run.viewport_id == viewport_id) if viewport_id else q.where(Run.viewport_id.is_(None))
    return db.scalar(q.limit(1)) is not None


@router.post("/sheets/{sheet_id}/calibrate", response_model=SheetOut)
def calibrate_sheet(sheet_id: int, body: CalibrateIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    sheet = get_or_404(db, Sheet, sheet_id)
    if _has_measurements(db, sheet.id):
        raise HTTPException(409, "This sheet already has runs measured at the current scale. Delete them before recalibrating.")
    before = snapshot(sheet)
    _calibrate(sheet, sheet, body)
    record(db, user.id, "sheet", sheet.id, "calibrate", before, snapshot(sheet))
    db.commit()
    return sheet


@router.post("/sheets/{sheet_id}/verify", response_model=SheetOut)
def verify_sheet(sheet_id: int, body: VerifyIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    sheet = get_or_404(db, Sheet, sheet_id)
    before = snapshot(sheet)
    _verify(sheet, body)
    record(db, user.id, "sheet", sheet.id, "verify", before, snapshot(sheet))
    db.commit()
    return sheet


# --- detail viewports ---
@router.post("/sheets/{sheet_id}/viewports", response_model=ViewportOut)
def create_viewport(sheet_id: int, body: ViewportIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    sheet = get_or_404(db, Sheet, sheet_id)
    x0, y0, x1, y1 = body.bbox
    if abs(x1 - x0) < 10 or abs(y1 - y0) < 10:
        raise HTTPException(422, "Viewport is too small")
    vp = Viewport(sheet_id=sheet.id, name=body.name, bbox=[min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)])
    db.add(vp)
    db.flush()
    record(db, user.id, "viewport", vp.id, "create", after=snapshot(vp))
    db.commit()
    return vp


@router.post("/viewports/{vp_id}/calibrate", response_model=ViewportOut)
def calibrate_viewport(vp_id: int, body: CalibrateIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    vp = get_or_404(db, Viewport, vp_id)
    if _has_measurements(db, vp.sheet_id, vp.id):
        raise HTTPException(409, "This viewport already has runs measured at the current scale. Delete them before recalibrating.")
    before = snapshot(vp)
    _calibrate(vp, vp.sheet, body)
    record(db, user.id, "viewport", vp.id, "calibrate", before, snapshot(vp))
    db.commit()
    return vp


@router.post("/viewports/{vp_id}/verify", response_model=ViewportOut)
def verify_viewport(vp_id: int, body: VerifyIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    vp = get_or_404(db, Viewport, vp_id)
    before = snapshot(vp)
    _verify(vp, body)
    record(db, user.id, "viewport", vp.id, "verify", before, snapshot(vp))
    db.commit()
    return vp


@router.delete("/viewports/{vp_id}", status_code=204)
def delete_viewport(vp_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    vp = get_or_404(db, Viewport, vp_id)
    if _has_measurements(db, vp.sheet_id, vp.id):
        raise HTTPException(409, "Delete the runs measured in this viewport first")
    record(db, user.id, "viewport", vp.id, "delete", before=snapshot(vp))
    db.delete(vp)
    db.commit()
