"""Core tables from the brief's data model, plus the supporting tables Phase 1 needs.

Geometry is stored in sheet coordinates: PDF points (1/72 inch) on the page as displayed
(rotation applied), origin top-left. Screen pixels are never stored.
"""
from datetime import date, datetime, timezone

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, false, true
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
    # What this user can see and do. Admins can always do everything.
    can_hydraulic: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())  # plumbing jobs
    can_civil: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())  # civil jobs
    can_all_jobs: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())  # other people's and previous tenders
    can_past_rates: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())  # previous civil job rates
    can_pricing: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())  # price books, mappings, rules
    sectors: Mapped[list | None] = mapped_column(JSON, nullable=True)  # residential / commercial / maintenance; empty = all
    can_ops: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())  # live jobs, scheduling, purchasing, customers
    can_finance: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())  # WIP, budgets, cash flow, invoices, costs
    # Staff details (ops.py). role "field" = tradies who only use the phone app.
    trade: Mapped[str] = mapped_column(String(30), default="", server_default="")  # plumber | apprentice | labourer | supervisor | office | manager
    phone: Mapped[str] = mapped_column(String(50), default="", server_default="")
    cost_rate: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")  # $/h incl. on-costs (super, workcover, leave)
    charge_rate: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")  # $/h charged out on do-and-charge jobs
    colour: Mapped[str] = mapped_column(String(10), default="", server_default="")  # on the schedule board
    can_hr: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())  # People: profiles, pay, leave, reviews, hiring
    # Per-feature access (features.py): a position preset, plus this person's own changes {feature: none|view|edit}
    position_id: Mapped[int | None] = mapped_column(ForeignKey("positions.id", name="fk_users_position_id_positions", ondelete="SET NULL"), nullable=True)
    features: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class Position(Base):
    """A preset of what a role sees: Estimator, Supervisor, Plumber... {feature key: none | view | edit}."""
    __tablename__ = "positions"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    description: Mapped[str] = mapped_column(String(300), default="")
    features: Mapped[dict] = mapped_column(JSON, default=dict)
    position: Mapped[int] = mapped_column(Integer, default=0)


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
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    # Program and tender outcome (reports.py)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)  # planned start on site
    target_weeks: Mapped[float | None] = mapped_column(Float, nullable=True)  # finish within this many weeks
    program: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # crew and per-stage overrides
    tender_result: Mapped[str] = mapped_column(String(20), default="pending", server_default="pending")  # pending | won | lost | withdrawn
    tender_value: Mapped[float | None] = mapped_column(Float, nullable=True)  # price submitted, ex GST
    # Sales tracking (sales.py)
    sector: Mapped[str] = mapped_column(String(20), default="commercial", server_default="commercial")  # residential | commercial | maintenance
    lead_date: Mapped[date | None] = mapped_column(Date, nullable=True)  # enquiry received
    quote_sent_date: Mapped[date | None] = mapped_column(Date, nullable=True)  # quote returned to the client
    decided_date: Mapped[date | None] = mapped_column(Date, nullable=True)  # won / lost / withdrawn
    lead_source: Mapped[str] = mapped_column(String(100), default="", server_default="")
    contact: Mapped[str] = mapped_column(String(300), default="", server_default="")  # name, phone, email
    work_type: Mapped[str] = mapped_column(String(100), default="", server_default="")  # picked from the sector's list
    value_band: Mapped[str] = mapped_column(String(40), default="", server_default="")  # rough size of the job, e.g. "10k-50k"
    outcome_reason: Mapped[str] = mapped_column(String(100), default="", server_default="")  # why it was lost / withdrawn
    # Live job (ops.py): a won quote or a job raised directly (maintenance). work_status "" = still a quote/tender.
    job_no: Mapped[str] = mapped_column(String(40), default="", server_default="", index=True)
    work_status: Mapped[str] = mapped_column(String(20), default="", server_default="")  # scheduled | in_progress | on_hold | complete | invoiced | closed
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), nullable=True)
    site_id: Mapped[int | None] = mapped_column(ForeignKey("sites.id"), nullable=True)
    order_no: Mapped[str] = mapped_column(String(100), default="", server_default="")  # the client's PO / work order number
    priority: Mapped[str] = mapped_column(String(10), default="normal", server_default="normal")  # low | normal | high | urgent
    description: Mapped[str] = mapped_column(Text, default="", server_default="")  # scope of works / fault description
    billing: Mapped[str] = mapped_column(String(20), default="fixed", server_default="fixed")  # fixed | charge (do-and-charge)
    contract_value: Mapped[float | None] = mapped_column(Float, nullable=True)  # ex GST, before variations
    percent_complete: Mapped[float | None] = mapped_column(Float, nullable=True)  # manual; empty = worked out from cost
    finish_date: Mapped[date | None] = mapped_column(Date, nullable=True)  # planned finish
    supervisor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    retention_pct: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    payment_terms_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    signature: Mapped[str] = mapped_column(Text, default="", server_default="")  # client sign-off on completion (data URL)
    signed_by_name: Mapped[str] = mapped_column(String(200), default="", server_default="")
    # Progress of the automatic read: {state, step, done, total, started_at, finished_at, attention: [...], summary}
    autopilot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Set by accepted tender requirements (tender.py):
    excluded_services: Mapped[list | None] = mapped_column(JSON, nullable=True)  # ["FIRE"]: by others
    spec_materials: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # {"SAN": "Acoustic PVC"}
    rate_adjustments: Mapped[list | None] = mapped_column(JSON, nullable=True)  # [{requirement_id, label, percent, applies_to, ...}]

    @property
    def sales_stage(self) -> str:
        """lead | quoting | quote_sent | won | lost | withdrawn (see sales.py)."""
        from sqlalchemy.orm import object_session

        from .sales import stage

        return stage(object_session(self), self)

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


# --- Tender documents ---
class TenderDocument(Base):
    """A scope, specification, acoustic report, brief, addendum or other tender document for a job."""
    __tablename__ = "tender_documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(500))
    storage_key: Mapped[str] = mapped_column(String(500))
    doc_type: Mapped[str] = mapped_column(String(50), default="")  # scope | specification | acoustic_report | brief | ...
    title: Mapped[str] = mapped_column(String(500), default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    text: Mapped[str] = mapped_column(Text, default="")  # extracted text, with [Page n] markers
    status: Mapped[str] = mapped_column(String(20), default="queued")  # queued | read | failed
    error: Mapped[str] = mapped_column(Text, default="")
    uploaded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TenderRequirement(Base):
    """Something a tender document says that affects the take-off or the price.

    Starts as a suggestion. Accepting it applies its effect (tender.apply), and what was changed is
    kept in `applied` so it can be undone.
    """
    __tablename__ = "tender_requirements"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("tender_documents.id", ondelete="CASCADE"), nullable=True, index=True)
    # material_spec | exclusion | inclusion | allowance | rate_factor | risk | note
    category: Mapped[str] = mapped_column(String(30))
    title: Mapped[str] = mapped_column(String(300))
    quote: Mapped[str] = mapped_column(Text, default="")  # the document's own words
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    service_codes: Mapped[list | None] = mapped_column(JSON, nullable=True)
    civil_category: Mapped[str] = mapped_column(String(200), default="")
    material: Mapped[str] = mapped_column(String(100), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    qty: Mapped[float] = mapped_column(Float, default=0.0)
    unit: Mapped[str] = mapped_column(String(20), default="")
    amount: Mapped[float] = mapped_column(Float, default=0.0)  # $ stated in the document (e.g. a provisional sum)
    allowance_kind: Mapped[str] = mapped_column(String(15), default="")  # pc | provisional | item
    percent: Mapped[float] = mapped_column(Float, default=0.0)  # a loading; set by the estimator unless stated
    applies_to: Mapped[str] = mapped_column(String(15), default="")  # labour | material | all
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(20), default="suggested")  # suggested | accepted | rejected
    applied: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# --- AI memory and chat ---
