"""Inspection and Test Plans on each job.

An ITP template is a list of items: the stage, what's done, how it's checked, the acceptance criteria, how often
(once, each section, or daily), the point type (hold = stop until signed off; witness = someone's invited to watch;
review = a record is checked), who does it and what's recorded (photo, reading, signature). A job gets a copy for each
area (Level 3, Unit 12...). Checks are recorded on the phone; hold and witness points need the signer's name and
signature. Each day the phone prompts for the daily items and the next items to do on each job.
"""
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import ItpCheck, ItpTemplate, Job, JobItp, User
from .plant import notify

POINTS = {"hold": "Hold point", "witness": "Witness point", "review": "Document review", "none": ""}
FREQUENCY = {"once": "Once", "each": "Each section", "daily": "Daily"}


def _i(key, stage, activity, check, criteria, frequency="once", point="none", who="Plumber", record="photo"):
    return {"key": key, "stage": stage, "activity": activity, "check": check, "criteria": criteria, "frequency": frequency, "point": point,
            "who": who, "record": record}


DEFAULT_ITPS = [
    {"name": "Sanitary drainage (AS/NZS 3500.2)", "items": [
        _i("d0", "Every day", "Daily trench and site check", "Visual", "Trench shored / battered over 1.5 m, edges barricaded, spoil 1 m back", "daily", "none", "Plumber", "photo"),
        _i("d1", "Set-out", "Set-out and levels", "Survey / laser against drawings", "Points and invert levels match the drawings", "once", "review", "Supervisor", "photo"),
        _i("d2", "Excavation", "Trench excavation", "Measure", "Width and depth to drawings; base firm and even", "each"),
        _i("d3", "Bedding", "Bedding material and depth", "Measure / visual", "Min. 75 mm compacted bedding, approved material", "each"),
        _i("d4", "Pipe laying", "Pipe grade and alignment", "Laser / level", "Grade as designed (DN100 min 1.65%, DN150 min 1%)", "each", "none", "Plumber", "reading"),
        _i("d5", "Pipe laying", "Joints", "Visual", "Solvent welds / rubber rings to manufacturer; no deflection beyond limits", "each"),
        _i("d6", "Pipe laying", "Inspection openings and junctions", "Visual", "Located per drawings, accessible", "once"),
        _i("d7", "Testing", "Water or air test", "Hydrostatic 1.5 m head 15 min / air 7 kPa 3 min", "No leaks, no drop", "each", "hold", "Plumber", "reading"),
        _i("d8", "Inspection", "Plumbing inspector / certifier inspection before backfill", "Inspection", "Approved to cover", "each", "hold", "Certifier", "signature"),
        _i("d9", "Backfill", "Backfill, compaction and marker tape", "Visual", "Compacted in layers; warning tape 300 mm above pipe", "each"),
        _i("d10", "Handover", "CCTV of the main line", "CCTV", "No defects, sags or debris", "once", "witness", "Client"),
        _i("d11", "Handover", "As-constructed drawings", "Document", "Marked up and submitted", "once", "review", "Supervisor", "photo")]},
    {"name": "Water services (AS/NZS 3500.1)", "items": [
        _i("w0", "Every day", "Daily work area check", "Visual", "Penetrations protected, materials stored off the ground, area tidy", "daily"),
        _i("w1", "Materials", "Materials WaterMark certified", "Document", "Pipes and fittings WaterMark listed; as specified", "once", "review", "Supervisor"),
        _i("w2", "Rough-in", "Pipe sizes and route", "Visual against drawings", "Sizes and route per hydraulic drawings", "each"),
        _i("w3", "Rough-in", "Clips, supports and lagging", "Measure", "Clip spacing to AS/NZS 3500.1; lagging where specified", "each"),
        _i("w4", "Testing", "Rough-in pressure test", "Test gauge", "1500 kPa for 30 minutes, no drop", "each", "hold", "Plumber", "reading"),
        _i("w5", "Inspection", "Inspection before lining", "Inspection", "Approved by certifier / inspector", "each", "hold", "Certifier", "signature"),
        _i("w6", "Fit-off", "Backflow prevention device", "Test kit", "Installed, tested and tagged; report lodged", "each", "witness", "Accredited tester", "reading"),
        _i("w7", "Fit-off", "TMVs commissioned", "Thermometer", "Outlet temperature ≤ 50 °C (45 °C aged care / childcare)", "each", "none", "Plumber", "reading"),
        _i("w8", "Commissioning", "Flushing and disinfection", "Visual / record", "Flushed clear; disinfected where required", "once"),
        _i("w9", "Handover", "Compliance certificate (Form 4) lodged", "Document", "Lodged with council", "once", "review", "Supervisor")]},
    {"name": "Gas (AS/NZS 5601)", "items": [
        _i("g1", "Design", "Pipe sizing calculation", "Document", "Sized for the connected load and length", "once", "review", "Licensed gasfitter"),
        _i("g2", "Install", "Pipe, supports and sleeving", "Visual", "Approved materials; sleeved through walls; supports to standard", "each"),
        _i("g3", "Testing", "Pressure test", "Test gauge", "Test pressure held for the required time, no drop", "each", "hold", "Licensed gasfitter", "reading"),
        _i("g4", "Commissioning", "Purging", "Detector", "Purged to a safe outside location", "once"),
        _i("g5", "Commissioning", "Appliance commissioning", "Manometer / analyser", "Operating pressure, flame picture, flue and CO checked", "each", "witness", "Licensed gasfitter", "reading"),
        _i("g6", "Handover", "Gas compliance certificate", "Document", "Issued and lodged", "once", "review", "Supervisor")]},
    {"name": "Stormwater (AS/NZS 3500.3)", "items": [
        _i("s0", "Every day", "Daily trench and site check", "Visual", "Trenches safe, sediment controls in place", "daily"),
        _i("s1", "Set-out", "Set-out and levels", "Survey", "Pits and inverts per drawings", "once", "review", "Supervisor"),
        _i("s2", "Pipe laying", "Grade, bedding and joints", "Laser / visual", "Grade per design; bedding and joints to standard", "each", "none", "Plumber", "reading"),
        _i("s3", "Pits", "Pits and grates", "Visual", "Levels, benching and grates per drawings; trafficable class where needed", "each"),
        _i("s4", "Inspection", "Inspection before backfill", "Inspection", "Approved to cover", "each", "hold", "Certifier", "signature"),
        _i("s5", "Handover", "As-constructed drawings", "Document", "Marked up and submitted", "once", "review", "Supervisor")]},
    {"name": "Hot water systems (AS/NZS 3500.4)", "items": [
        _i("h1", "Install", "Unit location and clearances", "Visual", "Clearances, access and flue per manufacturer", "each"),
        _i("h2", "Install", "Valves: isolation, non-return, PTR, expansion", "Visual", "All fitted and accessible", "each"),
        _i("h3", "Install", "Relief drains", "Visual", "Discharge to a safe, visible point", "each"),
        _i("h4", "Commissioning", "Temperature at outlets", "Thermometer", "Storage ≥ 60 °C; outlets ≤ 50 °C via TMV", "each", "none", "Plumber", "reading"),
        _i("h5", "Handover", "Warranty registration and manuals", "Document", "Registered; left with the owner", "once", "review", "Supervisor")]},
]


