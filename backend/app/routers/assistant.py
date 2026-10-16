"""Ask Peak (the company-wide assistant) and in-app notifications."""
import re

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import assistant
from ..ai import AIUnavailable
from ..auth import current_user
from ..db import get_db
from ..models import ChatMessage, ChatSession, Notification, User
from ..timesheets import now

router = APIRouter(prefix="/api", tags=["assistant"])


@router.get("/assistant")
def history(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return {"messages": assistant.visible(db, user)}


class Ask(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


@router.post("/assistant")
def ask(body: Ask, db: Session = Depends(get_db), user: User = Depends(current_user)):
    try:
        return assistant.ask(db, user, body.text.strip())
    except AIUnavailable as e:
        raise HTTPException(503, str(e))


@router.post("/assistant/new")
def new(db: Session = Depends(get_db), user: User = Depends(current_user)):
    assistant.session(db, user, fresh=True)
    db.commit()
    return {"messages": []}


@router.get("/assistant/reports/{message_id}/{index}.xlsx")
def report_file(message_id: int, index: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    m = db.get(ChatMessage, message_id)
    s = db.get(ChatSession, m.session_id) if m else None
    if m is None or s is None or s.scope != "company" or s.user_id != user.id or not m.reports or index >= len(m.reports):
        raise HTTPException(404, "Report not found")
    rep = m.reports[index]
    name = re.sub(r"[^A-Za-z0-9_-]+", "_", rep.get("title", "report"))[:60] or "report"
    return Response(assistant.report_xlsx(rep), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{name}.xlsx"'})


@router.get("/notifications")
def notifications(db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows = db.scalars(select(Notification).where(Notification.user_id == user.id).order_by(Notification.created_at.desc()).limit(50))
    return [{"id": n.id, "kind": n.kind, "text": n.text, "link": n.link, "at": n.created_at.isoformat(), "read": n.read_at is not None}
            for n in rows]


@router.post("/notifications/read-all", status_code=204)
def read_all(db: Session = Depends(get_db), user: User = Depends(current_user)):
    for n in db.scalars(select(Notification).where(Notification.user_id == user.id, Notification.read_at.is_(None))):
        n.read_at = now()
    db.commit()
