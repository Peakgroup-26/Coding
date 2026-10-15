export type Pt = [number, number];

export interface Permissions { can_hydraulic: boolean; can_civil: boolean; can_all_jobs: boolean; can_past_rates: boolean; can_pricing: boolean }
export interface User extends Permissions { id: number; email: string; name: string; role: "estimator" | "reviewer" | "admin"; active: boolean }

export interface ChatAction { tool: string; summary: string }
export interface ChatMsg { id: number; role: "user" | "assistant" | "note"; text: string; actions: ChatAction[]; user?: string; at?: string }
export interface Memory {
  id: number; scope: "company" | "client" | "job"; client: string; job_id: number | null; job: string; kind: string;
  text: string; active: boolean; created_by: string; created_at: string;
}
export interface Stage { id: number; name: string; order: number; active: boolean }
export interface Service { id: number; code: string; name: string; colour: string; kind: string; default_stage_id: number | null; order: number; active: boolean }
export interface Material { id: number; name: string; waste_pct: number; active: boolean }
export interface CountType { id: number; name: string; default_service_id: number | null; default_stage_id: number | null; is_fixture: boolean; needs_drainage: boolean; needs_water: boolean; active: boolean }
export interface Settings { stages: Stage[]; services: Service[]; materials: Material[]; count_types: CountType[] }

export interface Job {
  id: number; name: string; client: string; builder: string; address: string;
  quote_no: string; due_date: string | null; status: string;
  signed_off_by: number | null; signed_off_at: string | null; checks_run_at: string | null;
  kind?: "hydraulic" | "civil"; created_at?: string | null; autopilot?: AutopilotStatus | null; created_by?: number | null;
}

export interface Attention { kind: string; message: string; sheet_id?: number; sheet?: string }

export interface AutopilotStatus {
  state: "never" | "queued" | "running" | "done" | "failed" | "interrupted";
  step?: string; done?: number; total?: number; error?: string;
  started_at?: string; finished_at?: string;
  attention?: Attention[];
  summary?: Record<string, number>;
  running?: boolean;
  tender?: { documents: number; requirements: number; suggested: number; accepted: number };
}

export interface CivilItem { id: number; sheet_id: number | null; sheet: string; description: string; unit: string; qty: number; basis: string; confidence: number }
export interface RateSource { rate_id: number; job: string; description: string; unit: string; rate: number }
export interface CivilLine {
  id: number; sort: number; category: string; description: string; unit: string;
  qty: number; overridden_qty: number | null; effective_qty: number; combine: string;
  rate: number | null; rate_overridden: boolean; rate_sources: RateSource[]; rate_note: string;
  amount: number; needs_measuring: boolean; status: "suggested" | "confirmed"; source: string; note: string;
  items: CivilItem[];
}
export interface CivilLoading { label: string; percent: number; category: string; amount: number }
export interface CivilSummary {
  lines: number; lines_suggested: number; lines_confirmed: number; needs_measuring: number; unpriced: number;
  lines_total_ex_gst: number; loadings: CivilLoading[]; total_confirmed_ex_gst: number;
}

export interface TenderDoc {
  id: number; filename: string; doc_type: string; title: string; summary: string; page_count: number;
  status: "queued" | "read" | "failed"; error: string; created_at: string; requirements: number; suggested: number;
}
export type ReqCategory = "material_spec" | "exclusion" | "inclusion" | "allowance" | "rate_factor" | "risk" | "note";
export interface Requirement {
  id: number; document_id: number | null; document: string; category: ReqCategory; title: string; quote: string;
  page: number | null; service_codes: string[]; civil_category: string; material: string; description: string;
  qty: number; unit: string; amount: number; allowance_kind: string; percent: number; applies_to: string;
  confidence: number; status: "suggested" | "accepted" | "rejected"; effect: string; needs: string;
}
export interface RequirementList {
  requirements: Requirement[]; labels: Record<string, string>;
  excluded_services: string[]; spec_materials: Record<string, string>; loadings: { label: string; percent: number }[];
}
export interface CivilBoq { lines: CivilLine[]; summary: CivilSummary; categories: string[]; units: string[] }
export interface RateSet { id: number; name: string; source_file: string; job_date: string | null; notes: string; active: boolean; created_at: string; rates: number }
export interface CivilRate { id: number; code: string; category: string; description: string; unit: string; rate: number; qty: number | null }

