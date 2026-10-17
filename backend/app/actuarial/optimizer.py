"""Counterfactual mitigation engine (spec Prompt 1C item 3).

`simulate(response, action_ids)` applies the selected actions to the verification layer, then reruns the
whole chain (compound model -> credibility -> score map -> premium credits -> HITL) in memory.
Actions are additive: an action already reflected in the response stays applied. A selected action is
assumed verified (CV upload or registry certificate), so it also adds its credibility channel weight.
"""

import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace

from app.actuarial import attribution, compliance, insurance, uncertainty
from app.actuarial import compound_model as cm
from app.actuarial.base_rates import NriRates, base_rates_for, context_for, resolve
from app.actuarial.constants import get as c
from app.actuarial.credibility import Credibility, credibility, posterior_lcr
from app.actuarial.score_map import score, tier
from app.models.schemas import (
    ActuarialBreakdown,
    InputProvenance,
    Mitigation,
    ParcelScoreResponse,
    PrivateVerificationLayer,
    RegulatoryCompliance,
    Uncertainty,
)

LA_AL_FORTIFIED_GRANT_USD = c("credit.grant_usd")
WILDFIRE_DISCOUNT_CAP = c("credit.wildfire_cap")
WIND_DISCOUNT_CAP = c("credit.wind_cap")
NO_PAYBACK_YEARS = 99.0  # reported when an action earns no premium credit
BPS = 1e4

# Statutory credit schedules (share of the peril's premium); see the registry for sources and caveats.
# Wildfire credits stack to the cap; WPH Plus earns the cap outright. Wind credits are not additive: the
# best roof credit applies. Louisiana FORTIFIED discounts are the South-region values, reused for Alabama.
WILDFIRE_CREDITS = c("credit.wildfire")
WPH_BASE_BONUS = c("credit.wph_base_bonus")
_LA_REGION = "South"
WIND_CREDITS = {
    "impact_class4": c("credit.class4"),
    **{tier: c("credit.la_fortified")[tier][_LA_REGION] for tier in ("ROOF", "SILVER", "GOLD")},
}


@dataclass(frozen=True)
class Evaluation:
    raw_lcr: float
    credibility: Credibility
    posterior_lcr: float
    score: int
    tier: str
    terms: list[cm.PerilTerm]


def _firewise(r: ParcelScoreResponse) -> bool:
    return r.regulatory_compliance.ca_2644_9_factors.cat_a_firewise_usa


def _ctx(r: ParcelScoreResponse, nri: NriRates | None = None) -> dict:
    return {"state": r.parcel_identity.state, "year_built": r.parcel_identity.year_built,
            "firewise": _firewise(r), "base_rates": context_for(r, nri)[0]}


def evaluate(
    r: ParcelScoreResponse, v: PrivateVerificationLayer, *, z: float | None = None, nri: NriRates | None = None
) -> Evaluation:
    """Full chain for response `r`'s parcel under verification state `v`.

    `z` pins the credibility weight (default: the weight `v`'s evidence earns), so a caller can isolate the
    physical effect of a change from the evidence it would add."""
    terms = cm.peril_terms(r.public_hazard_layer, v, **_ctx(r, nri))
    raw = sum(t.n * t.s for t in terms)
    cred = credibility(v)
    if z is not None:
        cred = replace(cred, z=z)
    post = posterior_lcr(raw, context_for(r, nri)[1], cred.z)
    s = score(post)
    return Evaluation(raw, cred, post, s, tier(s), terms)