class AiMemory(Base):
    """Something the AI has learnt and should remember: for every job (company), for one client's
    jobs, or for one job. People can see, edit and delete these in the admin portal."""
    __tablename__ = "ai_memories"
    id: Mapped[int] = mapped_column(primary_key=True)
    scope: Mapped[str] = mapped_column(String(10))  # company | client | job
    client: Mapped[str] = mapped_column(String(255), default="")
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(20), default="")  # hydraulic | civil | "" (both)
    text: Mapped[str] = mapped_column(Text)
    source_job_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # the job it was learnt on
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ChatSession(Base):
    """One conversation with the AI about a job. Its system prompt and tools are fixed when it
    starts, and messages are only ever appended (the API requires the history to stay unchanged)."""
    __tablename__ = "chat_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), nullable=True, index=True)
    scope: Mapped[str] = mapped_column(String(10), default="job", server_default="job")  # job | company (Ask Peak)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)  # Ask Peak: whose conversation
    title: Mapped[str] = mapped_column(String(200), default="", server_default="")
    system: Mapped[str] = mapped_column(Text, default="")
    tool_names: Mapped[list | None] = mapped_column(JSON, nullable=True)
    summary: Mapped[str] = mapped_column(Text, default="")  # carried over from the previous session
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("chat_sessions.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(10))  # user | assistant
    content: Mapped[list] = mapped_column(JSON)  # API content blocks, exactly as sent / received
    text: Mapped[str] = mapped_column(Text, default="")  # what to show on screen
    actions: Mapped[list | None] = mapped_column(JSON, nullable=True)  # [{tool, summary}] for display
    hidden: Mapped[bool] = mapped_column(Boolean, default=False)  # tool results and the like
    reports: Mapped[list | None] = mapped_column(JSON, nullable=True)  # Ask Peak: tables / charts made for the person
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProductivityRate(Base):
    """Labour hours per unit of work, for labour reports and programs when the price book has no
    labour for an item. Peak's own figures: none are built in.

    Hydraulic pipe: service_code (+ DN range, material). Hydraulic items: item_type.
    Civil: civil_category (+ unit and a keyword in the description). The most specific match wins.
    """
    __tablename__ = "productivity_rates"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(20), default="hydraulic")  # hydraulic | civil
    service_code: Mapped[str] = mapped_column(String(20), default="")
    dn_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dn_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    material: Mapped[str] = mapped_column(String(100), default="")
    item_type: Mapped[str] = mapped_column(String(100), default="")
    civil_category: Mapped[str] = mapped_column(String(200), default="")
    keyword: Mapped[str] = mapped_column(String(100), default="")
    unit: Mapped[str] = mapped_column(String(20), default="")
    hours_per_unit: Mapped[float] = mapped_column(Float)
    note: Mapped[str] = mapped_column(String(300), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)


# ---------------------------------------------------------------------------
# Operations: customers, staff time, purchasing, costs, project tools, finance
# (ops.py, timesheets.py, purchasing.py, project.py, finance.py, integrations)
# ---------------------------------------------------------------------------
class Customer(Base):
    __tablename__ = "customers"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    kind: Mapped[str] = mapped_column(String(30), default="residential")  # client type, from the CRM list (crm.CLIENT_TYPES)
    email: Mapped[str] = mapped_column(String(255), default="")
    phone: Mapped[str] = mapped_column(String(50), default="")
    address: Mapped[str] = mapped_column(String(500), default="")
    abn: Mapped[str] = mapped_column(String(20), default="")
    terms_days: Mapped[int] = mapped_column(Integer, default=30)
    notes: Mapped[str] = mapped_column(Text, default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    xero_id: Mapped[str] = mapped_column(String(64), default="")
    no_marketing: Mapped[bool] = mapped_column(Boolean, default=False)  # never send review / feedback requests
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CustomerContact(Base):
    __tablename__ = "customer_contacts"
    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    position: Mapped[str] = mapped_column(String(100), default="")
    phone: Mapped[str] = mapped_column(String(50), default="")
    email: Mapped[str] = mapped_column(String(255), default="")


class Site(Base):
    __tablename__ = "sites"
    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    address: Mapped[str] = mapped_column(String(500), default="")
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    access_notes: Mapped[str] = mapped_column(Text, default="")  # keys, codes, parking, hazards
    contact: Mapped[str] = mapped_column(String(300), default="")


class Supplier(Base):
    __tablename__ = "suppliers"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    email: Mapped[str] = mapped_column(String(255), default="")
    phone: Mapped[str] = mapped_column(String(50), default="")
    account_no: Mapped[str] = mapped_column(String(100), default="")
    terms_days: Mapped[int] = mapped_column(Integer, default=30)  # paid this many days after the end of the month of the bill
    kind: Mapped[str] = mapped_column(String(20), default="materials")  # materials | subcontractor | plant | other
    price_format: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # column mapping remembered for its price files
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    xero_id: Mapped[str] = mapped_column(String(64), default="")


class BudgetLine(Base):
    """A job's budget (Simpro cost centres / Procore budget lines): what it should cost, by category."""
    __tablename__ = "budget_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    category: Mapped[str] = mapped_column(String(20))  # labour | materials | subcontract | plant | other
    description: Mapped[str] = mapped_column(String(255), default="")
    stage: Mapped[str] = mapped_column(String(100), default="")
    hours: Mapped[float] = mapped_column(Float, default=0.0)  # labour lines
    cost: Mapped[float] = mapped_column(Float, default=0.0)
    source: Mapped[str] = mapped_column(String(20), default="manual")  # estimate | manual | variation


class ScheduleEntry(Base):
    __tablename__ = "schedule_entries"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), nullable=True, index=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    start: Mapped[str] = mapped_column(String(5), default="07:00")  # HH:MM
    end: Mapped[str] = mapped_column(String(5), default="15:30")
    kind: Mapped[str] = mapped_column(String(20), default="work")  # work | leave | training | other
    notes: Mapped[str] = mapped_column(Text, default="")
    published: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TimeEntry(Base):
    """One stretch of time on a job (QuickBooks Time style). end_at empty = still clocked in."""
    __tablename__ = "time_entries"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id"), nullable=True, index=True)
    task: Mapped[str] = mapped_column(String(100), default="")  # stage / service item, e.g. Rough-in, Travel
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    break_minutes: Mapped[float] = mapped_column(Float, default=0.0)
    break_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    start_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    start_lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    end_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    end_lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(20), default="app")  # app | manual | crew | office
    status: Mapped[str] = mapped_column(String(20), default="open")  # open | submitted | approved | rejected
    cost_rate: Mapped[float | None] = mapped_column(Float, nullable=True)  # $/h frozen when approved
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    edited_reason: Mapped[str] = mapped_column(String(300), default="")
    client_ref: Mapped[str] = mapped_column(String(64), default="", index=True)  # phone's id, so an offline retry isn't doubled
    plant_id: Mapped[int | None] = mapped_column(ForeignKey("plant.id"), nullable=True)  # machine / truck operated (plant hire cost to the job)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TimeOff(Base):
    __tablename__ = "time_off"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20), default="annual")  # annual | sick | rdo | unpaid | other
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="requested")  # requested | approved | declined
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    po_no: Mapped[str] = mapped_column(String(40), index=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id"), nullable=True, index=True)
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"), nullable=True)
    supplier_name: Mapped[str] = mapped_column(String(255), default="")
    category: Mapped[str] = mapped_column(String(20), default="materials")  # materials | subcontract | plant | other
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft | sent | received | billed | cancelled
    order_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    required_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    delivery: Mapped[str] = mapped_column(String(300), default="")  # deliver to site / pick up from branch
    notes: Mapped[str] = mapped_column(Text, default="")
    bill_ref: Mapped[str] = mapped_column(String(100), default="")  # supplier's invoice number
    bill_amount: Mapped[float | None] = mapped_column(Float, nullable=True)  # ex GST
    bill_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    bill_due: Mapped[date | None] = mapped_column(Date, nullable=True)
    bill_paid: Mapped[date | None] = mapped_column(Date, nullable=True)
    xero_id: Mapped[str] = mapped_column(String(64), default="")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    lines: Mapped[list["PoLine"]] = relationship(cascade="all, delete-orphan", order_by="PoLine.id")


class PoLine(Base):
    __tablename__ = "po_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    po_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id", ondelete="CASCADE"), index=True)
    code: Mapped[str] = mapped_column(String(100), default="")
    description: Mapped[str] = mapped_column(String(500), default="")
    qty: Mapped[float] = mapped_column(Float, default=1.0)
    unit: Mapped[str] = mapped_column(String(20), default="ea")
    unit_cost: Mapped[float] = mapped_column(Float, default=0.0)
    received_qty: Mapped[float] = mapped_column(Float, default=0.0)


