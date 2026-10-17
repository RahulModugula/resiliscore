// Mirrors contracts/parcel_score_schema.json and backend/app/models/schemas.py. Change all three together.

// USPS codes: 50 states + DC + PR.
export type State =
  | "AL"
  | "AK"
  | "AZ"
  | "AR"
  | "CA"
  | "CO"
  | "CT"
  | "DE"
  | "DC"
  | "FL"
  | "GA"
  | "HI"
  | "ID"
  | "IL"
  | "IN"
  | "IA"
  | "KS"
  | "KY"
  | "LA"
  | "ME"
  | "MD"
  | "MA"
  | "MI"
  | "MN"
  | "MS"
  | "MO"
  | "MT"
  | "NE"
  | "NV"
  | "NH"
  | "NJ"
  | "NM"
  | "NY"
  | "NC"
  | "ND"
  | "OH"
  | "OK"
  | "OR"
  | "PA"
  | "PR"
  | "RI"
  | "SC"
  | "SD"
  | "TN"
  | "TX"
  | "UT"
  | "VT"
  | "VA"
  | "WA"
  | "WV"
  | "WI"
  | "WY";
export type Peril = "FLOOD" | "WILDFIRE" | "WIND_HAIL" | "PLUVIAL" | "SEWER_BACKUP";
export type RoofClass = "CLASS_A_FORTIFIED" | "CLASS_A_IMPACT_4" | "CLASS_A_ASPHALT" | "WOOD_SHAKE_UNRATED";
export type FortifiedTier = "ROOF" | "SILVER" | "GOLD" | "NONE";
export type WphTier = "BASE" | "PLUS" | "NONE";
export type UnderwritingTier = "TIER_1_AUTO_BIND" | "TIER_2_CONDITIONAL" | "TIER_3_DECLINE_ESCALATE";
export type TriggerCode =
  | "NONE"
  | "HITL_TRIGGER_01_SENSOR_DIVERGENCE"
  | "HITL_TRIGGER_02_UNPERMITTED_ADDITION"
  | "HITL_TRIGGER_03_HIGH_TIV"
  | "HITL_TRIGGER_04_BOUNDARY_CONFLICT";
export type FeatureKind =
  | "parcel_polygon"
  | "building_footprint"
  | "zone_0_ring_0_5ft"
  | "zone_1_ring_5_30ft"
  | "zone_2_ring_30_100ft"
  | "cv_detection";

export type LngLat = [number, number];

export interface Polygon {
  type: "Polygon";
  coordinates: LngLat[][];
}

export interface FeatureProperties {
  kind: FeatureKind;
  label: string | null;
}

export interface Feature {
  type: "Feature";
  geometry: Polygon;
  properties: FeatureProperties;
}

export interface FeatureCollection {
  type: "FeatureCollection";
  features: Feature[];
}

export interface ParcelIdentity {
  apn_uid: string; // 14-digit APN
  address: string;
  county_fips: string;
  state: State;
  h3_res11: string;
  h3_res13: string;
  rcv_usd: number;
  year_built: number;
  centroid: LngLat;
  geometries: FeatureCollection;
}

export interface PublicHazardLayer {
  fema_flood_zone: string;
  bfe_ft_navd88: number | null;
  usgs_lag_ft: number | null;
  est_ffe_ft: number | null;
  freeboard_delta_h_ft: number | null; // null when BFE or elevation is unavailable
  hand_rel_elev_ft: number;
  twi_index: number;
  noaa_atlas15_p24h_100yr_in: number;
  atlas15_cmip6_mult: number;
  landfire_fbfm40_code: string;
  slope_deg: number;
  wui_class: string;
  openfema_tract_claim_count: number;
  openfema_tract_mean_lcr: number;
  wrc_burn_probability: number | null;
}

export interface PrivateVerificationLayer {
  cv_roof_class: RoofClass;
  cv_confidence: number; // 0..1
  cv_overhang_ft: number;
  cv_zone0_clear: boolean;
  cv_zone1_no_shed: boolean;
  cv_enclosed_eaves: boolean;
  cv_ember_vents: boolean;
  elev_cert_verified: boolean;
  ibhs_fortified_tier: FortifiedTier;
  ibhs_wph_tier: WphTier;
  iot_shutoff_active: boolean;
  unpermitted_footprint_delta_sqft: number;
}

export interface PerilSplit {
  peril: Peril;
  zip_immunity_pi: number;
  expected_freq_n: number;
  expected_sev_s: number;
  peril_aal_usd: number;
}

export interface ActuarialBreakdown {
  tract_prior_lcr: number;
  parcel_raw_lcr: number;
  credibility_weight_z: number; // 0..1
  posterior_lcr: number;
  expected_annual_loss_usd: number;
  peril_split: PerilSplit[];
  resili_score: number; // 300..850
  baseline_macro_score: number; // 300..850
  underwriting_tier: UnderwritingTier;
  statutory_discount_pct: number;
  annual_base_premium_usd: number;
  annual_discounted_premium_usd: number;
}

