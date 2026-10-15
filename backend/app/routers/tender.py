"""Tender documents and the requirements read from them."""
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import autopilot, config, storage, tender
from ..audit import record, snapshot
from ..auth import current_user
from ..db import get_db
from ..models import DrawingFile, Job, TenderDocument, TenderRequirement, User
from . import ensure_open, get_or_404

router = APIRouter(prefix="/api", tags=["tender"])


async def store_any(db: Session, job: Job, up: UploadFile, user: User, force_document: bool = False) -> str:
    """Save an upload as a drawing set or a tender document, whichever it is. Returns "drawing" or "document".

    Word, Excel and text files are documents. A PDF is a document when its pages are mostly A4
    (scopes, specs, reports), and a drawing set otherwise.
    """
    name = up.filename or "file"
    lower = name.lower()
    if not lower.endswith(tender.DOC_EXTENSIONS):
        raise HTTPException(422, f"{name}: upload PDFs, Word (.docx), Excel (.xlsx) or text files")
    data = await up.read(config.MAX_UPLOAD_BYTES + 1)
    if len(data) > config.MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"{name} is larger than {config.MAX_UPLOAD_BYTES // (1024 * 1024)} MB")
    is_pdf = lower.endswith(".pdf")
    if is_pdf and data[:5] != b"%PDF-":
        raise HTTPException(422, f"{name} is not a valid PDF")
    if is_pdf and not force_document and not tender.is_document_pdf(data):
        key = f"jobs/{job.id}/originals/{uuid.uuid4().hex}-{tender.safe_name(name)}"
        storage.save_bytes(key, data)
        db.add(DrawingFile(job_id=job.id, filename=name, storage_key=key, uploaded_by=user.id, status="queued"))
        db.flush()
        return "drawing"
    key = f"jobs/{job.id}/documents/{uuid.uuid4().hex}-{tender.safe_name(name)}"
    storage.save_bytes(key, data)
    d = TenderDocument(job_id=job.id, filename=name, storage_key=key, uploaded_by=user.id)
    db.add(d)
    db.flush()
    record(db, user.id, "tender_document", d.id, "create", after={"job_id": job.id, "filename": name})
    return "document"


def _doc_out(d: TenderDocument, reqs: list[TenderRequirement]) -> dict:
    mine = [r for r in reqs if r.document_id == d.id]
    return {"id": d.id, "filename": d.filename, "doc_type": d.doc_type, "title": d.title, "summary": d.summary,
            "page_count": d.page_count, "status": d.status, "error": d.error, "created_at": d.created_at,
            "requirements": len(mine), "suggested": sum(1 for r in mine if r.status == "suggested")}


def _req_out(db: Session, r: TenderRequirement, docs: dict) -> dict:
    d = docs.get(r.document_id)
    return {"id": r.id, "document_id": r.document_id, "document": d.filename if d else "", "category": r.category,
            "title": r.title, "quote": r.quote, "page": r.page, "service_codes": r.service_codes or [],
            "civil_category": r.civil_category, "material": r.material, "description": r.description, "qty": r.qty,
            "unit": r.unit, "amount": r.amount, "allowance_kind": r.allowance_kind, "percent": r.percent,
            "applies_to": r.applies_to, "confidence": r.confidence, "status": r.status,
            "effect": tender.effect(db, r), "needs": tender.missing_input(r) if r.status == "suggested" else ""}


@router.post("/jobs/{job_id}/documents")
async def add_documents(job_id: int, files: list[UploadFile] = File(...), db: Session = Depends(get_db),
                        user: User = Depends(current_user)):
    """Add tender documents (scope, specs, reports, briefs, addenda) and read them."""
    job = get_or_404(db, Job, job_id)
    ensure_open(db, job.id)
    if autopilot.is_running(job.id):
        raise HTTPException(409, "This job is still being read. Add the documents when it has finished.")
    for up in files:
        await store_any(db, job, up, user, force_document=True)
    db.commit()
    autopilot.start(job.id, user.id)
    return {"ok": True}


