"""Core tables from the brief's data model, plus the supporting tables Phase 1 needs.

Geometry is stored in sheet coordinates: PDF points (1/72 inch) on the page as displayed
(rotation applied), origin top-left. Screen pixels are never stored.
"""
from datetime import date, datetime, timezone

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), default="")
    role: Mapped[str] = mapped_column(String(20), default="estimator")  # estimator | reviewer | admin
    password_hash: Mapped[str] = mapped_column(String(255))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Stage(Base):
    __tablename__ = "stages"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    order: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Service(Base):
    __tablename__ = "services"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    colour: Mapped[str] = mapped_column(String(9), default="#0070C0")
    # What the service is, for check-measure: drainage | stormwater | water | fire | gas | other
    kind: Mapped[str] = mapped_column(String(20), default="other")
    default_stage_id: Mapped[int | None] = mapped_column(ForeignKey("stages.id"), nullable=True)
    order: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Material(Base):
    """Pipe materials and their waste/offcut allowance (admin-set)."""
    __tablename__ = "materials"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    waste_pct: Mapped[float] = mapped_column(Float, default=0.0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class CountType(Base):
    """Item types for the click-to-count tool."""
    __tablename__ = "count_types"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    default_service_id: Mapped[int | None] = mapped_column(ForeignKey("services.id"), nullable=True)
    default_stage_id: Mapped[int | None] = mapped_column(ForeignKey("stages.id"), nullable=True)
    is_fixture: Mapped[bool] = mapped_column(Boolean, default=False)
    # Check-measure flags a fixture that has no drainage / water run connected when these are set.
    needs_drainage: Mapped[bool] = mapped_column(Boolean, default=False)
    needs_water: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    client: Mapped[str] = mapped_column(String(255), default="")
    builder: Mapped[str] = mapped_column(String(255), default="")
    address: Mapped[str] = mapped_column(String(500), default="")
    quote_no: Mapped[str] = mapped_column(String(100), default="")
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="draft")
    price_book_version_id: Mapped[int | None] = mapped_column(ForeignKey("price_book_versions.id"), nullable=True)
    # Pricing settings. margin_basis: "markup" (sell = cost x (1 + p)) or "margin" (sell = cost / (1 - p)).
    margin_basis: Mapped[str] = mapped_column(String(10), default="markup")
    default_margin_pct: Mapped[float] = mapped_column(Float, default=0.0)
    service_margins: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # {"SAN": 20}
    stage_margins: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # {"Fit-off": 15}
    gst_pct: Mapped[float] = mapped_column(Float, default=10.0)
    reference_total_ex_gst: Mapped[float | None] = mapped_column(Float, nullable=True)  # known past estimate, for comparison
    signed_off_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    signed_off_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    checks_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    kind: Mapped[str] = mapped_column(String(20), default="hydraulic", server_default="hydraulic")  # hydraulic | civil
    # Progress of the automatic read: {state, step, done, total, started_at, finished_at, attention: [...], summary}
    autopilot: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    files: Mapped[list["DrawingFile"]] = relationship(back_populates="job", cascade="all, delete-orphan")
    levels: Mapped[list["Level"]] = relationship(back_populates="job", cascade="all, delete-orphan")


class DrawingFile(Base):
    __tablename__ = "drawing_files"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(500))
    storage_key: Mapped[str] = mapped_column(String(500))
    uploaded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(30), default="processing")  # processing | ready | failed
    error: Mapped[str] = mapped_column(Text, default="")

    job: Mapped[Job] = relationship(back_populates="files")
    sheets: Mapped[list["Sheet"]] = relationship(back_populates="file", cascade="all, delete-orphan")