export interface Mitigation {
  action_id: string;
  title: string;
  peril: string;
  statutory_authority: string;
  gross_capex_usd: number;
  grant_subsidy_usd: number;
  net_capex_usd: number;
  lcr_delta_bps: number;
  score_delta_pts: number;
  annual_premium_savings_usd: number;
  payback_years: number;
  resale_value_bump_pct: number;
  currently_applied: boolean;
}

export interface HitlStatus {
  escalated: boolean;
  trigger_code: TriggerCode;
  trigger_reason: string | null;
  recommended_underwriter_action: string | null;
}

export interface Ca26449Factors {
  cat_a_fire_risk_reduction_community: boolean;
  cat_a_firewise_usa: boolean;
  cat_a_shelter_in_place: boolean;
  cat_b1_under_deck_clearing: boolean;
  cat_b1_zone0_clear_0_5ft: boolean;
  cat_b1_no_sheds_within_30ft: boolean;
  cat_b1_prc_4291_compliance: boolean;
  cat_b2_class_a_roof: boolean;
  cat_b2_enclosed_eaves: boolean;
  cat_b2_ember_vents: boolean;
  cat_b2_multi_pane_windows: boolean;
  cat_b2_vertical_siding_clearance_6in: boolean;
}

export interface RegulatoryCompliance {
  monotonicity_verified: boolean;
  ny_dfs_cl7_ecdis_free: boolean;
  ca_2644_9_factors: Ca26449Factors;
  dataset_vintages: Record<string, string>;
}

export type BasementType = "NONE" | "FULL" | "PARTIAL" | "UNKNOWN";
export type DepScenario = "LIMITED_CURRENT" | "MODERATE_CURRENT" | "MODERATE_2050" | "EXTREME_2080";
export type DepFloodClass = "NONE" | "NUISANCE" | "DEEP_CONTIGUOUS" | "UNAVAILABLE";

export interface DepStormwater {
  scenario: DepScenario;
  flood_class: DepFloodClass;
}

// Contract v3: NYC-specific evidence. Null or absent outside the five boroughs.
export interface NycLayer {
  bbl: string;
  bin: string | null;
  borough: string;
  bldg_class: string | null;
  year_built: number | null;
  num_floors: number | null;
  basement_code: string | null;
  basement_type: BasementType;
  ground_elevation_ft: number | null;
  roof_height_ft: number | null;
  dep_stormwater: DepStormwater[];
  floodnet_events_500m_5y: number | null;
  floodnet_max_depth_in: number | null;
  sewer_backup_311_500m_5y: number | null;
  street_flooding_311_500m_5y: number | null;
  catch_basins_150m: number | null;
  dob_open_violations: number | null;
  dob_cellar_conversion_flag: boolean | null;
  sandy_inundated: boolean | null;
  evacuation_zone: string | null;
}

export type ValueSource ="LIVE" | "DEFAULT" | "UNAVAILABLE" | "REFERENCE_PARCEL";

export interface InputProvenance {
  field: string;
  value_source: ValueSource;
  source_name: string;
  vintage: string | null;
}

export interface FactorContribution {
  factor: string;
  input_value: number | string | boolean | null;
  score_points: number;
  source: string;
}

export interface Uncertainty {
  aal_p05_usd: number;
  aal_p50_usd: number;
  aal_p95_usd: number;
  score_p05: number;
  score_p95: number;
  loss_1_in_100_usd: number;
  loss_1_in_250_usd: number;
  method: string;
}

export interface PremiumBuild {
  expected_loss_usd: number;
  deductible_usd: number;
  net_expected_loss_usd: number;
  expense_load_pct: number;
  profit_load_pct: number;
  indicated_premium_usd: number;
  modeled_mitigation_credit_pct: number;
  filed_mitigation_credit_pct: number;
}

export interface EvidenceLogEntry {
  evidence_id: string;
  channel: string;
  submitted_at: string; // ISO 8601 date-time
  weight_added: number;
  z_before: number;
  z_after: number;
  score_before: number;
  score_after: number;
}

export interface ParcelScoreResponse {
  request_id: string; // UUID
  processing_time_ms: number;
  parcel_identity: ParcelIdentity;
  public_hazard_layer: PublicHazardLayer;
  private_verification_layer: PrivateVerificationLayer;
  actuarial_breakdown: ActuarialBreakdown;
  prescriptive_mitigations: Mitigation[];
  hitl_status: HitlStatus;
  regulatory_compliance: RegulatoryCompliance;
  // Contract v2: optional, additive. Absent or null on responses that predate v2.
  input_provenance?: InputProvenance[];
  factor_contributions?: FactorContribution[];
  uncertainty?: Uncertainty | null;
  premium_build?: PremiumBuild | null;
  evidence_log?: EvidenceLogEntry[];
  indicative_only?: boolean;
  // Contract v3: optional, additive.
  nyc?: NycLayer | null;
}

export type GoldenScenarioKey =
  | "SCENARIO_1_LA_FLOOD"
  | "SCENARIO_2_CA_WUI"
  | "SCENARIO_3_ESCONDIDO_HITL"
  | "SCENARIO_3_ESCONDIDO_HITL__UNPERMITTED";

export type GoldenScenarios = Record<GoldenScenarioKey, ParcelScoreResponse>;
