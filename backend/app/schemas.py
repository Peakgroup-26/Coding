from datetime import date

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
    is_fixture: bool = False
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
