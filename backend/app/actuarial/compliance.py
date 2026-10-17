"""Regulatory guards (spec section 3.4, Prompt 1C item 4): monotonicity proof, ECDIS scan, HITL triggers."""

import types
import typing
from dataclasses import replace

from pydantic import BaseModel

from app.actuarial import compound_model as cm
from app.actuarial import nyc
from app.actuarial.base_rates import BaseRates
from app.actuarial.credibility import posterior_lcr
from app.actuarial.score_map import score_continuous
from app.models.schemas import (
    DepStormwater,
    HitlStatus,
    NycLayer,
    ParcelScoreResponse,
    PrivateVerificationLayer,
    PublicHazardLayer,
)

JACOBIAN_STEP = 1e-3
LIDAR_CERT_LIMIT_FT = 1.5
CV_CONFIDENCE_FLOOR = 0.85
UNPERMITTED_LIMIT_SQFT = 150.0
HIGH_TIV_USD = 5_000_000.0
BOUNDARY_SCORE = (570, 590)

# NY DFS CL7 / 11 NYCRR 90.2: socio-economic and behavioural proxies that must never be a field.
ECDIS_TOKENS = frozenset(
    {"credit", "income", "occupation", "education", "race", "ethnicity", "religion", "gender", "marital",
     "employment", "shopping", "purchase", "homeownership", "citizenship", "language"}
)


def numerical_jacobian(
    hazard: PublicHazardLayer,
    verification: PrivateVerificationLayer,
    *,
    state: str,
    year_built: int,
    firewise: bool,
    tract_prior_lcr: float,
    z: float,
    base: cm.Mitigations | None = None,
    base_rates: BaseRates | None = None,
    nyc_layer: NycLayer | None = None,
    nyc_installed: frozenset[str] = frozenset(),
) -> dict[str, float]:
    """Central-difference d(score)/d(m_k) for every mitigation dose, holding Z and the prior fixed.

    Each dose is probed at 0.5 with the other doses at `base` (default: as observed), so saturated flags
    are still differentiable (spec 3.4 chain rule).
    """
    base = base if base is not None else cm.mitigations_from(verification)
    if nyc_installed:
        base = replace(base, **dict.fromkeys([k for k in nyc_installed if k in cm.NYC_DOSE_NAMES], 1.0))

    def score_at(m: cm.Mitigations) -> float:
        raw = cm.parcel_raw_lcr(
            hazard, verification, state=state, year_built=year_built, firewise=firewise, mitigations=m,
            base_rates=base_rates, nyc_layer=nyc_layer,
        )
        return score_continuous(posterior_lcr(raw, tract_prior_lcr, z))

    jac = {}
    for name in cm.MITIGATION_NAMES:
        up = replace(base, **{name: 0.5 + JACOBIAN_STEP})
        down = replace(base, **{name: 0.5 - JACOBIAN_STEP})
        jac[name] = (score_at(up) - score_at(down)) / (2 * JACOBIAN_STEP)
    return jac


def reference_jacobian() -> dict[str, float]:
    """Strict proof on a reference parcel where every peril is live, so no dose is a structural zero."""
    hazard = PublicHazardLayer(
        fema_flood_zone="AE", bfe_ft_navd88=9.0, usgs_lag_ft=7.0, est_ffe_ft=13.0, freeboard_delta_h_ft=4.0,
        hand_rel_elev_ft=5.0, twi_index=8.0, noaa_atlas15_p24h_100yr_in=10.0, atlas15_cmip6_mult=1.1,
        landfire_fbfm40_code="SH7", slope_deg=15.0, wui_class="INTERMIX", openfema_tract_claim_count=100,
        openfema_tract_mean_lcr=0.01,
    )
    verification = PrivateVerificationLayer(
        cv_roof_class="WOOD_SHAKE_UNRATED", cv_confidence=0.9, cv_overhang_ft=10.0, cv_zone0_clear=False,
        cv_zone1_no_shed=False, cv_enclosed_eaves=False, cv_ember_vents=False, elev_cert_verified=False,
        ibhs_fortified_tier="NONE", ibhs_wph_tier="NONE", iot_shutoff_active=False,
        unpermitted_footprint_delta_sqft=0.0,
    )
    return numerical_jacobian(
        hazard, verification, state="LA", year_built=1990, firewise=False, tract_prior_lcr=0.02, z=0.6,
        # any positive rates: the proof is level-free
        base_rates=BaseRates(flood=0.001, wildfire=0.004, wind=0.001, pluvial=0.002, sewer=0.001),
        nyc_layer=nyc.blank_layer(
            basement_type="FULL",
            dep_stormwater=[
                DepStormwater(scenario="LIMITED_CURRENT", flood_class="NUISANCE"),
                DepStormwater(scenario="MODERATE_CURRENT", flood_class="NUISANCE"),
                DepStormwater(scenario="EXTREME_2080", flood_class="DEEP_CONTIGUOUS"),
            ],
            floodnet_events_500m_5y=5, sewer_backup_311_500m_5y=60, catch_basins_150m=5, residential_units_500m=3000,
            dob_cellar_conversion_flag=True, sandy_inundated=True,
        ),
    )