class JobCost(Base):
    """A cost on a job that isn't time: supplier bills without a PO, materials from the van, plant hire, etc."""
    __tablename__ = "job_costs"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    category: Mapped[str] = mapped_column(String(20), default="materials")
    description: Mapped[str] = mapped_column(String(500), default="")
    qty: Mapped[float] = mapped_column(Float, default=1.0)
    unit_cost: Mapped[float] = mapped_column(Float, default=0.0)
    amount: Mapped[float] = mapped_column(Float, default=0.0)  # qty x unit_cost, ex GST
    supplier: Mapped[str] = mapped_column(String(255), default="")
    ref: Mapped[str] = mapped_column(String(100), default="")
    source: Mapped[str] = mapped_column(String(20), default="office")  # office | field | stock | xero | reece
    sell_unit: Mapped[float | None] = mapped_column(Float, nullable=True)  # price to the customer each (stock items: price file + margin)
    markup_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    paid_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    xero_id: Mapped[str] = mapped_column(String(64), default="")
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Variation(Base):
    __tablename__ = "variations"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    reason: Mapped[str] = mapped_column(String(50), default="client request")  # client request | site instruction | latent condition | design change | other
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending | submitted | approved | rejected
    sell: Mapped[float] = mapped_column(Float, default=0.0)  # ex GST
    cost: Mapped[float] = mapped_column(Float, default=0.0)  # our cost estimate (adds to budget when approved)
    hours: Mapped[float] = mapped_column(Float, default=0.0)
    client_ref: Mapped[str] = mapped_column(String(100), default="")
    submitted_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    decided_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Invoice(Base):
    __tablename__ = "invoices"
    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_no: Mapped[str] = mapped_column(String(40), index=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id"), nullable=True, index=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), nullable=True)
    kind: Mapped[str] = mapped_column(String(20), default="progress")  # progress | final | deposit | service
    issue_date: Mapped[date] = mapped_column(Date)
    due_date: Mapped[date] = mapped_column(Date)
    description: Mapped[str] = mapped_column(Text, default="")
    amount: Mapped[float] = mapped_column(Float, default=0.0)  # ex GST, before retention
    retention: Mapped[float] = mapped_column(Float, default=0.0)  # held back this claim
    gst_pct: Mapped[float] = mapped_column(Float, default=10.0)
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft | sent | paid | void
    paid_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    paid_amount: Mapped[float] = mapped_column(Float, default=0.0)
    xero_id: Mapped[str] = mapped_column(String(64), default="")
    lines: Mapped[list | None] = mapped_column(JSON, nullable=True)  # [{description, qty, unit_price}]
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Document(Base):
    """Stored files: on a job (photos, drawings, contracts, certificates) or company-wide (policies, SWMS)."""
    __tablename__ = "documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), nullable=True, index=True)
    folder: Mapped[str] = mapped_column(String(100), default="General")
    filename: Mapped[str] = mapped_column(String(255))
    path: Mapped[str] = mapped_column(String(500))
    size: Mapped[int] = mapped_column(Integer, default=0)
    mime: Mapped[str] = mapped_column(String(100), default="")
    title: Mapped[str] = mapped_column(String(255), default="")
    version: Mapped[int] = mapped_column(Integer, default=1)
    supersedes_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id"), nullable=True)
    current: Mapped[bool] = mapped_column(Boolean, default=True)
    linked_type: Mapped[str] = mapped_column(String(30), default="")  # project_item | diary | form | po | asset ...
    linked_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    field_visible: Mapped[bool] = mapped_column(Boolean, default=True)  # the boys can open it on the phone
    uploaded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProjectItem(Base):
    """Procore-style project records: RFIs, defects, site instructions, incidents, inspections, observations, submittals."""
    __tablename__ = "project_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    number: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="open")  # open | answered | closed
    priority: Mapped[str] = mapped_column(String(10), default="normal")
    location: Mapped[str] = mapped_column(String(255), default="")
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    assignee_name: Mapped[str] = mapped_column(String(200), default="")  # someone outside the company
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    response: Mapped[str] = mapped_column(Text, default="")
    cost_impact: Mapped[float | None] = mapped_column(Float, nullable=True)
    variation_id: Mapped[int | None] = mapped_column(ForeignKey("variations.id"), nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DailyLog(Base):
    __tablename__ = "daily_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    weather: Mapped[str] = mapped_column(String(50), default="")
    work_done: Mapped[str] = mapped_column(Text, default="")
    delays: Mapped[str] = mapped_column(Text, default="")
    deliveries: Mapped[str] = mapped_column(Text, default="")
    visitors: Mapped[str] = mapped_column(Text, default="")
    safety: Mapped[str] = mapped_column(Text, default="")
    lost_hours: Mapped[float] = mapped_column(Float, default=0.0)  # wet weather / delays
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FormTemplate(Base):
    __tablename__ = "form_templates"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(30), default="checklist")  # swms | prestart | completion | inspection | test | checklist
    fields: Mapped[list] = mapped_column(JSON, default=list)  # [{key, label, type: check|yesno|text|number|choice|signature|photo, options}]
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    required_on_completion: Mapped[bool] = mapped_column(Boolean, default=False)


class FormResponse(Base):
    __tablename__ = "form_responses"
    id: Mapped[int] = mapped_column(primary_key=True)
    template_id: Mapped[int] = mapped_column(ForeignKey("form_templates.id"))
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), nullable=True, index=True)
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id"), nullable=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    answers: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Asset(Base):
    """Equipment on a site that needs servicing or testing (Simpro maintenance planner)."""
    __tablename__ = "assets"
    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(50))  # Backflow device | TMV | Hot water unit | Grease trap | Pump | Fire hose reel ...
    location: Mapped[str] = mapped_column(String(255), default="")
    make: Mapped[str] = mapped_column(String(100), default="")
    model: Mapped[str] = mapped_column(String(100), default="")
    serial: Mapped[str] = mapped_column(String(100), default="")
    installed: Mapped[date | None] = mapped_column(Date, nullable=True)
    interval_months: Mapped[int] = mapped_column(Integer, default=12)
    last_service: Mapped[date | None] = mapped_column(Date, nullable=True)
    next_due: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    service_price: Mapped[float | None] = mapped_column(Float, nullable=True)  # ex GST, per service
    form_template_id: Mapped[int | None] = mapped_column(ForeignKey("form_templates.id"), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class AssetService(Base):
    __tablename__ = "asset_services"
    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id"), nullable=True)
    day: Mapped[date] = mapped_column(Date)
    result: Mapped[str] = mapped_column(String(20), default="pass")  # pass | fail | serviced | not accessible
    readings: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)


