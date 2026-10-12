"""Phase 5: revision compare and carry-forward, marked-up PDF export, Microsoft 365 sign-on."""
import re
import secrets
import urllib.parse

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import sso
from ..audit import record
from ..auth import current_user, hash_password, make_token
from ..db import get_db
from ..geometry import RunShape, overlap_fraction
from ..markup import build_markup_pdf
from ..models import CountItem, Job, Run, Sheet, User
from ..revision import compare
from ..takeoff import recompute_run, resolve_scale
from ..titleblock import revision_rank
from . import ensure_open, get_or_404

router = APIRouter(prefix="/api", tags=["phase5"])


# --- revision compare ---
def _previous_revision(db: Session, sheet: Sheet) -> Sheet | None:
    if not sheet.sheet_no:
        return None
    older = [s for s in db.scalars(select(Sheet).where(Sheet.job_id == sheet.job_id, Sheet.id != sheet.id,
                                                       func.upper(Sheet.sheet_no) == sheet.sheet_no.upper(),
                                                       Sheet.is_duplicate.is_(False)))
             if revision_rank(s.revision) < revision_rank(sheet.revision)]
    return max(older, key=lambda s: revision_rank(s.revision), default=None)


@router.get("/sheets/{sheet_id}/revisions")
def sheet_revisions(sheet_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    sheet = get_or_404(db, Sheet, sheet_id)
    if not sheet.sheet_no:
        return []
    others = db.scalars(select(Sheet).where(Sheet.job_id == sheet.job_id, func.upper(Sheet.sheet_no) == sheet.sheet_no.upper(),
                                            Sheet.is_duplicate.is_(False)))
    return sorted([{"id": s.id, "revision": s.revision, "is_current": s.is_current,
                    "runs": db.scalar(select(func.count()).select_from(Run).where(Run.sheet_id == s.id)),
                    "counts": db.scalar(select(func.count()).select_from(CountItem).where(CountItem.sheet_id == s.id))}
                   for s in others], key=lambda r: revision_rank(r["revision"]))


@router.get("/sheets/{sheet_id}/compare")
def compare_sheet(sheet_id: int, with_id: int | None = None, dx: float = 0.0, dy: float = 0.0,
                  db: Session = Depends(get_db), _: User = Depends(current_user)):
    """What changed on this sheet since another revision (default: the one before it)."""
    new = get_or_404(db, Sheet, sheet_id)
    old = get_or_404(db, Sheet, with_id) if with_id else _previous_revision(db, new)
    if old is None:
        raise HTTPException(404, "There's no earlier revision of this sheet to compare with")
    if old.job_id != new.job_id:
        raise HTTPException(422, "Both sheets must be in the same job")
    return compare(db, old, new, dx, dy)


class CarryIn(BaseModel):
    from_sheet_id: int | None = None
    dx: float = 0.0
    dy: float = 0.0


@router.post("/sheets/{sheet_id}/carry-forward")
def carry_forward(sheet_id: int, body: CarryIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Copy runs and counts from an earlier revision onto this one, as suggestions to review.
    Ones on line work that changed are noted so they get checked first."""
    new = get_or_404(db, Sheet, sheet_id)
    ensure_open(db, new.job_id)
    if not new.is_current:
        raise HTTPException(409, "Carry measurements onto the current revision")
    if not new.scale_verified:
        raise HTTPException(409, "Calibrate and verify this revision's scale first. Scales are never copied between revisions.")
    old = get_or_404(db, Sheet, body.from_sheet_id) if body.from_sheet_id else _previous_revision(db, new)
    if old is None or old.job_id != new.job_id:
        raise HTTPException(404, "No earlier revision to carry from")
    diff = compare(db, old, new, body.dx, body.dy)
    affected = {a["run_id"] for a in diff["affected_runs"]}
    affected_counts = set(diff["affected_counts"])
    existing = [RunShape(r.id, r.geometry, r.service_id, r.dn, len(r.geometry) < 2)
                for r in db.scalars(select(Run).where(Run.sheet_id == new.id))]
    tag = f"Carried from Rev {old.revision or '-'}"
    runs = counts = skipped = flagged = 0
    for r in db.scalars(select(Run).where(Run.sheet_id == old.id).order_by(Run.id)):
        pts = [[x + body.dx, y + body.dy] for x, y in r.geometry]
        shape = RunShape(-1, pts, r.service_id, r.dn, len(pts) < 2)
        if not shape.is_point and any(e.service_id == r.service_id and overlap_fraction(shape, e) > 0.8 for e in existing):
            skipped += 1
            continue
        try:
            mpp, vp = resolve_scale(new, pts)
        except HTTPException:
            skipped += 1
            continue
        note = tag + (": line work changed here, check it" if r.id in affected else "")
        flagged += r.id in affected
        nr = Run(job_id=new.job_id, sheet_id=new.id, viewport_id=vp, service_id=r.service_id, dn=r.dn, material=r.material,
                 level_id=r.level_id, stage_id=r.stage_id, location_tag=r.location_tag, geometry=pts, m_per_pt=mpp,
                 vertical_mode=r.vertical_mode, vertical_count=r.vertical_count, vertical_height_m=r.vertical_height_m,
                 vertical_from_level_id=r.vertical_from_level_id, vertical_to_level_id=r.vertical_to_level_id,
                 waste_pct=r.waste_pct, status="suggested", source="carried", note=note, created_by=user.id)
        recompute_run(db, nr)
        db.add(nr)
        db.flush()
        existing.append(RunShape(nr.id, pts, r.service_id, r.dn, len(pts) < 2))
        runs += 1
    have = [(c.x, c.y, c.item_type) for c in db.scalars(select(CountItem).where(CountItem.sheet_id == new.id))]
    for c in db.scalars(select(CountItem).where(CountItem.sheet_id == old.id)):
        x, y = c.x + body.dx, c.y + body.dy
        if any(abs(x - hx) < 3 and abs(y - hy) < 3 and t == c.item_type for hx, hy, t in have):
            skipped += 1
            continue
        db.add(CountItem(job_id=new.job_id, sheet_id=new.id, service_id=c.service_id, item_type=c.item_type, x=x, y=y,
                         level_id=c.level_id, stage_id=c.stage_id, location_tag=c.location_tag,
                         status="suggested", source="carried", created_by=user.id))
        flagged += c.id in affected_counts
        counts += 1
    record(db, user.id, "sheet", new.id, "carry_forward",
           after={"job_id": new.job_id, "from_sheet_id": old.id, "runs": runs, "counts": counts})
    db.commit()
    return {"runs": runs, "counts": counts, "skipped": skipped, "on_changed_line_work": flagged,
            "from_revision": old.revision, "to_revision": new.revision}


# --- marked-up PDF ---
@router.get("/jobs/{job_id}/markup.pdf")
def markup_pdf(job_id: int, include_suggested: bool = True, db: Session = Depends(get_db), _: User = Depends(current_user)):
    job = get_or_404(db, Job, job_id)
    data = build_markup_pdf(db, job_id, include_suggested)
    fname = re.sub(r"[^A-Za-z0-9_-]+", "_", f"{job.quote_no or job.id}_{job.name}")[:80] + "_markup.pdf"
    return Response(data, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{fname}"'})


# --- Microsoft 365 sign-on ---
COOKIE = "peak_sso"


@router.get("/auth/sso")
def sso_config():
    return {"enabled": sso.enabled(), "provider": "Microsoft 365" if sso.enabled() else None}


@router.get("/auth/sso/start")
def sso_start():
    if not sso.enabled():
        raise HTTPException(404, "Single sign-on isn't set up")
    url, cookie = sso.start()
    resp = RedirectResponse(url, status_code=302)
    resp.set_cookie(COOKIE, cookie, max_age=600, httponly=True, samesite="lax", secure=sso.settings()["redirect_uri"].startswith("https"), path="/api/auth/sso")
    return resp


def _back_to_app(**params) -> RedirectResponse:
    # Token in the fragment: it never reaches a server log or the Referer header.
    resp = RedirectResponse("/login#" + urllib.parse.urlencode(params), status_code=302)
    resp.delete_cookie(COOKIE, path="/api/auth/sso")
    return resp


@router.get("/auth/sso/callback")
def sso_callback(request: Request, code: str = "", state: str = "", error: str = "", error_description: str = "",
                 db: Session = Depends(get_db)):
    if not sso.enabled():
        raise HTTPException(404, "Single sign-on isn't set up")
    if error:
        return _back_to_app(sso_error=error_description or error)
    saved = sso._unsign(request.cookies.get(COOKIE, ""))
    if not saved or not state or saved["state"] != state:
        return _back_to_app(sso_error="The sign-in took too long or came from another browser. Please try again.")
    try:
        email = sso.verify_id_token(sso.exchange_code(code, saved["verifier"]), saved["nonce"])
    except sso.SSOError as e:
        return _back_to_app(sso_error=str(e))
    user = db.scalar(select(User).where(func.lower(User.email) == email))
    if user is None:
        if not sso.settings()["auto_create"]:
            return _back_to_app(sso_error=f"{email} doesn't have an account yet. Ask an admin to add you.")
        user = User(email=email, name=email.split("@")[0], role="estimator", password_hash=hash_password(secrets.token_urlsafe(32)))
        db.add(user)
        db.flush()
        record(db, user.id, "user", user.id, "create", after={"email": email, "via": "sso"})
        db.commit()
    if not user.active:
        return _back_to_app(sso_error="This account has been deactivated")
    return _back_to_app(token=make_token(user.id))