export interface Level { id: number; job_id: number; name: string; rl: number; floor_to_floor_m: number }

export interface Viewport {
  id: number; sheet_id: number; name: string; bbox: [number, number, number, number];
  calibrated_scale: number | null; calibration_data: Record<string, unknown> | null;
  scale_verified: boolean; verification_data: Verification | null;
}

export interface Verification { known_m: number; measured_m: number; error_pct: number; ok: boolean; p1: Pt; p2: Pt }

export interface Sheet {
  id: number; file_id: number; job_id: number; page_no: number;
  sheet_no: string; title: string; revision: string; drawing_date: string;
  width_pt: number; height_pt: number; page_size: string;
  image_width_px: number; image_height_px: number;
  has_text_layer: boolean; has_vectors: boolean;
  stated_scale: string; stated_m_per_pt: number | null;
  calibrated_scale: number | null; calibration_method: string;
  calibration_data: { warning?: string; implied_ratio_at_page_size?: number; stated_diff_pct?: number; p1?: Pt; p2?: Pt; known_m?: number } | null;
  scale_verified: boolean; verification_data: Verification | null;
  classification: string; services_shown: string[] | null; is_hydraulic: boolean;
  confidence: number; confirmed: boolean; is_current: boolean; is_duplicate: boolean;
  proposed: { classification: string; services: string[]; is_hydraulic: boolean; source: string } | null;
  ai_reading: AiReading | null;
  viewports: Viewport[];
}

export interface Run {
  id: number; job_id: number; sheet_id: number; viewport_id: number | null;
  service_id: number; dn: number; material: string; level_id: number | null; stage_id: number | null;
  location_tag: string; geometry: Pt[]; m_per_pt: number; length_m: number;
  vertical_mode: "none" | "manual" | "levels"; vertical_count: number; vertical_height_m: number;
  vertical_from_level_id: number | null; vertical_to_level_id: number | null; vertical_m: number;
  waste_pct: number; status: "suggested" | "confirmed"; source: string; ai_edited: boolean; note: string;
}

export interface CountItem {
  id: number; job_id: number; sheet_id: number; service_id: number; item_type: string;
  x: number; y: number; level_id: number | null; stage_id: number | null; location_tag: string;
  status: "suggested" | "confirmed"; source: string; ai_edited: boolean;
}

export interface TotalsLine {
  service_code: string; service_name: string; colour: string; dn: number; material: string;
  plan_m: number; vertical_m: number; waste_m: number; total_m: number; runs: number;
}

export interface Totals {
  lines: TotalsLine[];
  services: { service_code: string; service_name: string; plan_m: number; vertical_m: number; waste_m: number; total_m: number }[];
  stages: { stage: string; service_code: string; total_m: number }[];
  counts: { service_code: string; item_type: string; stage: string; qty: number }[];
  grand_total_m: number;
  excluded: { suggested_runs: number; suggested_counts: number; superseded_runs: number };
}

export type Trigger = "per_fixture" | "per_metre" | "per_bend" | "per_branch" | "per_io" | "per_job";

export interface RuleCondition {
  service_codes?: string[]; materials?: string[]; dn_min?: number | null; dn_max?: number | null;
  item_types?: string[]; angle_min?: number | null; angle_max?: number | null;
  io_at_ends?: boolean; io_at_bends?: boolean; io_interval_m?: number | null;
}

export interface Rule {
  id: number; name: string; trigger_type: Trigger; condition: RuleCondition; formula: string;
  output_item_id: number | null; output_description: string; uom: string; stage_id: number | null;
  active: boolean; version: number;
}

export interface GeneratedItem {
  id: number; job_id: number; rule_id: number | null; rule_version: number | null; source_ref: string;
  source_qty: number | null; item_id: number | null; description: string; uom: string;
  service_id: number | null; dn: number | null; material: string; qty: number; stage_id: number | null;
  overridden_qty: number | null; stage_overridden: boolean; note: string;
}

export interface Flag {
  id: number; job_id: number; check_type: string; severity: "error" | "warning"; ref: string;
  sheet_id: number | null; x: number | null; y: number | null; message: string;
  status: "open" | "resolved" | "accepted"; resolved_by: number | null; note: string;
}

