"""Background jobs, once a minute: send due messages, push to Xero, board automations, and the daily / monthly reminders.

Each job runs in its own database session and its own try block, so one failing never stops the others.
Every few rounds the full Xero sync runs (payments, bills, bank balance). Off when BACKGROUND_TASKS=0.
"""
import logging
import threading
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from . import config
from .db import SessionLocal

log = logging.getLogger(__name__)
_stop = threading.Event()
_last_full_xero: datetime | None = None


def _run(name: str, fn) -> None:
    with SessionLocal() as db:
        try:
            fn(db)
            db.commit()
        except Exception:  # noqa: BLE001
            db.rollback()
            log.exception("background job %s failed", name)


def forgot_to_clock_out(db) -> None:
    """Anyone clocked in for more than 12 hours gets a nudge, and so do the admins."""
    from .models import TimeEntry, User
    from .plant import notify

    cutoff = datetime.now(timezone.utc) - timedelta(hours=12)
    for e in db.scalars(select(TimeEntry).where(TimeEntry.end_at.is_(None), TimeEntry.start_at < cutoff)):
        u = db.get(User, e.user_id)
        notify(db, e.user_id, "clock", "You're still clocked in from yesterday. Clock off and fix the time in My timesheet.",
               "/field/timesheet", key=f"forgot-{e.id}")
        for a in db.scalars(select(User).where(User.role == "admin", User.active.is_(True))):
            notify(db, a.id, "clock", f"{u.name or u.email if u else 'Someone'} has been clocked in for over 12 hours.", "/timesheets",
                   key=f"forgot-{e.id}-{a.id}")


_last_daily: datetime | None = None


def tick(full_xero: bool | None = None) -> None:
    global _last_full_xero, _last_daily
    from . import boards, crm, hr, plant, safety, tools, xero

    now = datetime.now(timezone.utc)
    if _last_daily is None or now - _last_daily >= timedelta(hours=1):  # licence reminders and leavers: hourly is plenty
        _last_daily = now
        _run("hr.daily", lambda db: hr.daily(db))
        _run("tools.daily", lambda db: tools.daily(db))
        _run("safety.daily", lambda db: safety.daily(db))
    _run("crm.send", crm.send_due)
    _run("crm.monthly", lambda db: crm.monthly(db))
    _run("plant.reminders", lambda db: plant.monthly_reminders(db))
    _run("clock", forgot_to_clock_out)
    _run("boards", lambda db: boards.scheduled(db))
    if full_xero is None:
        full_xero = _last_full_xero is None or now - _last_full_xero >= timedelta(minutes=config.XERO_SYNC_MINUTES)
    if full_xero:
        _last_full_xero = now
    _run("xero", lambda db: xero.sync(db, full=full_xero))


def _loop() -> None:
    time.sleep(20)
    while not _stop.is_set():
        tick()
        _stop.wait(60)


def start() -> None:
    if config.BACKGROUND_TASKS:
        threading.Thread(target=_loop, name="peak-background", daemon=True).start()


def stop() -> None:
    _stop.set()