def premium_discount(r: ParcelScoreResponse, v: PrivateVerificationLayer, nri: NriRates | None = None) -> float:
    """Blended statutory discount on the homeowners premium (flood is NFIP, so it is excluded).

    Peril shares come from the mitigation-free AAL split so the base premium stays fixed as actions toggle.
    """
    bare = {
        t.peril: t.n * t.s
        for t in cm.peril_terms(r.public_hazard_layer, v, **_ctx(r, nri), mitigations=cm.Mitigations())
        if t.peril != "FLOOD"
    }
    total = sum(bare.values())
    if total <= 0:
        return 0.0
    m = cm.mitigations_from(v)
    wildfire = 1.0 if v.ibhs_wph_tier == "PLUS" else sum(c * getattr(m, k) for k, c in WILDFIRE_CREDITS.items())
    wildfire = min(WILDFIRE_DISCOUNT_CAP, wildfire + (WPH_BASE_BONUS if v.ibhs_wph_tier == "BASE" else 0.0))
    wind = max(
        [WIND_CREDITS["impact_class4"] * m.roof_impact_class4]
        + ([WIND_CREDITS[v.ibhs_fortified_tier]] if v.ibhs_fortified_tier in WIND_CREDITS else [])
        + [WIND_CREDITS["ROOF"] * (v.cv_roof_class == "CLASS_A_FORTIFIED")]
    )
    credit = {"WILDFIRE": wildfire, "WIND_HAIL": min(WIND_DISCOUNT_CAP, wind)}
    return sum(bare[p] / total * credit[p] for p in bare)


@dataclass(frozen=True)
class Action:
    action_id: str
    alias: str
    title: str
    peril: str
    authority: str
    gross_capex_usd: float
    resale_bump_pct: float
    applicable: Callable[[ParcelScoreResponse, PrivateVerificationLayer], bool]
    applied: Callable[[PrivateVerificationLayer], bool]
    apply: Callable[[PrivateVerificationLayer], dict]
    strip: Callable[[PrivateVerificationLayer], dict]
    grant_states: tuple[str, ...] = ()

    def with_(self, v: PrivateVerificationLayer) -> PrivateVerificationLayer:
        return v.model_copy(update=self.apply(v))

    def without(self, v: PrivateVerificationLayer) -> PrivateVerificationLayer:
        return v.model_copy(update=self.strip(v))


def _ca_wui(r: ParcelScoreResponse, _v: PrivateVerificationLayer) -> bool:
    return r.parcel_identity.state == "CA" and r.public_hazard_layer.wui_class != "NON_WUI"


def _FORTIFIED_ROOF(v: PrivateVerificationLayer) -> bool:
    return v.cv_roof_class == "CLASS_A_FORTIFIED" or v.ibhs_fortified_tier != "NONE"

_E = c("action.economics")  # action id -> (gross capex USD, resale bump %)