class BudgetMonth(Base):
    """The company's forecast for one month: what we expect to invoice and spend."""
    __tablename__ = "budget_months"
    id: Mapped[int] = mapped_column(primary_key=True)
    month: Mapped[str] = mapped_column(String(7), unique=True)  # YYYY-MM
    revenue: Mapped[float] = mapped_column(Float, default=0.0)
    labour: Mapped[float] = mapped_column(Float, default=0.0)
    materials: Mapped[float] = mapped_column(Float, default=0.0)
    subcontract: Mapped[float] = mapped_column(Float, default=0.0)
    overheads: Mapped[float] = mapped_column(Float, default=0.0)
    notes: Mapped[str] = mapped_column(Text, default="")


class SupplierPrice(Base):
    """One line of a supplier's price file. Old prices stay (current = False) for price history."""
    __tablename__ = "supplier_prices"
    id: Mapped[int] = mapped_column(primary_key=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id", ondelete="CASCADE"), index=True)
    code: Mapped[str] = mapped_column(String(100), index=True)  # supplier's product code
    mfr_code: Mapped[str] = mapped_column(String(100), default="", index=True)  # manufacturer's code, to match across suppliers
    barcode: Mapped[str] = mapped_column(String(50), default="", index=True)
    description: Mapped[str] = mapped_column(String(500), default="")
    brand: Mapped[str] = mapped_column(String(100), default="")
    group: Mapped[str] = mapped_column(String(100), default="")  # product line, e.g. "PVC DWV fittings"
    unit: Mapped[str] = mapped_column(String(20), default="ea")
    price: Mapped[float] = mapped_column(Float)  # our trade price, ex GST
    list_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    effective: Mapped[date] = mapped_column(Date, index=True)
    current: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    import_id: Mapped[int | None] = mapped_column(ForeignKey("price_imports.id"), nullable=True)
    product_key: Mapped[str] = mapped_column(String(120), default="", index=True)  # what it's matched on across suppliers


class PriceImport(Base):
    __tablename__ = "price_imports"
    id: Mapped[int] = mapped_column(primary_key=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id", ondelete="CASCADE"))
    filename: Mapped[str] = mapped_column(String(255), default="")
    effective: Mapped[date] = mapped_column(Date)
    rows: Mapped[int] = mapped_column(Integer, default=0)
    new_items: Mapped[int] = mapped_column(Integer, default=0)
    price_up: Mapped[int] = mapped_column(Integer, default=0)
    price_down: Mapped[int] = mapped_column(Integer, default=0)
    source: Mapped[str] = mapped_column(String(20), default="file")  # file | reece_max | api
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProductMatch(Base):
    """People's say on which supplier codes are the same product (or aren't), overriding the automatic match."""
    __tablename__ = "product_matches"
    id: Mapped[int] = mapped_column(primary_key=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(String(100))
    product_key: Mapped[str] = mapped_column(String(120))
    __table_args__ = (UniqueConstraint("supplier_id", "code"),)


class Integration(Base):
    """A connection to another system (Xero, Reece maX): tokens and sync state. Secrets never leave the server."""
    __tablename__ = "integrations"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(30), unique=True)  # xero | reece
    status: Mapped[str] = mapped_column(String(20), default="disconnected")  # disconnected | connected | error
    tenant_id: Mapped[str] = mapped_column(String(64), default="")
    tenant_name: Mapped[str] = mapped_column(String(255), default="")
    access_token: Mapped[str] = mapped_column(Text, default="")
    refresh_token: Mapped[str] = mapped_column(Text, default="")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    settings: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # account codes, what to sync
    last_sync: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str] = mapped_column(Text, default="")
    log: Mapped[list | None] = mapped_column(JSON, nullable=True)  # recent sync results


class Counter(Base):
    """Running numbers: job, PO, invoice."""
    __tablename__ = "counters"
    name: Mapped[str] = mapped_column(String(40), primary_key=True)
    value: Mapped[int] = mapped_column(Integer, default=0)


# --- CRM: follow-ups after invoices, feedback and NPS (crm.py) ---
class CrmRule(Base):
    """What to send, to whom, and when: e.g. 3 days after a residential invoice, ask for a Google review."""
    __tablename__ = "crm_rules"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    trigger: Mapped[str] = mapped_column(String(20), default="invoice_sent")  # crm.TRIGGERS
    client_types: Mapped[list | None] = mapped_column(JSON, nullable=True)  # empty = all
    departments: Mapped[list | None] = mapped_column(JSON, nullable=True)  # residential | commercial | maintenance | civil; empty = all
    delay_days: Mapped[int] = mapped_column(Integer, default=2)
    channel: Mapped[str] = mapped_column(String(10), default="email")  # email | sms
    subject: Mapped[str] = mapped_column(String(255), default="")
    body: Mapped[str] = mapped_column(Text, default="")  # {first_name} {customer} {job} {job_no} {feedback_link} {review_link} {company}
    ask_feedback: Mapped[bool] = mapped_column(Boolean, default=True)
    ask_review: Mapped[bool] = mapped_column(Boolean, default=False)
    min_days_between: Mapped[int] = mapped_column(Integer, default=30)  # don't pester the same customer
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class OutboundMessage(Base):
    __tablename__ = "outbound_messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"), nullable=True, index=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id"), nullable=True)
    invoice_id: Mapped[int | None] = mapped_column(ForeignKey("invoices.id"), nullable=True)
    rule_id: Mapped[int | None] = mapped_column(ForeignKey("crm_rules.id"), nullable=True)
    feedback_id: Mapped[int | None] = mapped_column(ForeignKey("feedback.id"), nullable=True)
    channel: Mapped[str] = mapped_column(String(10), default="email")
    to: Mapped[str] = mapped_column(String(255), default="")
    subject: Mapped[str] = mapped_column(String(255), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    send_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(20), default="queued")  # queued | sent | failed | cancelled | skipped
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Feedback(Base):
    """One feedback request and, once answered, the answer. The token is the private link the customer opens."""
    __tablename__ = "feedback"
    id: Mapped[int] = mapped_column(primary_key=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"), nullable=True, index=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id"), nullable=True)
    kind: Mapped[str] = mapped_column(String(20), default="job")  # job | monthly
    department: Mapped[str] = mapped_column(String(20), default="")  # residential | commercial | maintenance | civil
    period: Mapped[str] = mapped_column(String(7), default="")  # YYYY-MM for monthly check-ins
    contact_name: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 0-10: how likely to recommend us
    ratings: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # {quality: 1-5, communication, timeliness, cleanliness, value}
    comment: Mapped[str] = mapped_column(Text, default="")
    review_clicked: Mapped[bool] = mapped_column(Boolean, default=False)
    followed_up: Mapped[bool] = mapped_column(Boolean, default=False)  # someone has called about a low score