def seed(db: Session) -> None:
    if not db.scalar(select(ItpTemplate.id).limit(1)):
        for t in DEFAULT_ITPS:
            db.add(ItpTemplate(name=t["name"], items=t["items"]))
        db.flush()


def today() -> date:
    from .timesheets import local_day

    return local_day(datetime.now(timezone.utc))


def create(db: Session, job: Job, t: ItpTemplate, area: str = "") -> JobItp:
    ji = JobItp(job_id=job.id, template_id=t.id, name=t.name, area=area, items=[dict(i) for i in t.items or []])
    db.add(ji)
    db.flush()
    return ji


def checks(db: Session, ji: JobItp) -> list[ItpCheck]:
    return list(db.scalars(select(ItpCheck).where(ItpCheck.job_itp_id == ji.id).order_by(ItpCheck.created_at)))


def state(db: Session, ji: JobItp, day: date | None = None) -> list[dict]:
    """Each item with its latest result and whether it's done."""
    day = day or today()
    by_item: dict[str, list[ItpCheck]] = {}
    for c in checks(db, ji):
        by_item.setdefault(c.item_key, []).append(c)
    out = []
    for it in ji.items or []:
        cs = by_item.get(it["key"], [])
        last = cs[-1] if cs else None
        if it.get("frequency") == "daily":
            done = any(c.day == day and c.result in ("pass", "na") for c in cs)
        else:
            done = bool(last and last.result in ("pass", "na"))
        out.append({**it, "done": done, "last": check_out(last) if last else None, "count": len(cs),
                    "failed": bool(last and last.result == "fail"), "point_label": POINTS.get(it.get("point", "none"), "")})
    return out


