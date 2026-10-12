export type Pt = [number, number];

export interface User { id: number; email: string; name: string; role: "estimator" | "reviewer" | "admin"; active: boolean }
export interface Stage { id: number; name: string; order: number; active: boolean }
export interface Service { id: number; code: string; name: string; colour: string; default_stage_id: number | null; order: number; active: boolean }
export interface Material { id: number; name: string; waste_pct: number; active: boolean }
export interface CountType { id: number; name: string; default_service_id: number | null; default_stage_id: number | null; is_fixture: boolean; active: boolean }
export interface Settings { stages: Stage[]; services: Service[]; materials: Material[]; count_types: CountType[] }

export interface Job {
  id: number; name: string; client: string; builder: string; address: string;
  quote_no: string; due_date: string | null; status: string;
}

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
  viewports: Viewport[];
}

export interface Run {
  id: number; job_id: number; sheet_id: number; viewport_id: number | null;
  service_id: number; dn: number; material: string; level_id: number | null; stage_id: number | null;
  location_tag: string; geometry: Pt[]; m_per_pt: number; length_m: number;
  vertical_mode: "none" | "manual" | "levels"; vertical_count: number; vertical_height_m: number;
  vertical_from_level_id: number | null; vertical_to_level_id: number | null; vertical_m: number;
  waste_pct: number; status: "suggested" | "confirmed"; source: string; note: string;
}

export interface CountItem {
  id: number; job_id: number; sheet_id: number; service_id: number; item_type: string;
  x: number; y: number; level_id: number | null; stage_id: number | null; location_tag: string;
  status: "suggested" | "confirmed"; source: string;
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
