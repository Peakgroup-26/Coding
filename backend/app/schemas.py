from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

Point = tuple[float, float]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- auth / users ---
class LoginIn(BaseModel):
    email: str
    password: str


class UserOut(ORM):
    id: int
    email: str
    name: str
    role: str
    active: bool


class UserIn(BaseModel):
    email: str
    name: str = ""
    role: str = "estimator"
    password: str = Field(min_length=8)


class UserPatch(BaseModel):
    name: str | None = None
    role: str | None = None
    active: bool | None = None
    password: str | None = Field(default=None, min_length=8)


# --- settings ---
class StageIn(BaseModel):
    name: str
    order: int = 0
    active: bool = True


class StageOut(ORM, StageIn):
    id: int


class ServiceIn(BaseModel):
    code: str
    name: str
    colour: str = "#0070C0"
    kind: str = "other"
    default_stage_id: int | None = None
    order: int = 0
    active: bool = True


class ServiceOut(ORM, ServiceIn):
    id: int


class MaterialIn(BaseModel):
    name: str
    waste_pct: float = Field(default=0.0, ge=0, le=100)
    active: bool = True


class MaterialOut(ORM, MaterialIn):
    id: int


class CountTypeIn(BaseModel):
    name: str
    default_service_id: int | None = None
    default_stage_id: int | None = None
    is_fixture: bool = False
    needs_drainage: bool = False
    needs_water: bool = False
    active: bool = True


class CountTypeOut(ORM, CountTypeIn):
    id: int


# --- jobs ---
class JobIn(BaseModel):
    name: str
    client: str = ""
    builder: str = ""
    address: str = ""
    quote_no: str = ""
    due_date: date | None = None
    status: str = "draft"


class JobPatch(BaseModel):
    name: str | None = None
    client: str | None = None
    builder: str | None = None
    address: str | None = None
    quote_no: str | None = None
    due_date: date | None = None
    status: str | None = None


class JobOut(ORM, JobIn):
    id: int
    signed_off_by: int | None = None
    signed_off_at: datetime | None = None
    checks_run_at: datetime | None = None
    price_book_version_id: int | None = None
    margin_basis: str = "markup"
    default_margin_pct: float = 0.0
    service_margins: dict | None = None
    stage_margins: dict | None = None
    gst_pct: float = 10.0
    reference_total_ex_gst: float | None = None


class FileOut(ORM):
    id: int
    job_id: int
    filename: str
    page_count: int
    status: str
    error: str


class LevelIn(BaseModel):
    name: str
    rl: float = 0.0
    floor_to_floor_m: float = Field(default=0.0, ge=0)


class LevelOut(ORM, LevelIn):
    id: int
    job_id: int


# --- sheets ---
class ViewportOut(ORM):
    id: int
    sheet_id: int
    name: str
    bbox: list[float]
    calibrated_scale: float | None
    calibration_data: dict | None
    scale_verified: bool
    verification_data: dict | None


class SheetOut(ORM):
    id: int
    file_id: int
    job_id: int
    page_no: int
    sheet_no: str
    title: str
    revision: str
    drawing_date: str
    width_pt: float
    height_pt: float
    page_size: str
    image_width_px: int
    image_height_px: int
    has_text_layer: bool
    has_vectors: bool
    stated_scale: str
    stated_m_per_pt: float | None
    calibrated_scale: float | None
    calibration_method: str
    calibration_data: dict | None
    scale_verified: bool
    verification_data: dict | None
    classification: str
    services_shown: list[str] | None
    is_hydraulic: bool
    confidence: float
    confirmed: bool
    proposed: dict | None = None
    ai_reading: dict | None = None
    is_current: bool
    is_duplicate: bool
    viewports: list[ViewportOut] = []


class SheetPatch(BaseModel):
    sheet_no: str | None = None
    title: str | None = None
    revision: str | None = None
    drawing_date: str | None = None
    classification: str | None = None
    services_shown: list[str] | None = None
    is_hydraulic: bool | None = None
    confirmed: bool | None = None
    stated_scale: str | None = None