ACTIONS: tuple[Action, ...] = (
    Action(
        "CA_ZONE0_1_CLEARANCE", "zone0_clear",
        "Zone 0/1 clearance: noncombustible 0-5 ft, prune canopy, relocate shed",
        "WILDFIRE", "10 CCR 2644.9 Cat B1; CA PRC 4291", *_E["CA_ZONE0_1_CLEARANCE"], _ca_wui,
        lambda v: v.cv_zone0_clear and v.cv_zone1_no_shed and v.cv_overhang_ft == 0,
        lambda v: {"cv_zone0_clear": True, "cv_zone1_no_shed": True, "cv_overhang_ft": 0.0},
        lambda v: {"cv_zone0_clear": False, "cv_zone1_no_shed": False},
    ),
    Action(
        "CA_EMBER_VENTS_EAVES", "ember_vents_eaves", "1/4-inch ember vents + enclosed eaves",
        "WILDFIRE", "10 CCR 2644.9 Cat B2; CBC Chapter 7A", *_E["CA_EMBER_VENTS_EAVES"], _ca_wui,
        lambda v: v.cv_ember_vents and v.cv_enclosed_eaves,
        lambda v: {"cv_ember_vents": True, "cv_enclosed_eaves": True},
        lambda v: {"cv_ember_vents": False, "cv_enclosed_eaves": False},
    ),
    Action(
        "CA_IBHS_WPH_CLASS_A_ROOF", "ibhs_wph_class_a_roof", "IBHS Wildfire Prepared Home Class A roof",
        "WILDFIRE", "10 CCR 2644.9 Cat B2; IBHS WPH", *_E["CA_IBHS_WPH_CLASS_A_ROOF"],
        lambda r, v: _ca_wui(r, v) and v.ibhs_wph_tier != "PLUS",
        lambda v: v.ibhs_wph_tier != "NONE" and v.cv_roof_class != "WOOD_SHAKE_UNRATED",
        lambda v: {
            "ibhs_wph_tier": v.ibhs_wph_tier if v.ibhs_wph_tier != "NONE" else "BASE",
            "cv_roof_class": "CLASS_A_ASPHALT" if v.cv_roof_class == "WOOD_SHAKE_UNRATED" else v.cv_roof_class,
        },
        lambda v: {"ibhs_wph_tier": "NONE", "cv_roof_class": "WOOD_SHAKE_UNRATED"},
    ),
    Action(
        "CA_IBHS_WPH_PLUS", "ibhs_wph_plus",
        "IBHS Wildfire Prepared Home Plus (30% wildfire peril discount)",
        "WILDFIRE", "10 CCR 2644.9 Cat B1+B2; IBHS WPH Plus", *_E["CA_IBHS_WPH_PLUS"], _ca_wui,
        lambda v: v.ibhs_wph_tier == "PLUS",
        lambda v: {
            "ibhs_wph_tier": "PLUS", "cv_zone0_clear": True, "cv_zone1_no_shed": True, "cv_overhang_ft": 0.0,
            "cv_ember_vents": True, "cv_enclosed_eaves": True,
            "cv_roof_class": "CLASS_A_ASPHALT" if v.cv_roof_class == "WOOD_SHAKE_UNRATED" else v.cv_roof_class,
        },
        lambda v: {"ibhs_wph_tier": "NONE"},
    ),
    Action(
        "LA_FORTIFIED_ROOF", "ibhs_fortified_roof", "IBHS FORTIFIED Roof (Louisiana Fortify Homes grant)",
        "WIND_HAIL", "LA R.S. 22:1460 FORTIFIED Roof credit", *_E["LA_FORTIFIED_ROOF"],
        lambda r, v: r.parcel_identity.state in ("LA", "AL"),
        _FORTIFIED_ROOF,
        lambda v: {
            "cv_roof_class": "CLASS_A_FORTIFIED",
            "ibhs_fortified_tier": v.ibhs_fortified_tier if v.ibhs_fortified_tier != "NONE" else "ROOF",
        },
        lambda v: {"cv_roof_class": "CLASS_A_ASPHALT", "ibhs_fortified_tier": "NONE"},
        grant_states=("LA", "AL"),
    ),
    Action(
        "HAIL_CLASS4_ROOF", "hail_class4_roof", "Class 4 impact-resistant roof (12.4% hail discount)",
        "WIND_HAIL", "IBHS FORTIFIED; UL 2218 Class 4", *_E["HAIL_CLASS4_ROOF"],
        lambda r, v: not _FORTIFIED_ROOF(v),
        lambda v: v.cv_roof_class == "CLASS_A_IMPACT_4",
        lambda v: {"cv_roof_class": "CLASS_A_IMPACT_4"},
        lambda v: {"cv_roof_class": "CLASS_A_ASPHALT"},
    ),
    Action(
        "SMART_WATER_SHUTOFF", "smart_water_shutoff", "Smart water shut-off valve with backflow protection",
        "FLOOD", "IBHS FORTIFIED Home water-intrusion guidance; carrier water-damage credit", *_E["SMART_WATER_SHUTOFF"],
        lambda r, v: "FLOOD" in cm.active_perils(r.public_hazard_layer),
        lambda v: v.iot_shutoff_active,
        lambda v: {"iot_shutoff_active": True},
        lambda v: {"iot_shutoff_active": False},
    ),
)
# Accepted ids: the canonical (golden) action ids and the spec's short ids. The API and MCP pass the
# golden ids; the S2 score of 630 comes from CA_ZONE0_1_CLEARANCE + CA_EMBER_VENTS_EAVES +
# CA_IBHS_WPH_CLASS_A_ROOF. The short id `ibhs_wph_plus` is a different, larger action (CA_IBHS_WPH_PLUS:
# WPH Plus certificate plus every wildfire flag), so swapping it in for the class-A-roof action gives 644.
_BY_KEY ={k: a for a in ACTIONS for k in (a.action_id, a.alias)}