class Sheet(Base):
    __tablename__ = "sheets"
    id: Mapped[int] = mapped_column(primary_key=True)
    file_id: Mapped[int] = mapped_column(ForeignKey("drawing_files.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    page_no: Mapped[int] = mapped_column(Integer)  # 1-based within its file
    sheet_no: Mapped[str] = mapped_column(String(100), default="")
    title: Mapped[str] = mapped_column(String(500), default="")
    revision: Mapped[str] = mapped_column(String(20), default="")
    drawing_date: Mapped[str] = mapped_column(String(50), default="")

    # Page geometry
    width_pt: Mapped[float] = mapped_column(Float)
    height_pt: Mapped[float] = mapped_column(Float)
    page_size: Mapped[str] = mapped_column(String(20), default="")  # A0..A4 or "custom"
    image_key: Mapped[str] = mapped_column(String(500), default="")
    image_width_px: Mapped[int] = mapped_column(Integer, default=0)
    image_height_px: Mapped[int] = mapped_column(Integer, default=0)
    snap_key: Mapped[str] = mapped_column(String(500), default="")
    has_text_layer: Mapped[bool] = mapped_column(Boolean, default=False)
    has_vectors: Mapped[bool] = mapped_column(Boolean, default=False)
    extracted_text: Mapped[str] = mapped_column(Text, default="")

    # Scale. calibrated_scale is metres per PDF point.
    stated_scale: Mapped[str] = mapped_column(String(100), default="")
    stated_m_per_pt: Mapped[float | None] = mapped_column(Float, nullable=True)
    calibrated_scale: Mapped[float | None] = mapped_column(Float, nullable=True)
    calibration_method: Mapped[str] = mapped_column(String(20), default="")  # two_point | stated
    calibration_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    scale_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    verification_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Classification proposal
    classification: Mapped[str] = mapped_column(String(50), default="")  # plan | section | detail | schematic | cover | legend | other
    services_shown: Mapped[list | None] = mapped_column(JSON, nullable=True)  # list of service codes
    is_hydraulic: Mapped[bool] = mapped_column(Boolean, default=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    # The first proposal (keyword or AI), kept to measure classification accuracy against what users confirm.
    proposed: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    ai_reading: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # last AI read, incl. legend

    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    is_duplicate: Mapped[bool] = mapped_column(Boolean, default=False)

    file: Mapped[DrawingFile] = relationship(back_populates="sheets")
    viewports: Mapped[list["Viewport"]] = relationship(back_populates="sheet", cascade="all, delete-orphan")


class Viewport(Base):
    """A detail area on a sheet with its own scale."""
    __tablename__ = "viewports"
    id: Mapped[int] = mapped_column(primary_key=True)
    sheet_id: Mapped[int] = mapped_column(ForeignKey("sheets.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100), default="Detail")
    bbox: Mapped[list] = mapped_column(JSON)  # [x0, y0, x1, y1] in sheet points
    calibrated_scale: Mapped[float | None] = mapped_column(Float, nullable=True)
    calibration_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    scale_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    verification_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    sheet: Mapped[Sheet] = relationship(back_populates="viewports")


class ClassificationCorrection(Base):
    """User corrections to sheet classification, remembered per client."""
    __tablename__ = "classification_corrections"
    id: Mapped[int] = mapped_column(primary_key=True)
    client: Mapped[str] = mapped_column(String(255), index=True)
    title_key: Mapped[str] = mapped_column(String(500))
    classification: Mapped[str] = mapped_column(String(50), default="")
    services_shown: Mapped[list | None] = mapped_column(JSON, nullable=True)
    is_hydraulic: Mapped[bool] = mapped_column(Boolean, default=True)


class Level(Base):
    __tablename__ = "levels"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    rl: Mapped[float] = mapped_column(Float, default=0.0)
    floor_to_floor_m: Mapped[float] = mapped_column(Float, default=0.0)

    job: Mapped[Job] = relationship(back_populates="levels")


class Run(Base):
    __tablename__ = "runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    sheet_id: Mapped[int] = mapped_column(ForeignKey("sheets.id", ondelete="CASCADE"), index=True)
    viewport_id: Mapped[int | None] = mapped_column(ForeignKey("viewports.id", ondelete="SET NULL"), nullable=True)
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id"))
    dn: Mapped[int] = mapped_column(Integer)
    material: Mapped[str] = mapped_column(String(100))
    level_id: Mapped[int | None] = mapped_column(ForeignKey("levels.id", ondelete="SET NULL"), nullable=True)
    stage_id: Mapped[int | None] = mapped_column(ForeignKey("stages.id"), nullable=True)
    location_tag: Mapped[str] = mapped_column(String(200), default="")

    geometry: Mapped[list] = mapped_column(JSON)  # [[x, y], ...] sheet points
    m_per_pt: Mapped[float] = mapped_column(Float)  # scale used when measured
    length_m: Mapped[float] = mapped_column(Float, default=0.0)

    # Verticals: count x height, where height is entered or taken from the level table.
    vertical_mode: Mapped[str] = mapped_column(String(10), default="none")  # none | manual | levels
    vertical_count: Mapped[int] = mapped_column(Integer, default=0)
    vertical_height_m: Mapped[float] = mapped_column(Float, default=0.0)
    vertical_from_level_id: Mapped[int | None] = mapped_column(ForeignKey("levels.id", ondelete="SET NULL"), nullable=True)
    vertical_to_level_id: Mapped[int | None] = mapped_column(ForeignKey("levels.id", ondelete="SET NULL"), nullable=True)
    vertical_m: Mapped[float] = mapped_column(Float, default=0.0)

    waste_pct: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(20), default="confirmed")  # suggested | confirmed
    source: Mapped[str] = mapped_column(String(20), default="manual")  # manual | ai
    ai_edited: Mapped[bool] = mapped_column(Boolean, default=False)  # a suggestion changed before it was confirmed
    note: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CountItem(Base):
    __tablename__ = "count_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    sheet_id: Mapped[int] = mapped_column(ForeignKey("sheets.id", ondelete="CASCADE"), index=True)
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id"))
    item_type: Mapped[str] = mapped_column(String(100))
    x: Mapped[float] = mapped_column(Float)
    y: Mapped[float] = mapped_column(Float)
    level_id: Mapped[int | None] = mapped_column(ForeignKey("levels.id", ondelete="SET NULL"), nullable=True)
    stage_id: Mapped[int | None] = mapped_column(ForeignKey("stages.id"), nullable=True)
    location_tag: Mapped[str] = mapped_column(String(200), default="")
    status: Mapped[str] = mapped_column(String(20), default="confirmed")
    source: Mapped[str] = mapped_column(String(20), default="manual")
    ai_edited: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    entity: Mapped[str] = mapped_column(String(50))
    entity_id: Mapped[int] = mapped_column(Integer)
    job_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(20))  # create | update | delete | calibrate | finalise ...
    before: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    after: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CatalogueItem(Base):
    """Materials catalogue. Filled from Peak's price list in Phase 3; rules can point at it now."""
    __tablename__ = "catalogue_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(100), unique=True)
    description: Mapped[str] = mapped_column(String(500))
    uom: Mapped[str] = mapped_column(String(20), default="ea")
    cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    supplier: Mapped[str] = mapped_column(String(200), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Rule(Base):
    """A fitting or sundry allowance rule. Peak's own values; the system ships none.

    trigger_type: per_fixture | per_metre | per_bend | per_branch | per_io | per_job
    condition: JSON filters and trigger settings, e.g.
        {"service_codes": ["SAN"], "materials": ["PVC DWV"], "dn_min": 80, "dn_max": 150,
         "item_types": ["WC"], "angle_min": 67.5, "angle_max": 95,
         "io_at_ends": true, "io_at_bends": false, "io_interval_m": 30}
    formula: quantity expression; see expr.py for the variables each trigger provides.
    """
    __tablename__ = "rules"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    trigger_type: Mapped[str] = mapped_column(String(20))
    condition: Mapped[dict] = mapped_column(JSON, default=dict)
    formula: Mapped[str] = mapped_column(String(500), default="n")
    output_item_id: Mapped[int | None] = mapped_column(ForeignKey("catalogue_items.id"), nullable=True)
    output_description: Mapped[str] = mapped_column(String(300), default="")  # template, e.g. "{material} DN{dn} 88° bend"
    uom: Mapped[str] = mapped_column(String(20), default="ea")
    stage_id: Mapped[int | None] = mapped_column(ForeignKey("stages.id"), nullable=True)  # null = source's stage
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    version: Mapped[int] = mapped_column(Integer, default=1)


class GeneratedItem(Base):
    """A fitting or sundry line, generated from a rule (or added by hand when rule_id is null)."""
    __tablename__ = "generated_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    rule_id: Mapped[int | None] = mapped_column(ForeignKey("rules.id", ondelete="SET NULL"), nullable=True)
    rule_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_ref: Mapped[str] = mapped_column(String(50), default="")  # run:12 | count:5 | job | manual
    source_qty: Mapped[float | None] = mapped_column(Float, nullable=True)  # the n or m the formula used
    item_id: Mapped[int | None] = mapped_column(ForeignKey("catalogue_items.id"), nullable=True)
    description: Mapped[str] = mapped_column(String(300))
    uom: Mapped[str] = mapped_column(String(20), default="ea")
    service_id: Mapped[int | None] = mapped_column(ForeignKey("services.id"), nullable=True)
    dn: Mapped[int | None] = mapped_column(Integer, nullable=True)
    material: Mapped[str] = mapped_column(String(100), default="")
    qty: Mapped[float] = mapped_column(Float, default=0.0)
    stage_id: Mapped[int | None] = mapped_column(ForeignKey("stages.id"), nullable=True)
    overridden_qty: Mapped[float | None] = mapped_column(Float, nullable=True)
    stage_overridden: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str] = mapped_column(Text, default="")


class Benchmark(Base):
    """Ratio check for check-measure, e.g. drainage metres per fixture must be between min and max."""
    __tablename__ = "benchmarks"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    service_codes: Mapped[list] = mapped_column(JSON, default=list)  # metres of these services...
    per: Mapped[str] = mapped_column(String(20), default="fixture")  # ...per fixture
    min_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Flag(Base):
    __tablename__ = "flags"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    check_type: Mapped[str] = mapped_column(String(50))
    severity: Mapped[str] = mapped_column(String(10), default="warning")  # error | warning
    ref: Mapped[str] = mapped_column(String(100), default="")  # e.g. run:12:end, count:5, sheet:3
    sheet_id: Mapped[int | None] = mapped_column(ForeignKey("sheets.id", ondelete="CASCADE"), nullable=True)
    x: Mapped[float | None] = mapped_column(Float, nullable=True)
    y: Mapped[float | None] = mapped_column(Float, nullable=True)
    message: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="open")  # open | resolved | accepted
    resolved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# --- Phase 3: pricing ---
class PriceBookVersion(Base):
    """A snapshot of Peak's prices. Jobs point at one; once locked it never changes, so an old
    estimate keeps the rates it was priced with."""
    __tablename__ = "price_book_versions"
    id: Mapped[int] = mapped_column(primary_key=True)
    label: Mapped[str] = mapped_column(String(200))
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    locked: Mapped[bool] = mapped_column(Boolean, default=False)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    default_labour_rate_code: Mapped[str] = mapped_column(String(100), default="")


class PriceItem(Base):
    """A material or catalogue item with its cost in one price-book version."""
    __tablename__ = "price_items"
    __table_args__ = (UniqueConstraint("version_id", "code"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("price_book_versions.id", ondelete="CASCADE"), index=True)
    code: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(String(500), default="")
    uom: Mapped[str] = mapped_column(String(20), default="ea")
    cost: Mapped[float] = mapped_column(Float, default=0.0)
    supplier: Mapped[str] = mapped_column(String(200), default="")


class Prebuild(Base):
    """An assembly of items (and possibly other prebuilds) plus labour, as in Simpro."""
    __tablename__ = "prebuilds"
    __table_args__ = (UniqueConstraint("version_id", "code"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("price_book_versions.id", ondelete="CASCADE"), index=True)
    code: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(String(500), default="")
    uom: Mapped[str] = mapped_column(String(20), default="ea")
    labour_hours: Mapped[float] = mapped_column(Float, default=0.0)
    labour_rate_code: Mapped[str] = mapped_column(String(100), default="")  # blank = the version's default rate
    components: Mapped[list] = mapped_column(JSON, default=list)  # [{"code": "...", "qty": 1.0}]


class LabourRate(Base):
    __tablename__ = "labour_rates"
    __table_args__ = (UniqueConstraint("version_id", "code"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("price_book_versions.id", ondelete="CASCADE"), index=True)
    code: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(String(200), default="")
    rate: Mapped[float] = mapped_column(Float, default=0.0)  # $ per hour, ex GST


class PriceMapping(Base):
    """Maps a take-off item to a prebuild or catalogue item code. Codes, not ids, so mappings
    carry across price-book versions.

    source_kind: pipe (service + material + DN, per metre) | count (item type) | fitting (description)
    Blank service_code matches any service; a mapping for the exact service wins.
    """
    __tablename__ = "price_mappings"
    id: Mapped[int] = mapped_column(primary_key=True)
    source_kind: Mapped[str] = mapped_column(String(10))
    service_code: Mapped[str] = mapped_column(String(20), default="")
    material: Mapped[str] = mapped_column(String(100), default="")
    dn: Mapped[int | None] = mapped_column(Integer, nullable=True)
    item_type: Mapped[str] = mapped_column(String(100), default="")
    description: Mapped[str] = mapped_column(String(300), default="")
    target_kind: Mapped[str] = mapped_column(String(10))  # prebuild | item
    target_code: Mapped[str] = mapped_column(String(100))
    factor: Mapped[float] = mapped_column(Float, default=1.0)  # target qty per source unit
    note: Mapped[str] = mapped_column(String(300), default="")


class JobAllowance(Base):
    """PC items, provisional sums and exclusions on a job."""
    __tablename__ = "job_allowances"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(15))  # pc | provisional | exclusion
    description: Mapped[str] = mapped_column(String(500))
    amount: Mapped[float] = mapped_column(Float, default=0.0)  # ex GST; ignored for exclusions
    service_id: Mapped[int | None] = mapped_column(ForeignKey("services.id"), nullable=True)
    stage_id: Mapped[int | None] = mapped_column(ForeignKey("stages.id"), nullable=True)
    apply_margin: Mapped[bool] = mapped_column(Boolean, default=True)


class ReferenceLine(Base):
    """A known quantity from a completed job, for the golden-job comparison."""
    __tablename__ = "reference_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    service_code: Mapped[str] = mapped_column(String(20))
    dn: Mapped[int | None] = mapped_column(Integer, nullable=True)
    material: Mapped[str] = mapped_column(String(100), default="")
    qty_m: Mapped[float] = mapped_column(Float)


class AppSetting(Base):
    """Small admin-editable settings, e.g. the Simpro CSV template."""
    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)


# --- Phase 4: AI assistance ---
class StyleMapping(Base):
    """A drawing line style (colour, dashes, width, layer) assigned to a service, size and material,
    remembered per client (consultants tend to reuse their CAD styles)."""
    __tablename__ = "style_mappings"
    id: Mapped[int] = mapped_column(primary_key=True)
    client: Mapped[str] = mapped_column(String(255), index=True)
    style_key: Mapped[str] = mapped_column(String(300))
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id"))
    dn: Mapped[int] = mapped_column(Integer)
    material: Mapped[str] = mapped_column(String(100))


class AiOutcome(Base):
    """What happened to each suggestion: accepted as is, edited then accepted, or rejected."""
    __tablename__ = "ai_outcomes"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    sheet_id: Mapped[int | None] = mapped_column(ForeignKey("sheets.id", ondelete="CASCADE"), nullable=True)
    kind: Mapped[str] = mapped_column(String(10))  # run | count
    outcome: Mapped[str] = mapped_column(String(10))  # accepted | edited | rejected
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# --- Civil BOQ ---
class CivilRateSet(Base):
    """Rates from one previous civil job (or a rate schedule), imported from a spreadsheet."""
    __tablename__ = "civil_rate_sets"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    source_file: Mapped[str] = mapped_column(String(500), default="")
    job_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    rates: Mapped[list["CivilRate"]] = relationship(back_populates="rate_set", cascade="all, delete-orphan")


class CivilRate(Base):
    __tablename__ = "civil_rates"
    id: Mapped[int] = mapped_column(primary_key=True)
    set_id: Mapped[int] = mapped_column(ForeignKey("civil_rate_sets.id", ondelete="CASCADE"), index=True)
    code: Mapped[str] = mapped_column(String(100), default="")
    category: Mapped[str] = mapped_column(String(200), default="")
    description: Mapped[str] = mapped_column(String(1000))
    unit: Mapped[str] = mapped_column(String(20), default="")
    rate: Mapped[float] = mapped_column(Float)
    qty: Mapped[float | None] = mapped_column(Float, nullable=True)  # the quantity on that job, for reference

    rate_set: Mapped[CivilRateSet] = relationship(back_populates="rates")


class CivilTakeoffItem(Base):
    """A quantity the AI (or a person) read from one civil sheet."""
    __tablename__ = "civil_takeoff_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    sheet_id: Mapped[int | None] = mapped_column(ForeignKey("sheets.id", ondelete="CASCADE"), nullable=True, index=True)
    category: Mapped[str] = mapped_column(String(200), default="")
    description: Mapped[str] = mapped_column(String(1000))
    unit: Mapped[str] = mapped_column(String(20), default="")
    qty: Mapped[float] = mapped_column(Float, default=0.0)
    basis: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    needs_measuring: Mapped[bool] = mapped_column(Boolean, default=False)
    line_id: Mapped[int | None] = mapped_column(ForeignKey("civil_boq_lines.id", ondelete="SET NULL"), nullable=True)


class CivilBoqLine(Base):
    __tablename__ = "civil_boq_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    sort: Mapped[int] = mapped_column(Integer, default=0)
    category: Mapped[str] = mapped_column(String(200), default="")
    description: Mapped[str] = mapped_column(String(1000))
    unit: Mapped[str] = mapped_column(String(20), default="")
    qty: Mapped[float] = mapped_column(Float, default=0.0)  # as read: sum or max of its takeoff items
    combine: Mapped[str] = mapped_column(String(10), default="sum")  # sum | max
    overridden_qty: Mapped[float | None] = mapped_column(Float, nullable=True)
    rate: Mapped[float | None] = mapped_column(Float, nullable=True)  # suggested from history, or typed in
    rate_overridden: Mapped[bool] = mapped_column(Boolean, default=False)
    rate_sources: Mapped[list | None] = mapped_column(JSON, nullable=True)  # [{rate_id, set, description, unit, rate}]
    rate_note: Mapped[str] = mapped_column(Text, default="")
    needs_measuring: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default="suggested")  # suggested | confirmed
    source: Mapped[str] = mapped_column(String(20), default="ai")  # ai | manual
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
