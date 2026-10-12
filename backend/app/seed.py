"""Default seed data from the brief. Admins can rename, add or retire any of it.

Waste percentages start at 0%: the brief says these are Peak's numbers to supply, so the
system doesn't invent them.
"""
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import config
from .auth import hash_password
from .models import CountType, Material, Service, Stage, User

log = logging.getLogger(__name__)

STAGES = ["Site / civil", "Under slab", "Drains", "Rough-in", "Downpipes / roof", "Fit-off", "Final"]

# code, name, colour, default stage
SERVICES = [
    ("CW", "Cold water", "#0070C0", "Rough-in"),
    ("HW", "Hot water (incl. warm/tempered)", "#E02020", "Rough-in"),
    ("HWS", "Hot water supply / plant", "#FF8C00", "Fit-off"),
    ("SW", "Site / external water", "#00A0E0", "Site / civil"),
    ("SAN", "Sanitary drainage", "#8B4513", "Under slab"),
    ("TW", "Trade waste", "#808000", "Drains"),
    ("FIRE", "Fire services", "#C00060", "Rough-in"),
    ("RW", "Roof water", "#009090", "Downpipes / roof"),
    ("STW", "Stormwater (building)", "#00A050", "Drains"),
    ("CSTW", "Civil stormwater", "#006030", "Site / civil"),
    ("PUMP", "Pumps and pump supply", "#7030A0", "Fit-off"),
    ("PC", "PC item supply", "#606060", "Fit-off"),
    ("GAS", "Gas (optional)", "#E0C000", "Rough-in"),
]

MATERIALS = ["PVC DWV", "PVC SWV", "PVC pressure", "Copper", "PEX", "HDPE", "Ductile iron", "Stainless steel", "Galvanised steel", "Polypropylene"]

# name, default service code, is_fixture
COUNT_TYPES = [
    ("WC", "SAN", True),
    ("Basin", "SAN", True),
    ("Sink", "SAN", True),
    ("Shower", "SAN", True),
    ("Urinal", "SAN", True),
    ("Cleaner's sink", "SAN", True),
    ("Dishwasher", "SAN", True),
    ("Floor waste", "SAN", False),
    ("IO (inspection opening)", "SAN", False),
    ("Pit", "STW", False),
    ("Valve", "CW", False),
    ("Hydrant", "FIRE", False),
    ("Hose reel", "FIRE", False),
    ("Tundish", "HWS", False),
    ("TMV", "HW", False),
    ("Backflow device", "CW", False),
    ("Meter", "SW", False),
    ("HWS unit", "HWS", False),
    ("Hose tap", "CW", True),
]


def seed(db: Session) -> None:
    if not db.scalar(select(Stage.id).limit(1)):
        for i, name in enumerate(STAGES):
            db.add(Stage(name=name, order=i))
        db.flush()
    stages = {s.name: s.id for s in db.scalars(select(Stage))}

    if not db.scalar(select(Service.id).limit(1)):
        for i, (code, name, colour, stage) in enumerate(SERVICES):
            db.add(Service(code=code, name=name, colour=colour, default_stage_id=stages.get(stage), order=i))
        db.flush()
    services = {s.code: s.id for s in db.scalars(select(Service))}

    if not db.scalar(select(Material.id).limit(1)):
        for name in MATERIALS:
            db.add(Material(name=name, waste_pct=0.0))

    if not db.scalar(select(CountType.id).limit(1)):
        for name, svc, fixture in COUNT_TYPES:
            # Fixtures go in at fit-off; other items take their service's default stage.
            db.add(CountType(name=name, default_service_id=services.get(svc), is_fixture=fixture,
                             default_stage_id=stages.get("Fit-off") if fixture else None))

    if not db.scalar(select(User.id).limit(1)):
        db.add(User(email=config.ADMIN_EMAIL.lower(), name="Admin", role="admin", password_hash=hash_password(config.ADMIN_PASSWORD)))
        if config.ADMIN_PASSWORD == "changeme":
            log.warning("Created default admin %s with password 'changeme'. Change it now.", config.ADMIN_EMAIL)
    db.commit()