def _select(v: PrivateVerificationLayer, action_ids: list[str]) -> PrivateVerificationLayer:
    for key in action_ids:
        if key not in _BY_KEY:
            raise ValueError(f"unknown mitigation action: {key}")
        v = _BY_KEY[key].with_(v)
    return v


def _mitigation_row(
    r: ParcelScoreResponse, a: Action, v: PrivateVerificationLayer, base_premium: float, nri: NriRates
) -> Mitigation:
    on, off = a.with_(v), a.without(v)
    # A row is the physical effect of the action alone: both sides use the as-found credibility weight.
    # Evidence (more channels, a higher Z) is a separate effect and shows in simulate()'s headline score.
    z = credibility(v).z
    e_on, e_off = evaluate(r, on, z=z, nri=nri), evaluate(r, off, z=z, nri=nri)
    savings = base_premium * (premium_discount(r, on, nri) - premium_discount(r, off, nri))
    grant = min(a.gross_capex_usd, LA_AL_FORTIFIED_GRANT_USD) if r.parcel_identity.state in a.grant_states else 0.0
    net = a.gross_capex_usd - grant
    return Mitigation(
        action_id=a.action_id, title=a.title, peril=a.peril, statutory_authority=a.authority,
        gross_capex_usd=a.gross_capex_usd, grant_subsidy_usd=grant, net_capex_usd=net,
        lcr_delta_bps=round((e_on.posterior_lcr - e_off.posterior_lcr) * BPS, 2),
        score_delta_pts=e_on.score - e_off.score,
        annual_premium_savings_usd=round(savings, 2),
        payback_years=round(net / savings, 2) if savings > 0 else NO_PAYBACK_YEARS,
        resale_value_bump_pct=a.resale_bump_pct,
        currently_applied=a.applied(v),
    )


def _factors(r: ParcelScoreResponse, v: PrivateVerificationLayer):
    """CA 2644.9 factors derivable from verification; others (community, windows, siding) carry over."""
    f = r.regulatory_compliance.ca_2644_9_factors
    if r.parcel_identity.state != "CA":
        return f
    clear = v.cv_zone0_clear and v.cv_zone1_no_shed and v.cv_overhang_ft == 0
    return f.model_copy(update={
        "cat_b1_zone0_clear_0_5ft": v.cv_zone0_clear,
        "cat_b1_no_sheds_within_30ft": v.cv_zone1_no_shed,
        "cat_b1_prc_4291_compliance": clear,
        "cat_b2_class_a_roof": v.cv_roof_class != "WOOD_SHAKE_UNRATED",
        "cat_b2_enclosed_eaves": v.cv_enclosed_eaves,
        "cat_b2_ember_vents": v.cv_ember_vents,
    })

STAND_IN_FIELD = "actuarial_breakdown.base_rates"


def _with_stand_in_row(rows: list[InputProvenance], tract: NriRates) -> list[InputProvenance]:
    """Say that the base rates and prior come from the nearest reference tract, not the parcel's own."""
    row = InputProvenance(
        field=STAND_IN_FIELD, value_source="REFERENCE_PARCEL", vintage=tract.version,
        source_name=f"FEMA NRI reference tract {tract.tractfips} used as a stand-in: no tract was supplied for this parcel",
    )
    return [x for x in rows if x.field != STAND_IN_FIELD] + [row]


