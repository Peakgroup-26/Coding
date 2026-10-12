"""Core tables from the brief's data model, plus the supporting tables Phase 1 needs.

Geometry is stored in sheet coordinates: PDF points (1/72 inch) on the page as displayed
(rotation applied), origin top-left. Screen pixels are never stored.
"""
from datetime import date, datetime, timezone

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text
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
    price_book_version_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # Phase 3
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

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
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    entity: Mapped[str] = mapped_column(String(50))
    entity_id: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(20))  # create | update | delete
    before: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    after: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