class CrmActivity(Base):
    """The customer's timeline: calls, meetings, notes, and what the system sent."""
    __tablename__ = "crm_activities"
    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20), default="note")  # note | call | meeting | email | task
    text: Mapped[str] = mapped_column(Text, default="")
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)  # tasks: follow up by
    done: Mapped[bool] = mapped_column(Boolean, default=False)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id"), nullable=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# --- Plant and vehicles (Plant Assessor style): register, pre-starts, defects, photos (plant.py) ---
class Plant(Base):
    __tablename__ = "plant"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(20), default="plant")  # vehicle | plant | trailer | tool
    name: Mapped[str] = mapped_column(String(200))  # e.g. "5t excavator", "Hilux – Dave"
    fleet_no: Mapped[str] = mapped_column(String(50), default="")
    category: Mapped[str] = mapped_column(String(50), default="")  # Excavator, Skid steer, Tipper, Ute, Roller...
    rego: Mapped[str] = mapped_column(String(20), default="")
    make: Mapped[str] = mapped_column(String(100), default="")
    model: Mapped[str] = mapped_column(String(100), default="")
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    serial: Mapped[str] = mapped_column(String(100), default="")  # VIN / serial
    assigned_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)  # company vehicle driven by
    hours: Mapped[float | None] = mapped_column(Float, nullable=True)  # hour meter, latest reading
    odometer: Mapped[float | None] = mapped_column(Float, nullable=True)  # km, latest reading
    service_every_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    service_every_km: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_service_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_service_km: Mapped[float | None] = mapped_column(Float, nullable=True)
    next_service_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    rego_expiry: Mapped[date | None] = mapped_column(Date, nullable=True)
    insurance_expiry: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="in_service")  # in_service | out_of_service | in_repair | sold
    hire_rate: Mapped[float] = mapped_column(Float, default=0.0)  # internal $/h charged to the job when operated
    checklist_id: Mapped[int | None] = mapped_column(ForeignKey("form_templates.id"), nullable=True)  # its pre-start questions
    photos_required: Mapped[bool] = mapped_column(Boolean, default=True)  # machine + fuel gauge photos at start and end of day
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PlantCheck(Base):
    """A pre-start, start/end-of-day photo set, weekly vehicle check or wash, done on the phone."""
    __tablename__ = "plant_checks"
    id: Mapped[int] = mapped_column(primary_key=True)
    plant_id: Mapped[int] = mapped_column(ForeignKey("plant.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(20))  # prestart | start_day | end_day | weekly | wash | service
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    answers: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    passed: Mapped[bool] = mapped_column(Boolean, default=True)
    hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    odometer: Mapped[float | None] = mapped_column(Float, nullable=True)
    fuel_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    photo_ids: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # {"machine": doc_id, "fuel": doc_id, "exterior": ..., "interior": ...}
    time_entry_id: Mapped[int | None] = mapped_column(ForeignKey("time_entries.id"), nullable=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id"), nullable=True)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")


class PlantDefect(Base):
    __tablename__ = "plant_defects"
    id: Mapped[int] = mapped_column(primary_key=True)
    plant_id: Mapped[int] = mapped_column(ForeignKey("plant.id", ondelete="CASCADE"), index=True)
    reported_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    kind: Mapped[str] = mapped_column(String(20), default="defect")  # defect | damage | incident
    severity: Mapped[str] = mapped_column(String(10), default="minor")  # minor | major | critical (takes it out of service)
    description: Mapped[str] = mapped_column(Text, default="")
    photo_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    check_id: Mapped[int | None] = mapped_column(ForeignKey("plant_checks.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="open")  # open | in_repair | fixed | no_action
    fixed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fixed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    repair_notes: Mapped[str] = mapped_column(Text, default="")
    repair_cost: Mapped[float | None] = mapped_column(Float, nullable=True)


class Notification(Base):
    """In-app reminders and alerts (wash your vehicle, timesheet to approve, low feedback score...)."""
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(30))
    text: Mapped[str] = mapped_column(Text)
    link: Mapped[str] = mapped_column(String(300), default="")
    key: Mapped[str] = mapped_column(String(100), default="", index=True)  # stops the same reminder being made twice
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# --- People (hr.py): the BambooHR side ---
class EmployeeProfile(Base):
    """Everything about a person beyond their sign-in. Only people with can_hr (and the person) see it."""
    __tablename__ = "employee_profiles"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    position: Mapped[str] = mapped_column(String(100), default="")  # Plumber, 2nd year apprentice, Estimator...
    department: Mapped[str] = mapped_column(String(50), default="")  # plumbing | civil | maintenance | office | management
    employment_type: Mapped[str] = mapped_column(String(20), default="full_time")  # full_time | part_time | casual | apprentice | contractor
    status: Mapped[str] = mapped_column(String(20), default="active")  # active | on_leave | terminated
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_reason: Mapped[str] = mapped_column(String(50), default="")  # resigned | terminated | end of contract | retired
    manager_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    hours_per_week: Mapped[float] = mapped_column(Float, default=38.0)
    award: Mapped[str] = mapped_column(String(100), default="")  # Plumbing and Fire Sprinklers Award 2020 ...
    apprentice_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dob: Mapped[date | None] = mapped_column(Date, nullable=True)
    personal_email: Mapped[str] = mapped_column(String(255), default="")
    address: Mapped[str] = mapped_column(String(500), default="")
    emergency_contacts: Mapped[list] = mapped_column(JSON, default=list)  # [{name, relationship, phone}]
    drivers_licence: Mapped[str] = mapped_column(String(50), default="")  # class, e.g. C, HR
    shirt_size: Mapped[str] = mapped_column(String(10), default="")
    pants_size: Mapped[str] = mapped_column(String(10), default="")
    boot_size: Mapped[str] = mapped_column(String(10), default="")
    medical_notes: Mapped[str] = mapped_column(Text, default="")  # allergies etc. for first aid
    notes: Mapped[str] = mapped_column(Text, default="")
    photo_key: Mapped[str] = mapped_column(String(500), default="")


class PayChange(Base):
    """Pay history: a new row for every pay rise, promotion or change of hours."""
    __tablename__ = "pay_changes"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    effective: Mapped[date] = mapped_column(Date)
    pay_type: Mapped[str] = mapped_column(String(10), default="hourly")  # hourly | salary
    amount: Mapped[float] = mapped_column(Float)  # $/h or $/year
    position: Mapped[str] = mapped_column(String(100), default="")
    reason: Mapped[str] = mapped_column(String(100), default="")  # Pay review, Apprentice year, Promotion, Award increase
    notes: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CredentialType(Base):
    """Licences, tickets, inductions and training courses, and who must hold them."""
    __tablename__ = "credential_types"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    category: Mapped[str] = mapped_column(String(20), default="licence")  # licence | ticket | training | induction
    renew_months: Mapped[int | None] = mapped_column(Integer, nullable=True)  # expiry worked out from completion when set
    required_for: Mapped[list] = mapped_column(JSON, default=list)  # trades, e.g. ["plumber", "apprentice"]; ["*"] = everyone
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Credential(Base):
    __tablename__ = "credentials"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    type_id: Mapped[int] = mapped_column(ForeignKey("credential_types.id"), index=True)
    number: Mapped[str] = mapped_column(String(100), default="")
    issuer: Mapped[str] = mapped_column(String(100), default="")  # QBCC, RTO name...
    issued: Mapped[date | None] = mapped_column(Date, nullable=True)
    expires: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    hours: Mapped[float | None] = mapped_column(Float, nullable=True)  # training hours
    cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    file_key: Mapped[str] = mapped_column(String(500), default="")  # photo of the card / certificate
    file_name: Mapped[str] = mapped_column(String(255), default="")
    verified_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LeavePolicy(Base):
    """How a kind of leave builds up. Kinds match time_off.kind (annual, sick, long_service, rdo...)."""
    __tablename__ = "leave_policies"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    hours_per_year: Mapped[float] = mapped_column(Float, default=0.0)  # for a 38 h week; pro-rata to hours worked
    accrues_on_hours: Mapped[bool] = mapped_column(Boolean, default=True)  # build up with ordinary hours worked, not just time
    after_years: Mapped[float] = mapped_column(Float, default=0.0)  # long service: only usable after this many years
    casuals: Mapped[bool] = mapped_column(Boolean, default=False)  # casuals accrue it too
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class LeaveAdjustment(Base):
    """Opening balances and manual corrections (in hours; minus takes leave off)."""
    __tablename__ = "leave_adjustments"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    day: Mapped[date] = mapped_column(Date)
    hours: Mapped[float] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(String(200), default="")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)


class ChecklistTemplate(Base):
    """Onboarding / offboarding steps: [{title, who: hr|manager|employee, due_days, policy_id?, credential_type_id?}]."""
    __tablename__ = "checklist_templates"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(20), default="onboarding")  # onboarding | offboarding
    tasks: Mapped[list] = mapped_column(JSON, default=list)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class ChecklistTask(Base):
    __tablename__ = "checklist_tasks"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)  # the person being on/offboarded
    kind: Mapped[str] = mapped_column(String(20), default="onboarding")
    template_id: Mapped[int | None] = mapped_column(ForeignKey("checklist_templates.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(300))
    who: Mapped[str] = mapped_column(String(20), default="hr")  # hr | manager | employee
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    due: Mapped[date | None] = mapped_column(Date, nullable=True)
    policy_id: Mapped[int | None] = mapped_column(ForeignKey("policies.id"), nullable=True)  # done when signed
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    done_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    position: Mapped[int] = mapped_column(Integer, default=0)


class Policy(Base):
    """Company policies and contracts people read and sign (drug & alcohol, code of conduct, vehicle use...)."""
    __tablename__ = "policies"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text, default="")  # text to read on the phone, or blank when it's a file
    file_key: Mapped[str] = mapped_column(String(500), default="")
    file_name: Mapped[str] = mapped_column(String(255), default="")
    version: Mapped[int] = mapped_column(Integer, default=1)
    audience: Mapped[str] = mapped_column(String(20), default="all")  # all | field | office | none (only when sent)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PolicySignature(Base):
    __tablename__ = "policy_signatures"
    __table_args__ = (UniqueConstraint("policy_id", "version", "user_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    policy_id: Mapped[int] = mapped_column(ForeignKey("policies.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    typed_name: Mapped[str] = mapped_column(String(200))
    signature: Mapped[str] = mapped_column(Text, default="")  # data URL of the drawn signature
    signed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ip: Mapped[str] = mapped_column(String(60), default="")


class ReviewCycle(Base):
    __tablename__ = "review_cycles"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))  # "2026 annual review", "Apprentice 6-month"
    due: Mapped[date | None] = mapped_column(Date, nullable=True)
    questions: Mapped[list] = mapped_column(JSON, default=list)  # [{key, label, type: rating|text}]
    status: Mapped[str] = mapped_column(String(20), default="open")  # open | closed
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Review(Base):
    __tablename__ = "reviews"
    __table_args__ = (UniqueConstraint("cycle_id", "user_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    cycle_id: Mapped[int] = mapped_column(ForeignKey("review_cycles.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    reviewer_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    self_answers: Mapped[dict] = mapped_column(JSON, default=dict)
    manager_answers: Mapped[dict] = mapped_column(JSON, default=dict)
    self_done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    manager_done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    shared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # the person can see the manager's side
    overall: Mapped[float | None] = mapped_column(Float, nullable=True)


class Goal(Base):
    __tablename__ = "goals"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text, default="")
    due: Mapped[date | None] = mapped_column(Date, nullable=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)  # 0-100
    status: Mapped[str] = mapped_column(String(20), default="open")  # open | done | dropped
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Survey(Base):
    """Staff pulse / eNPS surveys. Answers are anonymous unless the survey says otherwise."""
    __tablename__ = "surveys"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    questions: Mapped[list] = mapped_column(JSON, default=list)  # [{key, label, type: enps|rating|text|choice, options}]
    anonymous: Mapped[bool] = mapped_column(Boolean, default=True)
    audience: Mapped[str] = mapped_column(String(20), default="all")  # all | field | office
    status: Mapped[str] = mapped_column(String(20), default="open")  # open | closed
    closes: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SurveyInvite(Base):
    """Who has answered, kept apart from the answers so anonymous answers can't be traced back."""
    __tablename__ = "survey_invites"
    __table_args__ = (UniqueConstraint("survey_id", "user_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    survey_id: Mapped[int] = mapped_column(ForeignKey("surveys.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    answered: Mapped[bool] = mapped_column(Boolean, default=False)


class SurveyResponse(Base):
    __tablename__ = "survey_responses"
    id: Mapped[int] = mapped_column(primary_key=True)
    survey_id: Mapped[int] = mapped_column(ForeignKey("surveys.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)  # blank when anonymous
    department: Mapped[str] = mapped_column(String(50), default="")
    answers: Mapped[dict] = mapped_column(JSON, default=dict)
    month: Mapped[str] = mapped_column(String(7), default="")  # YYYY-MM only, no time stamp, so answers can't be matched to invites


class JobOpening(Base):
    __tablename__ = "job_openings"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    department: Mapped[str] = mapped_column(String(50), default="")
    employment_type: Mapped[str] = mapped_column(String(20), default="full_time")
    location: Mapped[str] = mapped_column(String(200), default="Sunshine Coast")
    pay: Mapped[str] = mapped_column(String(100), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    questions: Mapped[list] = mapped_column(JSON, default=list)  # extra questions on the application form: [{key, label}]
    status: Mapped[str] = mapped_column(String(20), default="open")  # draft | open | closed
    hiring_manager_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Candidate(Base):
    __tablename__ = "candidates"
    id: Mapped[int] = mapped_column(primary_key=True)
    opening_id: Mapped[int | None] = mapped_column(ForeignKey("job_openings.id", ondelete="SET NULL"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(255), default="")
    phone: Mapped[str] = mapped_column(String(50), default="")
    stage: Mapped[str] = mapped_column(String(20), default="applied")  # applied | screen | interview | offer | hired | rejected
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 1-5
    source: Mapped[str] = mapped_column(String(50), default="careers page")
    answers: Mapped[dict] = mapped_column(JSON, default=dict)
    cover_note: Mapped[str] = mapped_column(Text, default="")
    resume_key: Mapped[str] = mapped_column(String(500), default="")
    resume_name: Mapped[str] = mapped_column(String(255), default="")
    hired_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CandidateNote(Base):
    __tablename__ = "candidate_notes"
    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Announcement(Base):
    __tablename__ = "announcements"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text, default="")
    audience: Mapped[str] = mapped_column(String(20), default="all")  # all | field | office
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    expires: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class IssuedItem(Base):
    """Company gear a person has: phone, laptop, tool kits, keys, fuel card, uniform."""
    __tablename__ = "issued_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    item: Mapped[str] = mapped_column(String(200))
    serial: Mapped[str] = mapped_column(String(100), default="")
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    issued: Mapped[date | None] = mapped_column(Date, nullable=True)
    returned: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")


class EmployeeFile(Base):
    """Private files on a person's record (contract, tax form scan, warnings). Kept apart from company documents."""
    __tablename__ = "employee_files"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    folder: Mapped[str] = mapped_column(String(50), default="General")  # Contract | Licences | Performance | Medical | General
    filename: Mapped[str] = mapped_column(String(255))
    key: Mapped[str] = mapped_column(String(500))
    mime: Mapped[str] = mapped_column(String(100), default="")
    size: Mapped[int] = mapped_column(Integer, default=0)
    employee_can_see: Mapped[bool] = mapped_column(Boolean, default=True)
    uploaded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# --- Boards (boards.py): the Monday.com side ---
class Board(Base):
    __tablename__ = "boards"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    private: Mapped[bool] = mapped_column(Boolean, default=False)  # only members (and admins) can see it
    members: Mapped[list] = mapped_column(JSON, default=list)  # user ids
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True, index=True)
    template: Mapped[str] = mapped_column(String(50), default="")
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class BoardColumn(Base):
    __tablename__ = "board_columns"
    __table_args__ = (UniqueConstraint("board_id", "key"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    board_id: Mapped[int] = mapped_column(ForeignKey("boards.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(100))
    # text | long_text | status | person | date | timeline | number | money | dropdown | checkbox | rating | progress
    # | job | customer | link | phone | email | time | tags | files
    type: Mapped[str] = mapped_column(String(20))
    settings: Mapped[dict] = mapped_column(JSON, default=dict)  # labels [{key, label, colour, done}], options, unit
    position: Mapped[int] = mapped_column(Integer, default=0)


class BoardGroup(Base):
    __tablename__ = "board_groups"
    id: Mapped[int] = mapped_column(primary_key=True)
    board_id: Mapped[int] = mapped_column(ForeignKey("boards.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(100))
    colour: Mapped[str] = mapped_column(String(10), default="#579bfc")
    position: Mapped[int] = mapped_column(Integer, default=0)


class BoardItem(Base):
    __tablename__ = "board_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    board_id: Mapped[int] = mapped_column(ForeignKey("boards.id", ondelete="CASCADE"), index=True)
    group_id: Mapped[int | None] = mapped_column(ForeignKey("board_groups.id", ondelete="SET NULL"), nullable=True, index=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("board_items.id", ondelete="CASCADE"), nullable=True, index=True)  # subitem
    name: Mapped[str] = mapped_column(String(300))
    values: Mapped[dict] = mapped_column(JSON, default=dict)  # {column key: value}
    depends_on: Mapped[list] = mapped_column(JSON, default=list)  # item ids that must finish first (timeline)
    position: Mapped[float] = mapped_column(Float, default=0.0)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ItemUpdate(Base):
    """The conversation on an item: updates, replies and @mentions."""
    __tablename__ = "item_updates"
    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("board_items.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reply_to: Mapped[int | None] = mapped_column(ForeignKey("item_updates.id", ondelete="CASCADE"), nullable=True)
    body: Mapped[str] = mapped_column(Text)
    mentions: Mapped[list] = mapped_column(JSON, default=list)
    liked_by: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ItemFile(Base):
    __tablename__ = "item_files"
    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("board_items.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    key: Mapped[str] = mapped_column(String(500))
    mime: Mapped[str] = mapped_column(String(100), default="")
    size: Mapped[int] = mapped_column(Integer, default=0)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ItemActivity(Base):
    """Activity log: who changed which column, from what to what."""
    __tablename__ = "item_activity"
    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("board_items.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)  # blank = an automation
    what: Mapped[str] = mapped_column(String(100))
    old: Mapped[str] = mapped_column(Text, default="")
    new: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class BoardAutomation(Base):
    """When <trigger> then <actions>, e.g. when Status changes to Done, notify the owner and move the item to Done."""
    __tablename__ = "board_automations"
    id: Mapped[int] = mapped_column(primary_key=True)
    board_id: Mapped[int] = mapped_column(ForeignKey("boards.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    trigger: Mapped[dict] = mapped_column(JSON, default=dict)
    actions: Mapped[list] = mapped_column(JSON, default=list)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    runs: Mapped[int] = mapped_column(Integer, default=0)
    last_run: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str] = mapped_column(Text, default="")


class BoardView(Base):
    __tablename__ = "board_views"
    id: Mapped[int] = mapped_column(primary_key=True)
    board_id: Mapped[int] = mapped_column(ForeignKey("boards.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    type: Mapped[str] = mapped_column(String(20), default="table")  # table | kanban | calendar | timeline | workload | chart
    settings: Mapped[dict] = mapped_column(JSON, default=dict)  # {column, filter: {person, status, text}, sort}


class BoardForm(Base):
    """A form that adds an item to a board; can be public (customers, subbies) or staff only."""
    __tablename__ = "board_forms"
    id: Mapped[int] = mapped_column(primary_key=True)
    board_id: Mapped[int] = mapped_column(ForeignKey("boards.id", ondelete="CASCADE"), index=True)
    token: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(200))
    intro: Mapped[str] = mapped_column(Text, default="")
    columns: Mapped[list] = mapped_column(JSON, default=list)  # column keys on the form
    group_id: Mapped[int | None] = mapped_column(ForeignKey("board_groups.id", ondelete="SET NULL"), nullable=True)
    public: Mapped[bool] = mapped_column(Boolean, default=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


# --- Estimating workbook (estimating.py): the CostX / CANDY side ---
class Resource(Base):
    """A priced resource: a labour grade, a machine, a material, a subcontract rate. Change it and every build-up follows."""
    __tablename__ = "resources"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True)
    kind: Mapped[str] = mapped_column(String(20), default="material")  # labour | plant | material | subcontract | other
    description: Mapped[str] = mapped_column(String(300), default="")
    unit: Mapped[str] = mapped_column(String(20), default="ea")
    rate: Mapped[float] = mapped_column(Float, default=0.0)  # $ per unit, ex GST
    supplier: Mapped[str] = mapped_column(String(100), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RateBuildup(Base):
    """A rate built from resources, e.g. 1 m of 100 mm sewer in 1.2 m trench = 0.25 h plumber + 0.1 h excavator + 1.05 m pipe."""
    __tablename__ = "rate_buildups"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True)
    description: Mapped[str] = mapped_column(String(300), default="")
    unit: Mapped[str] = mapped_column(String(20), default="m")
    lines: Mapped[list] = mapped_column(JSON, default=list)  # [{resource: code, qty: per unit, waste_pct}]
    notes: Mapped[str] = mapped_column(Text, default="")


class EstimateVariable(Base):
    """Named numbers used in workbook formulas: weeks on site, levels, units, supervisors..."""
    __tablename__ = "estimate_variables"
    __table_args__ = (UniqueConstraint("job_id", "name"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(40))
    value: Mapped[float] = mapped_column(Float, default=0.0)
    note: Mapped[str] = mapped_column(String(200), default="")


class EstimateLine(Base):
    """A workbook row: quantity typed, from a formula, or linked live to a take-off dimension; rate typed or built up."""
    __tablename__ = "estimate_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    section: Mapped[str] = mapped_column(String(100), default="General")  # Preliminaries, Sanitary drainage, Subcontract...
    position: Mapped[float] = mapped_column(Float, default=0.0)
    ref: Mapped[str] = mapped_column(String(30), default="")
    description: Mapped[str] = mapped_column(String(500))
    qty_source: Mapped[str] = mapped_column(String(10), default="manual")  # manual | formula | takeoff
    qty: Mapped[float] = mapped_column(Float, default=0.0)
    formula: Mapped[str] = mapped_column(String(500), default="")  # uses variables, and q = the linked take-off quantity
    dimension: Mapped[str] = mapped_column(String(200), default="")  # take-off key, e.g. run:SAN:100:PVC or count:SAN:WC
    uom: Mapped[str] = mapped_column(String(20), default="item")
    rate_source: Mapped[str] = mapped_column(String(10), default="manual")  # manual | buildup | resource
    rate_code: Mapped[str] = mapped_column(String(50), default="")
    # unit costs per category when typed (buildup / resource fill these in when priced)
    labour_hours: Mapped[float] = mapped_column(Float, default=0.0)
    labour_rate: Mapped[float] = mapped_column(Float, default=0.0)
    material: Mapped[float] = mapped_column(Float, default=0.0)
    plant: Mapped[float] = mapped_column(Float, default=0.0)
    subcontract: Mapped[float] = mapped_column(Float, default=0.0)
    margin_pct: Mapped[float | None] = mapped_column(Float, nullable=True)  # blank = the job's margin for its service / stage
    service_id: Mapped[int | None] = mapped_column(ForeignKey("services.id"), nullable=True)
    stage_id: Mapped[int | None] = mapped_column(ForeignKey("stages.id"), nullable=True)
    package_id: Mapped[int | None] = mapped_column(ForeignKey("trade_packages.id", ondelete="SET NULL"), nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")


class TradePackage(Base):
    """A subcontract or supply package sent out for quotes, then levelled and awarded (subcontractor comparison)."""
    __tablename__ = "trade_packages"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))  # Concrete cutting, Excavation, Fire services, Hot water supply
    kind: Mapped[str] = mapped_column(String(15), default="subcontract")  # subcontract | supply
    scope: Mapped[str] = mapped_column(Text, default="")
    due: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(15), default="open")  # open | awarded
    awarded_quote_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    section: Mapped[str] = mapped_column(String(100), default="Subcontract")
    stage_id: Mapped[int | None] = mapped_column(ForeignKey("stages.id"), nullable=True)
    margin_pct: Mapped[float | None] = mapped_column(Float, nullable=True)


class PackageQuote(Base):
    __tablename__ = "package_quotes"
    id: Mapped[int] = mapped_column(primary_key=True)
    package_id: Mapped[int] = mapped_column(ForeignKey("trade_packages.id", ondelete="CASCADE"), index=True)
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"), nullable=True)
    company: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[str] = mapped_column(String(15), default="invited")  # invited | received | declined
    amount: Mapped[float | None] = mapped_column(Float, nullable=True)  # their price ex GST
    adjustments: Mapped[list] = mapped_column(JSON, default=list)  # levelling: [{description, amount}] for what they left out
    exclusions: Mapped[str] = mapped_column(Text, default="")
    valid_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    file_key: Mapped[str] = mapped_column(String(500), default="")
    file_name: Mapped[str] = mapped_column(String(255), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    invited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EstimateSnapshot(Base):
    """A saved copy of the priced estimate, to compare versions (CostX revisions / CANDY estimate versions)."""
    __tablename__ = "estimate_snapshots"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    label: Mapped[str] = mapped_column(String(100))
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    lines: Mapped[list] = mapped_column(JSON, default=list)  # [{key, section, description, qty, uom, cost, sell}]
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TenderProgramme(Base):
    """The tender programme: when each stage happens, so the estimate can be spread into a cash flow."""
    __tablename__ = "tender_programmes"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), unique=True)
    start: Mapped[date] = mapped_column(Date)
    retention_pct: Mapped[float] = mapped_column(Float, default=5.0)
    retention_cap_pct: Mapped[float] = mapped_column(Float, default=5.0)  # of the contract sum
    terms_days: Mapped[int] = mapped_column(Integer, default=30)
    pay_suppliers_days: Mapped[int] = mapped_column(Integer, default=30)
    activities: Mapped[list] = mapped_column(JSON, default=list)  # [{name, stages: [...], sections: [...], start_week, weeks, curve}]