def simulate(
    response: ParcelScoreResponse, action_ids: list[str], nri: NriRates | None = None
) -> ParcelScoreResponse:
    """Re-score `response` with `action_ids` applied (canonical ids or spec aliases).

    `nri` is the parcel's own NRI tract (from the ingestion client). With none, the nearest reference tract is a
    stand-in unless the parcel is that reference parcel, and the result is `indicative_only` with a provenance row
    saying so. The tract is resolved once here; nothing is read from any other request.
    """
    t0 = time.perf_counter()
    r = response
    tract, stand_in = resolve(r, nri)
    v = _select(r.private_verification_layer, action_ids)
    ev = evaluate(r, v, nri=tract)
    prior = tract.tract_prior_lcr
    base_premium = r.actuarial_breakdown.annual_base_premium_usd
    discount = premium_discount(r, v, tract)
    jac = compliance.numerical_jacobian(
        r.public_hazard_layer, v, **_ctx(r, tract), tract_prior_lcr=prior, z=ev.credibility.z
    )
    rows = [_mitigation_row(r, a, v, base_premium, tract) for a in ACTIONS if a.applicable(r, v)]
    scale = ev.posterior_lcr / ev.raw_lcr if ev.raw_lcr > 0 else 1.0
    rcv = r.parcel_identity.rcv_usd
    freeboard_missing = r.public_hazard_layer.freeboard_delta_h_ft is None and "FLOOD" in {t.peril for t in ev.terms}
    mc = uncertainty.simulate_losses(
        ev.terms, state=r.parcel_identity.state, rcv_usd=rcv, tract_prior_lcr=prior, z=ev.credibility.z,
        freeboard_known=not freeboard_missing,
    )
    build = insurance.premium_build(
        ev.terms,
        bare_terms=cm.peril_terms(r.public_hazard_layer, v, **_ctx(r, tract), mitigations=cm.Mitigations()),
        expected_loss_usd=ev.posterior_lcr * rcv, scale=scale, rcv_usd=rcv, filed_credit_pct=discount * 100,
    )
    breakdown = ActuarialBreakdown(
        tract_prior_lcr=prior,
        parcel_raw_lcr=round(ev.raw_lcr, 6),
        credibility_weight_z=round(ev.credibility.z, 4),
        posterior_lcr=round(ev.posterior_lcr, 6),
        expected_annual_loss_usd=round(ev.posterior_lcr * r.parcel_identity.rcv_usd, 2),
        peril_split=cm.peril_split(
            r.public_hazard_layer,
            v,
            r.parcel_identity.rcv_usd,
            scale=ev.posterior_lcr / ev.raw_lcr if ev.raw_lcr > 0 else 1.0,
            **_ctx(r, tract),
        ),
        resili_score=ev.score,
        baseline_macro_score=score(prior),
        underwriting_tier=ev.tier,
        statutory_discount_pct=round(discount * 100, 2),
        annual_base_premium_usd=base_premium,
        annual_discounted_premium_usd=round(base_premium * (1 - discount), 2),
    )
    out = r.model_copy(update={
        "private_verification_layer": v,
        "actuarial_breakdown": breakdown,
        "prescriptive_mitigations": rows,
        "uncertainty": Uncertainty(**asdict(mc)),
        "indicative_only": r.indicative_only or freeboard_missing or stand_in,
        "input_provenance": _with_stand_in_row(r.input_provenance, tract) if stand_in else r.input_provenance,
        "premium_build": build,
        "factor_contributions": attribution.contributions(r, v, base_rates=base_rates_for(tract), prior=prior),
        "hitl_status": compliance.hitl_status(
            rcv_usd=r.parcel_identity.rcv_usd,
            cv_confidence=v.cv_confidence,
            unpermitted_footprint_delta_sqft=v.unpermitted_footprint_delta_sqft,
            resili_score=ev.score,
        ),
        "regulatory_compliance": RegulatoryCompliance(
            monotonicity_verified=compliance.monotonicity_verified(jac),
            ny_dfs_cl7_ecdis_free=not compliance.ecdis_fields_present(),
            ca_2644_9_factors=_factors(r, v),
            dataset_vintages=r.regulatory_compliance.dataset_vintages,
        ),
        "processing_time_ms": round((time.perf_counter() - t0) * 1000, 2),
    })
    return out


__all__ = ["ACTIONS", "Evaluation", "evaluate", "premium_discount", "simulate"]