def check_out(c: ItpCheck, names: dict[int, str] | None = None) -> dict:
    return {"id": c.id, "item_key": c.item_key, "day": c.day.isoformat(), "result": c.result, "reading": c.reading, "notes": c.notes,
            "photos": c.photos or [], "user_id": c.user_id, "by": (names or {}).get(c.user_id or 0, ""), "signed_name": c.signed_name,
            "signed_role": c.signed_role, "has_signature": bool(c.signature), "at": c.created_at.isoformat()}


def record(db: Session, ji: JobItp, user: User, item_key: str, result: str, reading: str = "", notes: str = "", photos: list | None = None,
           signed_name: str = "", signed_role: str = "", signature: str = "", day: date | None = None) -> ItpCheck:
    item = next((i for i in ji.items or [] if i["key"] == item_key), None)
    if item is None:
        raise ValueError("No such item on this ITP")
    if result not in ("pass", "fail", "na"):
        raise ValueError("Pass, fail or not applicable")
    if result == "pass" and item.get("point") in ("hold", "witness") and not (signed_name.strip() and signature):
        raise ValueError(f"{POINTS[item['point']]}: get {item.get('who') or 'the signer'} to sign it off")
    if result == "pass" and item.get("record") == "reading" and not reading.strip():
        raise ValueError("Enter the reading or test result")
    c = ItpCheck(job_itp_id=ji.id, item_key=item_key, day=day or today(), result=result, reading=reading, notes=notes, photos=photos or [],
                 user_id=user.id, signed_name=signed_name, signed_role=signed_role, signature=signature)
    db.add(c)
    db.flush()
    if result == "fail":
        job = db.get(Job, ji.job_id)
        to = {u.id for u in db.scalars(select(User).where(User.role == "admin", User.active.is_(True)))}
        if job and job.supervisor_id:
            to.add(job.supervisor_id)
        for uid in to - {user.id}:
            notify(db, uid, "itp", f"ITP failed on {job.job_no if job else ''}: {item['activity']} ({ji.name}{', ' + ji.area if ji.area else ''})",
                   f"/work/{ji.job_id}?tab=itp", key=f"itp-fail-{c.id}-{uid}")
    st = state(db, ji)
    ji.status = "complete" if all(s["done"] for s in st if s.get("frequency") != "daily") else "open"
    return c


def due_today(db: Session, job: Job, day: date | None = None) -> list[dict]:
    """For the phone: today's daily checks, then the next couple of items on each open ITP (hold points flagged)."""
    day = day or today()
    out = []
    for ji in db.scalars(select(JobItp).where(JobItp.job_id == job.id, JobItp.status == "open")):
        st = state(db, ji, day)
        label = f"{ji.name}{' – ' + ji.area if ji.area else ''}"
        for s in st:
            if s.get("frequency") == "daily" and not s["done"]:
                out.append({"itp_id": ji.id, "itp": label, "key": s["key"], "activity": s["activity"], "point": s.get("point"), "daily": True})
        nxt = [s for s in st if s.get("frequency") != "daily" and not s["done"]][:2]
        for s in nxt:
            out.append({"itp_id": ji.id, "itp": label, "key": s["key"], "activity": s["activity"], "point": s.get("point"), "daily": False,
                        "failed": s["failed"]})
    return out


def itp_out(db: Session, ji: JobItp, names: dict[int, str]) -> dict:
    st = state(db, ji)
    real = [s for s in st if s.get("frequency") != "daily"]
    return {"id": ji.id, "job_id": ji.job_id, "name": ji.name, "area": ji.area, "status": ji.status, "items": st,
            "done": sum(1 for s in real if s["done"]), "total": len(real), "failed": sum(1 for s in st if s["failed"]),
            "history": [check_out(c, names) for c in reversed(checks(db, ji))][:200], "created_at": ji.created_at.isoformat()}