class CalibrateIn(BaseModel):
    method: str = "two_point"  # two_point | stated
    p1: Point | None = None
    p2: Point | None = None
    known_m: float | None = None
    # For method "stated": e.g. ratio=100, paper="A1". If omitted, uses the sheet's stated scale.
    ratio: float | None = None
    paper: str | None = None


class VerifyIn(BaseModel):
    p1: Point
    p2: Point
    known_m: float


class ViewportIn(BaseModel):
    name: str = "Detail"
    bbox: tuple[float, float, float, float]


# --- take-off ---
class RunIn(BaseModel):
    service_id: int
    dn: int = Field(gt=0)
    material: str
    geometry: list[Point] = Field(min_length=1)
    level_id: int | None = None
    stage_id: int | None = None
    location_tag: str = ""
    vertical_mode: str = "none"
    vertical_count: int = 0
    vertical_height_m: float = 0.0
    vertical_from_level_id: int | None = None
    vertical_to_level_id: int | None = None
    waste_pct: float | None = None  # defaults to the material's allowance
    status: str = "confirmed"
    note: str = ""


class RunPatch(BaseModel):
    service_id: int | None = None
    dn: int | None = Field(default=None, gt=0)
    material: str | None = None
    geometry: list[Point] | None = None
    level_id: int | None = None
    stage_id: int | None = None
    location_tag: str | None = None
    vertical_mode: str | None = None
    vertical_count: int | None = None
    vertical_height_m: float | None = None
    vertical_from_level_id: int | None = None
    vertical_to_level_id: int | None = None
    waste_pct: float | None = None
    status: str | None = None
    note: str | None = None


class RunOut(ORM):
    id: int
    job_id: int
    sheet_id: int
    viewport_id: int | None
    service_id: int
    dn: int
    material: str
    level_id: int | None
    stage_id: int | None
    location_tag: str
    geometry: list[list[float]]
    m_per_pt: float
    length_m: float
    vertical_mode: str
    vertical_count: int
    vertical_height_m: float
    vertical_from_level_id: int | None
    vertical_to_level_id: int | None
    vertical_m: float
    waste_pct: float
    status: str
    source: str
    ai_edited: bool = False
    note: str


class CountIn(BaseModel):
    service_id: int
    item_type: str
    x: float
    y: float
    level_id: int | None = None
    stage_id: int | None = None
    location_tag: str = ""
    status: str = "confirmed"


class CountPatch(BaseModel):
    service_id: int | None = None
    item_type: str | None = None
    x: float | None = None
    y: float | None = None
    level_id: int | None = None
    stage_id: int | None = None
    location_tag: str | None = None
    status: str | None = None


class CountOut(ORM):
    id: int
    job_id: int
    sheet_id: int
    service_id: int
    item_type: str
    x: float
    y: float
    level_id: int | None
    stage_id: int | None
    location_tag: str
    status: str
    source: str
    ai_edited: bool = False


# --- Phase 2: rules, generated items, check-measure ---
class CatalogueItemIn(BaseModel):
    code: str
    description: str
    uom: str = "ea"
    cost: float | None = None
    supplier: str = ""
    active: bool = True


class CatalogueItemOut(ORM, CatalogueItemIn):
    id: int


class RuleCondition(BaseModel):
    service_codes: list[str] = []
    materials: list[str] = []
    dn_min: int | None = None
    dn_max: int | None = None
    item_types: list[str] = []
    angle_min: float | None = None
    angle_max: float | None = None
    io_at_ends: bool = False
    io_at_bends: bool = False
    io_interval_m: float | None = Field(default=None, ge=0)


class RuleIn(BaseModel):
    name: str
    trigger_type: str
    condition: RuleCondition = RuleCondition()
    formula: str = "n"
    output_item_id: int | None = None
    output_description: str = ""
    uom: str = "ea"
    stage_id: int | None = None
    active: bool = True