@router.get("/jobs/{job_id}/documents")
def list_documents(job_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    get_or_404(db, Job, job_id)
    reqs = list(db.scalars(select(TenderRequirement).where(TenderRequirement.job_id == job_id)))
    return [_doc_out(d, reqs) for d in db.scalars(select(TenderDocument).where(TenderDocument.job_id == job_id).order_by(TenderDocument.id))]


@router.get("/documents/{doc_id}/file")
def document_file(doc_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    d = get_or_404(db, TenderDocument, doc_id)
    media = "application/pdf" if d.filename.lower().endswith(".pdf") else "application/octet-stream"
    return Response(storage.read_bytes(d.storage_key), media_type=media,
                    headers={"Content-Disposition": f'inline; filename="{tender.safe_name(d.filename)}"'})


@router.delete("/documents/{doc_id}", status_code=204)
def delete_document(doc_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Remove a document and undo anything accepted from it."""
    d = get_or_404(db, TenderDocument, doc_id)
    ensure_open(db, d.job_id)
    for r in db.scalars(select(TenderRequirement).where(TenderRequirement.document_id == d.id)):
        if r.status == "accepted":
            tender.undo(db, r, user)
        db.delete(r)
    db.flush()  # requirements first, then the document
    record(db, user.id, "tender_document", d.id, "delete", before={"job_id": d.job_id, "filename": d.filename})
    storage.delete(d.storage_key)
    db.delete(d)
    db.commit()


@router.get("/jobs/{job_id}/requirements")
def list_requirements(job_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    job = get_or_404(db, Job, job_id)
    docs = {d.id: d for d in db.scalars(select(TenderDocument).where(TenderDocument.job_id == job_id))}
    order = {c: i for i, c in enumerate(tender.CATEGORY_LABELS)}
    reqs = sorted(db.scalars(select(TenderRequirement).where(TenderRequirement.job_id == job_id)),
                  key=lambda r: (order.get(r.category, 99), r.id))
    return {"requirements": [_req_out(db, r, docs) for r in reqs], "labels": tender.CATEGORY_LABELS,
            "excluded_services": job.excluded_services or [], "spec_materials": job.spec_materials or {},
            "loadings": job.rate_adjustments or []}


class ReqPatch(BaseModel):
    category: str | None = None
    title: str | None = None
    service_codes: list[str] | None = None
    civil_category: str | None = None
    material: str | None = None
    description: str | None = None
    qty: float | None = None
    unit: str | None = None
    amount: float | None = None
    allowance_kind: str | None = None
    percent: float | None = None
    applies_to: str | None = None


@router.patch("/requirements/{req_id}")
def update_requirement(req_id: int, body: ReqPatch, db: Session = Depends(get_db), user: User = Depends(current_user)):
    r = get_or_404(db, TenderRequirement, req_id)
    ensure_open(db, r.job_id)
    if r.status == "accepted":
        raise HTTPException(409, "Undo this first, then change it")
    data = body.model_dump(exclude_unset=True)
    if "category" in data and data["category"] not in tender.CATEGORY_LABELS:
        raise HTTPException(422, "Unknown category")
    if "applies_to" in data and data["applies_to"] not in ("", "labour", "material", "all"):
        raise HTTPException(422, "applies_to must be labour, material or all")
    for k in ("qty", "amount", "percent"):
        if data.get(k) is not None and data[k] < 0:
            raise HTTPException(422, f"{k} can't be negative")
    before = snapshot(r)
    for k, v in data.items():
        if v is not None:
            setattr(r, k, v)
    record(db, user.id, "tender_requirement", r.id, "update", before, snapshot(r))
    db.commit()
    docs = {d.id: d for d in db.scalars(select(TenderDocument).where(TenderDocument.job_id == r.job_id))}
    return _req_out(db, r, docs)


@router.post("/requirements/{req_id}/{action}")
def decide(req_id: int, action: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    r = get_or_404(db, TenderRequirement, req_id)
    ensure_open(db, r.job_id)
    if action == "accept":
        if r.status == "accepted":
            raise HTTPException(409, "Already accepted")
        try:
            tender.apply(db, r, user)
        except ValueError as e:
            raise HTTPException(422, str(e))
    elif action == "reject":
        tender.undo(db, r, user, new_status="rejected")
    elif action == "undo":
        tender.undo(db, r, user)
    else:
        raise HTTPException(404, "Unknown action")
    db.commit()
    docs = {d.id: d for d in db.scalars(select(TenderDocument).where(TenderDocument.job_id == r.job_id))}
    return _req_out(db, r, docs)


@router.post("/jobs/{job_id}/requirements/accept-all")
def accept_all(job_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Accept every suggestion that has what it needs. Ones still needing a choice (a %, a material) are left."""
    get_or_404(db, Job, job_id)
    ensure_open(db, job_id)
    accepted, waiting = 0, 0
    for r in db.scalars(select(TenderRequirement).where(TenderRequirement.job_id == job_id, TenderRequirement.status == "suggested")
                        .order_by(TenderRequirement.id)):
        if tender.missing_input(r):
            waiting += 1
            continue
        tender.apply(db, r, user)
        db.flush()
        accepted += 1
    db.commit()
    return {"accepted": accepted, "waiting": waiting}
