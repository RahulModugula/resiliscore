"""Pydantic v2 models mirroring contracts/parcel_score_schema.json. Change both together."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

UUID_PATTERN = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"

State = Literal["LA", "CA", "FL"]
Peril = Literal["FLOOD", "WILDFIRE", "WIND_HAIL"]
RoofClass = Literal["CLASS_A_FORTIFIED", "CLASS_A_IMPACT_4", "CLASS_A_ASPHALT", "WOOD_SHAKE_UNRATED"]
FortifiedTier = Literal["ROOF", "SILVER", "GOLD", "NONE"]
WphTier = Literal["BASE", "PLUS", "NONE"]
UnderwritingTier = Literal["TIER_1_AUTO_BIND", "TIER_2_CONDITIONAL", "TIER_3_DECLINE_ESCALATE"]
TriggerCode = Literal[
    "NONE",
    "HITL_TRIGGER_01_SENSOR_DIVERGENCE",
    "HITL_TRIGGER_02_UNPERMITTED_ADDITION",
    "HITL_TRIGGER_03_HIGH_TIV",
    "HITL_TRIGGER_04_BOUNDARY_CONFLICT",
]
FeatureKind = Literal[
    "parcel_polygon",
    "building_footprint",
    "zone_0_ring_0_5ft",
    "zone_1_ring_5_30ft",
    "zone_2_ring_30_100ft",
    "cv_detection",
]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Polygon(_Strict):
    type: Literal["Polygon"]
    coordinates: list[Annotated[list[tuple[float, float]], Field(min_length=4)]] = Field(min_length=1)


class FeatureProperties(_Strict):
    kind: FeatureKind
    label: str | None


class Feature(_Strict):
    type: Literal["Feature"]
    geometry: Polygon
    properties: FeatureProperties


class FeatureCollection(_Strict):
    type: Literal["FeatureCollection"]
    features: list[Feature]


class ParcelIdentity(_Strict):
    apn_uid: str = Field(pattern=r"^[0-9]{14}$")
    address: str
    county_fips: str
    state: State
    h3_res11: str
    h3_res13: str
    rcv_usd: float
    year_built: int
    centroid: tuple[float, float]  # [lng, lat]
    geometries: FeatureCollection


class PublicHazardLayer(_Strict):
    fema_flood_zone: str
    bfe_ft_navd88: float | None
    usgs_lag_ft: float
    est_ffe_ft: float
    freeboard_delta_h_ft: float
    hand_rel_elev_ft: float
    twi_index: float
    noaa_atlas15_p24h_100yr_in: float
    atlas15_cmip6_mult: float
    landfire_fbfm40_code: str
    slope_deg: float
    wui_class: str
    openfema_tract_claim_count: int
    openfema_tract_mean_lcr: float


class PrivateVerificationLayer(_Strict):
    cv_roof_class: RoofClass
    cv_confidence: float = Field(ge=0, le=1)
    cv_overhang_ft: float
    cv_zone0_clear: bool
    cv_zone1_no_shed: bool
    cv_enclosed_eaves: bool
    cv_ember_vents: bool
    elev_cert_verified: bool
    ibhs_fortified_tier: FortifiedTier
    ibhs_wph_tier: WphTier
    iot_shutoff_active: bool
    unpermitted_footprint_delta_sqft: float


class PerilSplit(_Strict):
    peril: Peril
    zip_immunity_pi: float
    expected_freq_n: float
    expected_sev_s: float
    peril_aal_usd: float


class ActuarialBreakdown(_Strict):
    tract_prior_lcr: float
    parcel_raw_lcr: float
    credibility_weight_z: float = Field(ge=0, le=1)
    posterior_lcr: float
    expected_annual_loss_usd: float
    peril_split: list[PerilSplit]
    resili_score: int = Field(ge=300, le=850)
    baseline_macro_score: int = Field(ge=300, le=850)
    underwriting_tier: UnderwritingTier
    statutory_discount_pct: float
    annual_base_premium_usd: float
    annual_discounted_premium_usd: float


class Mitigation(_Strict):
    action_id: str
    title: str
    peril: str
    statutory_authority: str
    gross_capex_usd: float
    grant_subsidy_usd: float
    net_capex_usd: float
    lcr_delta_bps: float
    score_delta_pts: int
    annual_premium_savings_usd: float
    payback_years: float
    resale_value_bump_pct: float
    currently_applied: bool


class HitlStatus(_Strict):
    escalated: bool
    trigger_code: TriggerCode
    trigger_reason: str | None
    recommended_underwriter_action: str | None


class Ca26449Factors(_Strict):
    """The 12 10 CCR 2644.9 wildfire factors: Cat A (community), B1 (surroundings), B2 (structure)."""

    cat_a_fire_risk_reduction_community: bool
    cat_a_firewise_usa: bool
    cat_a_shelter_in_place: bool
    cat_b1_under_deck_clearing: bool
    cat_b1_zone0_clear_0_5ft: bool
    cat_b1_no_sheds_within_30ft: bool
    cat_b1_prc_4291_compliance: bool
    cat_b2_class_a_roof: bool
    cat_b2_enclosed_eaves: bool
    cat_b2_ember_vents: bool
    cat_b2_multi_pane_windows: bool
    cat_b2_vertical_siding_clearance_6in: bool


class RegulatoryCompliance(_Strict):
    monotonicity_verified: bool
    ny_dfs_cl7_ecdis_free: bool
    ca_2644_9_factors: Ca26449Factors
    dataset_vintages: dict[str, str]


ValueSource = Literal["LIVE", "DEFAULT", "UNAVAILABLE", "REFERENCE_PARCEL"]


class InputProvenance(_Strict):
    field: str
    value_source: ValueSource
    source_name: str
    vintage: str | None


class FactorContribution(_Strict):
    factor: str
    input_value: float | str | bool | None
    score_points: float
    source: str


class Uncertainty(_Strict):
    aal_p05_usd: float
    aal_p50_usd: float
    aal_p95_usd: float
    score_p05: float
    score_p95: float
    loss_1_in_100_usd: float
    loss_1_in_250_usd: float
    method: str


class PremiumBuild(_Strict):
    expected_loss_usd: float
    deductible_usd: float
    net_expected_loss_usd: float
    expense_load_pct: float
    profit_load_pct: float
    indicated_premium_usd: float
    modeled_mitigation_credit_pct: float
    filed_mitigation_credit_pct: float


class EvidenceLogEntry(_Strict):
    evidence_id: str
    channel: str
    submitted_at: datetime
    weight_added: float
    z_before: float
    z_after: float
    score_before: int
    score_after: int


class ParcelScoreResponse(_Strict):
    request_id: str = Field(pattern=UUID_PATTERN)
    processing_time_ms: float
    parcel_identity: ParcelIdentity
    public_hazard_layer: PublicHazardLayer
    private_verification_layer: PrivateVerificationLayer
    actuarial_breakdown: ActuarialBreakdown
    prescriptive_mitigations: list[Mitigation]
    hitl_status: HitlStatus
    regulatory_compliance: RegulatoryCompliance
    # Contract v2: optional, additive.
    input_provenance: list[InputProvenance] = Field(default_factory=list)
    factor_contributions: list[FactorContribution] = Field(default_factory=list)
    uncertainty: Uncertainty | None = None
    premium_build: PremiumBuild | None = None
    evidence_log: list[EvidenceLogEntry] = Field(default_factory=list)
    indicative_only: bool = False