def monotonicity_verified(parcel_jacobian: dict[str, float]) -> bool:
    """True when every dose is strictly score-improving on the reference parcel and never harmful here."""
    return all(g > 0 for g in reference_jacobian().values()) and all(g >= -1e-9 for g in parcel_jacobian.values())


def _field_names(model: type[BaseModel], seen: set[type]) -> list[str]:
    names = []
    for name, info in model.model_fields.items():
        names.append(name)
        stack = [info.annotation]
        while stack:
            ann = stack.pop()
            if isinstance(ann, type) and issubclass(ann, BaseModel) and ann not in seen:
                seen.add(ann)
                names.extend(_field_names(ann, seen))
            elif typing.get_origin(ann) in (list, tuple, dict, typing.Union, types.UnionType):
                stack.extend(typing.get_args(ann))
    return names


# Mitigation credits are filed rating-plan discounts, not consumer credit data.
ECDIS_ALLOWED_FIELDS = frozenset({"modeled_mitigation_credit_pct", "filed_mitigation_credit_pct"})


def ecdis_fields_present(model: type[BaseModel] = ParcelScoreResponse) -> list[str]:
    """Field names (any depth) containing a socio-economic ECDIS token; empty means CL7-clean."""
    names = _field_names(model, set())
    return sorted({n for n in names if n not in ECDIS_ALLOWED_FIELDS and ECDIS_TOKENS & set(n.lower().split("_"))})


def hitl_status(
    *,
    rcv_usd: float,
    cv_confidence: float,
    unpermitted_footprint_delta_sqft: float,
    resili_score: int,
    delta_z_lidar_ft: float | None = None,
    delta_z_cert_ft: float | None = None,
) -> HitlStatus:
    """First matching trigger of the four in spec Prompt 1C item 4. The elevation-certificate elevation
    is not part of the contract, so the divergence leg runs only when the caller supplies both values."""
    if delta_z_lidar_ft is not None and delta_z_cert_ft is not None:
        gap = abs(delta_z_lidar_ft - delta_z_cert_ft)
        if gap > LIDAR_CERT_LIMIT_FT:
            return _escalate(
                "HITL_TRIGGER_01_SENSOR_DIVERGENCE",
                f"LiDAR and elevation-certificate elevations differ by {gap:.1f} ft (limit {LIDAR_CERT_LIMIT_FT} ft).",
                "Request a fresh elevation certificate or field survey before pricing flood.",
            )
    if cv_confidence < CV_CONFIDENCE_FLOOR:
        return _escalate(
            "HITL_TRIGGER_01_SENSOR_DIVERGENCE",
            f"Aerial CV confidence {cv_confidence:.2f} is below {CV_CONFIDENCE_FLOOR}.",
            "Request a fresh flyover or mobile photo verification before applying credits.",
        )
    if unpermitted_footprint_delta_sqft > UNPERMITTED_LIMIT_SQFT:
        return _escalate(
            "HITL_TRIGGER_02_UNPERMITTED_ADDITION",
            f"CV detected a +{unpermitted_footprint_delta_sqft:.0f} sq ft unpermitted structure in Zone 1 "
            "(5-30 ft) versus the permitted footprint.",
            "Hold auto-bind; request permit history or mobile-QR photo verification before applying "
            "wildfire credits.",
        )
    if rcv_usd > HIGH_TIV_USD:
        return _escalate(
            "HITL_TRIGGER_03_HIGH_TIV",
            f"Replacement cost ${rcv_usd:,.0f} exceeds the ${HIGH_TIV_USD:,.0f} straight-through limit.",
            "Route to a senior underwriter for a facultative or manual quote.",
        )
    if BOUNDARY_SCORE[0] <= resili_score <= BOUNDARY_SCORE[1]:
        return _escalate(
            "HITL_TRIGGER_04_BOUNDARY_CONFLICT",
            f"ResiliScore {resili_score} sits on the Tier 2 / Tier 3 boundary "
            f"({BOUNDARY_SCORE[0]}-{BOUNDARY_SCORE[1]}).",
            "Underwriter to review the verification evidence before binding or declining.",
        )
    return HitlStatus(
        escalated=False, trigger_code="NONE", trigger_reason=None, recommended_underwriter_action=None
    )


def _escalate(code: str, reason: str, action: str) -> HitlStatus:
    return HitlStatus(
        escalated=True, trigger_code=code, trigger_reason=reason, recommended_underwriter_action=action
    )