class RuleOut(ORM):
    id: int
    name: str
    trigger_type: str
    condition: dict
    formula: str
    output_item_id: int | None
    output_description: str
    uom: str
    stage_id: int | None
    active: bool
    version: int


class GeneratedItemOut(ORM):
    id: int
    job_id: int
    rule_id: int | None
    rule_version: int | None
    source_ref: str
    source_qty: float | None
    item_id: int | None
    description: str
    uom: str
    service_id: int | None
    dn: int | None
    material: str
    qty: float
    stage_id: int | None
    overridden_qty: float | None
    stage_overridden: bool
    note: str


class GeneratedItemPatch(BaseModel):
    overridden_qty: float | None = Field(default=None, ge=0)
    clear_override: bool = False
    stage_id: int | None = None
    note: str | None = None


class ManualItemIn(BaseModel):
    description: str
    uom: str = "ea"
    qty: float = Field(gt=0)
    service_id: int | None = None
    stage_id: int | None = None
    note: str = ""


class BenchmarkIn(BaseModel):
    name: str
    service_codes: list[str]
    per: str = "fixture"
    min_value: float | None = None
    max_value: float | None = None
    active: bool = True


class BenchmarkOut(ORM, BenchmarkIn):
    id: int


class FlagOut(ORM):
    id: int
    job_id: int
    check_type: str
    severity: str
    ref: str
    sheet_id: int | None
    x: float | None
    y: float | None
    message: str
    status: str
    resolved_by: int | None
    note: str


class FlagPatch(BaseModel):
    status: str  # open | resolved | accepted
    note: str = ""


class AuditOut(ORM):
    id: int
    user_id: int | None
    user_name: str = ""
    entity: str
    entity_id: int
    action: str
    before: dict | None
    after: dict | None
    at: datetime


# --- Phase 3: pricing ---
class PriceBookIn(BaseModel):
    label: str
    notes: str = ""
    copy_from_id: int | None = None


class PriceBookPatch(BaseModel):
    label: str | None = None
    notes: str | None = None
    default_labour_rate_code: str | None = None


class PriceBookOut(ORM):
    id: int
    label: str
    notes: str
    created_at: datetime
    locked: bool
    locked_at: datetime | None
    default_labour_rate_code: str


class PriceItemIn(BaseModel):
    code: str
    description: str = ""
    uom: str = "ea"
    cost: float = Field(ge=0)
    supplier: str = ""


class PriceItemOut(ORM, PriceItemIn):
    id: int
    version_id: int


class PrebuildIn(BaseModel):
    code: str
    description: str = ""
    uom: str = "ea"
    labour_hours: float = Field(default=0, ge=0)
    labour_rate_code: str = ""
    components: list[dict] = []


class PrebuildOut(ORM, PrebuildIn):
    id: int
    version_id: int


class LabourRateIn(BaseModel):
    code: str
    description: str = ""
    rate: float = Field(ge=0)


class LabourRateOut(ORM, LabourRateIn):
    id: int
    version_id: int


class MappingIn(BaseModel):
    source_kind: str  # pipe | count | fitting
    service_code: str = ""
    material: str = ""
    dn: int | None = None
    item_type: str = ""
    description: str = ""
    target_kind: str  # prebuild | item
    target_code: str
    factor: float = Field(default=1.0, gt=0)
    note: str = ""


class MappingOut(ORM, MappingIn):
    id: int


class PricingSettingsIn(BaseModel):
    price_book_version_id: int | None = None
    margin_basis: str = "markup"
    default_margin_pct: float = 0.0
    service_margins: dict[str, float | None] = {}
    stage_margins: dict[str, float | None] = {}
    gst_pct: float = Field(default=10.0, ge=0, le=100)
    reference_total_ex_gst: float | None = None


class AllowanceIn(BaseModel):
    kind: str  # pc | provisional | exclusion
    description: str
    amount: float = Field(default=0.0, ge=0)
    service_id: int | None = None
    stage_id: int | None = None
    apply_margin: bool = True


class AllowanceOut(ORM, AllowanceIn):
    id: int
    job_id: int