export interface Benchmark {
  id: number; name: string; service_codes: string[]; per: string;
  min_value: number | null; max_value: number | null; active: boolean;
}

export interface AuditEntry {
  id: number; user_id: number | null; entity: string; entity_id: number; action: string;
  before: Record<string, unknown> | null; after: Record<string, unknown> | null; at: string;
}

export interface StageMatrix {
  services: string[];
  rows: { stage: string; cells: Record<string, number>; total_m: number }[];
  service_totals: Record<string, number>;
  grand_total_m: number;
}

export interface PriceBook {
  id: number; label: string; notes: string; created_at: string; locked: boolean; locked_at: string | null;
  default_labour_rate_code: string; items: number; prebuilds: number; rates: number; jobs: number;
}
export interface PriceItem { id: number; version_id: number; code: string; description: string; uom: string; cost: number; supplier: string }
export interface Prebuild {
  id: number; version_id: number; code: string; description: string; uom: string; labour_hours: number;
  labour_rate_code: string; components: { code: string; qty: number }[];
}
export interface LabourRate { id: number; version_id: number; code: string; description: string; rate: number }

export type SourceKind = "pipe" | "count" | "fitting";
export interface Mapping {
  id: number; source_kind: SourceKind; service_code: string; material: string; dn: number | null; item_type: string;
  description: string; target_kind: "prebuild" | "item"; target_code: string; factor: number; note: string;
}

export interface PricingLine {
  kind: SourceKind; service_code: string; stage: string; description: string; qty: number; uom: string;
  material: string; dn: number | null; item_type: string;
  target_kind?: "prebuild" | "item"; target_code?: string; target_description?: string; target_qty?: number; factor?: number;
  material_cost?: number; labour_hours?: number; labour_cost?: number; cost?: number; margin_pct?: number; sell?: number;
  missing?: string[];
}
export interface Allowance {
  id: number; kind: "pc" | "provisional" | "exclusion"; description: string; amount: number; service_code: string;
  stage: string; apply_margin: boolean; margin_pct?: number; sell?: number;
}
export interface PricingSummary {
  material_cost: number; labour_cost: number; labour_hours: number; allowances_cost: number; cost: number; margin: number;
  sell_ex_gst: number; gst: number; sell_inc_gst: number;
  loading_cost?: number; loadings?: { label: string; percent: number; applies_to: string; service_codes: string[] }[];
  by_service: { service_code: string; cost: number; sell: number; labour_hours: number }[];
  by_stage: { stage: string; cost: number; sell: number; labour_hours: number }[];
  reference_total_ex_gst?: number; reference_variance_pct?: number | null;
}
export interface Pricing {
  price_book: { id: number; label: string; locked: boolean } | null;
  margin_basis: "markup" | "margin";
  lines: PricingLine[]; unmapped: PricingLine[]; missing_codes: string[]; allowances: Allowance[];
  summary: PricingSummary | null;
}

export interface PricingJob extends Job {
  price_book_version_id: number | null; margin_basis: "markup" | "margin"; default_margin_pct: number;
  service_margins: Record<string, number> | null; stage_margins: Record<string, number> | null;
  gst_pct: number; reference_total_ex_gst: number | null;
}

export interface AiReading {
  sheet_no: string; title: string; revision: string; scale_text: string; sheet_type: string; services: string[];
  is_hydraulic: boolean; confidence: number; model: string;
  legend: { description: string; item_type: string; service_code: string }[];
}
export interface AiStatus { enabled: boolean; provider: string | null; model: string | null }
export interface LineStyle {
  key: string; colour: string; dashes: string; width: number; layer: string; segments: number;
  length_pt: number; length_m: number | null; bbox: [number, number, number, number];
  mapping: { service_id: number; dn: number; material: string } | null;
}
export interface AiStats {
  sheets: { sheet_id: number; sheet_no: string; accepted: number; edited: number; rejected: number; pending: number }[];
  classification: { sheets_confirmed: number; type_correct_pct: number | null; services_correct_pct: number | null;
    both_correct_pct: number | null; target_pct: number; by_source: Record<string, { sheets: number; correct_pct: number }> };
  ai: AiStatus;
}
