// Mirrors backend/app/models/validation.py (contracts/validation_report_schema.json). dr = damage ratio, 0-1.

export interface SeverityBucket {
  depth_bucket: string;
  depth_mid_ft: number;
  n: number;
  observed_mean_dr: number;
  observed_ci_low: number;
  observed_ci_high: number;
  hazus_pred_dr: number;
  fitted_pred_dr: number | null;
}

export interface FloodEvent {
  event: string;
  year: number;
  states: string[];
  n_claims: number;
  observed_mean_dr: number;
  hazus_mae: number;
  fitted_mae: number | null;
  bias: number;
  tract_spearman: number | null;
  n_tracts: number | null;
  note: string | null;
}

export interface RankingDecile {
  decile: number;
  expected: number;
  actual: number;
}

export interface Ranking {
  n_tracts: number;
  spearman: number;
  gini: number;
  deciles: RankingDecile[];
}

export interface FloodValidation {
  method: string;
  data_source: string;
  data_vintage: string;
  fetched_on: string; // ISO date
  verdict: string;
  severity_by_depth: SeverityBucket[];
  events: FloodEvent[];
  ranking: Ranking | null;
  adopted: boolean;
  adoption_note: string | null;
}

export interface WildfireFire {
  fire: string;
  year: number;
  n_structures: number;
  destroyed_share: number;
  auc_current: number;
  auc_fitted: number | null;
  calibration_slope: number | null;
  note: string | null;
}

export interface WildfireFeature {
  feature: string;
  n: number;
  odds_ratio: number;
  ci_low: number;
  ci_high: number;
  model_implied_ratio: number | null;
  supported: boolean;
}

export interface WildfireValidation {
  method: string;
  data_source: string;
  data_vintage: string;
  fetched_on: string; // ISO date
  verdict: string;
  fires: WildfireFire[];
  features: WildfireFeature[];
  pooled_auc: number | null;
  adopted: boolean;
  adoption_note: string | null;
}

export interface BenchmarkRow {
  name: string;
  n: number;
  concurrency: number | null;
  p50_ms: number;
  p95_ms: number;
  p99_ms: number;
  rps: number | null;
}

export interface SourceRef {
  name: string;
  url: string;
  vintage: string;
}

export interface ModelCard {
  constants_total: number;
  constants_validated: number;
  constants_calibration: number;
  perils: string[];
  sources: SourceRef[];
}

export type ValidationStatus = "COMPLETE" | "PARTIAL" | "PENDING";

export interface ValidationReport {
  schema_version: "1.0";
  generated_at: string; // ISO datetime
  model_commit: string;
  status: ValidationStatus;
  flood: FloodValidation | null;
  wildfire: WildfireValidation | null;
  benchmarks: BenchmarkRow[];
  model_card: ModelCard;
}
