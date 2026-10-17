"""Two-part compound frequency-severity engine (spec section 3.1, Prompt 1C item 1).

AAL_p / RCV = E[N_p] * E[S_p | N_p > 0], with E[N] = (1 - pi) * lambda from a zero-inflated Poisson GLM
and a spliced severity: depth-damage (flood) or constant (fire, wind) body for s <= u = 0.5, truncated
GPD tail on [u, 1]. Every mitigation m_k in [0, 1] enters only through attenuating terms
(immunity logit up, body down, GPD scale down, tail probability down), which is what makes
d(score)/d(m_k) > 0 (section 3.4).

Parameters. Every coefficient is read from constants.py, which records its source and whether it is
validated. v2 replaced invented severity and mitigation values with cited ones: the flood body is the Hazus
USACE-IWR RES1 depth-damage table, wildfire immunity per feature comes from the IBHS LA conflagration study,
and the FORTIFIED roof effect reproduces the Hurricane Sally frequency and severity cuts. The intercepts
the frequency intercepts are no longer fitted to any demo score: each peril's intercept is solved in closed form
so a reference home matches the FEMA NRI building loss rate for its tract (base_rates.py, D3).

Notes.
* Flood ln(lambda) uses +beta_2 * TWI (section 3.1). Prompt 1C prints -beta_2 * TWI, which would lower
  flood frequency on wetter terrain.
* Freeboard acts by shifting first-floor height through the depth-damage curve (depth = stage - freeboard).
* The spec gives no GLM for wind/hail; the structure below mirrors the wildfire one.
"""

import math
from dataclasses import dataclass, fields
from statistics import NormalDist

import numpy as np

from app.actuarial.base_rates import BaseRates, intercept_for
from app.actuarial.constants import get as c
from app.models.schemas import PerilSplit, PrivateVerificationLayer, PublicHazardLayer

U_TAIL = c("tail.splice_u")  # catastrophic splice threshold u_p
_PHI = NormalDist().cdf

# Every coefficient below is read from the registry (constants.py), which records its source and whether it
# is validated. Most are priors; see the registry notes before quoting any of them.

# --- Flood frequency ---
GAMMA0, GAMMA1, GAMMA2 = c("flood.zip.gamma")
BETA1, BETA2, BETA3, BETA4 = c("flood.freq.beta")
ELEVATED_BLDG_FT = c("flood.elevated_bldg_ft")  # I_elev_bldg: certified freeboard at or above this

# --- Wildfire frequency ---
ETA0 = c("wildfire.eta0")
DELTA1, DELTA2, DELTA3_CANOPY, DELTA4_FIREWISE = c("wildfire.freq")

# --- Wind/hail frequency ---
OMEGA0 = c("wind.omega0")
V1_REGION, V2_PRE_CODE = c("wind.v_region_precode")
PRE_CODE_YEAR = c("wind.pre_code_year")
STATE_WIND_INDEX = c("wind.state_index")
DEFAULT_WIND_INDEX = c("wind.state_index_default")

# --- Severity ---
DDF_MIN_FT, DDF_MAX_FT = c("flood.ddf.depth_clamp_ft")
_DDF_DEPTHS = np.arange(DDF_MIN_FT, DDF_MAX_FT + 1.0)
_DDF_FRACTION = np.array(c("flood.ddf.usace_iwr_res1_1s_nb"), dtype=float) / 100.0
FLOOD_STAGE0_FT, FLOOD_STAGE_PER_IN = c("flood.stage0_ft"), c("flood.stage_per_in")  # stage above BFE = a + b * D_100
BODY_WILDFIRE, BODY_WIND = c("wildfire.body"), c("wind.body")
# (alpha_0, alpha_dh, sigma_0, xi) per peril
TAIL = {
    "WILDFIRE": tuple(c("wildfire.tail")),
    "WIND_HAIL": tuple(c("wind.tail")),
}

# Fuel index (0-1) for Scott & Burgan codes: family default plus overrides.
FUEL_FAMILY = c("wildfire.fuel_family")
FUEL_OVERRIDES = c("wildfire.fuel_overrides")
FUEL_DEFAULT = c("wildfire.fuel_default")  # unrecognised code: mid-scale rather than silently zero


@dataclass(frozen=True)
class Mitigations:
    """Physical mitigation doses m_k in [0, 1]; observed flags map to 0 or 1."""

    zone0_clear: float = 0.0
    zone1_no_shed: float = 0.0
    canopy_trim: float = 0.0
    ember_vents: float = 0.0
    enclosed_eaves: float = 0.0
    roof_class_a: float = 0.0
    roof_impact_class4: float = 0.0
    roof_fortified: float = 0.0
    water_shutoff: float = 0.0


MITIGATION_NAMES = tuple(f.name for f in fields(Mitigations))


@dataclass(frozen=True)
class Effect:
    """Attenuation per unit dose: immunity logit lift, body log-drop, GPD log-scale drop, probit drop."""

    eta: float = 0.0
    psi: float = 0.0
    theta: float = 0.0
    alpha: float = 0.0


# peril -> mitigation -> effect. All fields >= 0 (spec 3.4). canopy_trim acts through lambda (DELTA3_CANOPY).
# Wildfire features carry only the IBHS-derived immunity lift (severity attenuation is not invented).
# Wind roof effects come from the registry.
EFFECTS: dict[str, dict[str, Effect]] = {
    "FLOOD": {"water_shutoff": Effect(*c("flood.effect.water_shutoff"))},
    "WILDFIRE": {
        name: Effect(*c("wildfire.effect.feature"))
        for name in ("zone0_clear", "zone1_no_shed", "ember_vents", "enclosed_eaves", "roof_class_a")
    },
    "WIND_HAIL": {
        "roof_impact_class4": Effect(*c("wind.effect.roof_impact_class4")),
        "roof_fortified": Effect(*c("wind.effect.roof_fortified")),
    },
}


@dataclass(frozen=True)
class PerilTerm:
    peril: str
    pi: float
    n: float  # E[N]
    s: float  # E[S | N > 0] as a fraction of RCV
    depth_ft: float | None = None  # flood only: event depth above the first floor
    sev: "SevParams | None" = None  # severity distribution behind s, used by the Monte Carlo and the deductible


def mitigations_from(v: PrivateVerificationLayer) -> Mitigations:
    """Observed verification flags -> doses. Overhang is a feature, so canopy_trim starts at 0."""
    return Mitigations(
        zone0_clear=float(v.cv_zone0_clear),
        zone1_no_shed=float(v.cv_zone1_no_shed),
        ember_vents=float(v.cv_ember_vents),
        enclosed_eaves=float(v.cv_enclosed_eaves),
        roof_class_a=float(v.cv_roof_class != "WOOD_SHAKE_UNRATED"),
        roof_impact_class4=float(v.cv_roof_class in ("CLASS_A_IMPACT_4", "CLASS_A_FORTIFIED")),
        roof_fortified=float(v.cv_roof_class == "CLASS_A_FORTIFIED" or v.ibhs_fortified_tier != "NONE"),
        water_shutoff=float(v.iot_shutoff_active),
    )


def fuel_index(code: str) -> float:
    if code in FUEL_OVERRIDES:
        return FUEL_OVERRIDES[code]
    return FUEL_FAMILY.get(code[:2], FUEL_DEFAULT)


def active_perils(hazard: PublicHazardLayer) -> list[str]:
    """Flood in FEMA special flood hazard areas (A/V zones), wildfire in the WUI, wind/hail everywhere."""
    perils = []
    if hazard.fema_flood_zone[:1] in ("A", "V"):
        perils.append("FLOOD")
    if hazard.wui_class != "NON_WUI":
        perils.append("WILDFIRE")
    perils.append("WIND_HAIL")
    return perils


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def _sum(peril: str, m: Mitigations, attr: str) -> float:
    return sum(getattr(e, attr) * getattr(m, name) for name, e in EFFECTS[peril].items())


def ddf(depth_ft: float) -> float:
    """Hazus RES1 one-story no-basement structure damage fraction (USACE-IWR, DmgFnId 129).

    depth_ft is flood stage minus first-floor elevation, so more freeboard means less damage. Piecewise
    linear between the published one-foot points, clamped to the table's -2..+16 ft support.
    """
    return float(np.interp(depth_ft, _DDF_DEPTHS, _DDF_FRACTION))


def tgpd_mean(sigma: float, xi: float, upper: float) -> float:
    """E[Y | 0 <= Y <= upper] for a GPD(xi != 0, sigma): (int S dy - upper * S(upper)) / G(upper)."""
    surv_upper = (1 + xi * upper / sigma) ** (-1 / xi)
    integral = sigma / (1 - xi) * (1 - (1 + xi * upper / sigma) ** (1 - 1 / xi))
    return (integral - upper * surv_upper) / (1 - surv_upper)


@dataclass(frozen=True)
class SevParams:
    """Spliced severity: partial-loss body (mean body_mean, capped at body_cap) with probability 1 - p_tail,
    GPD(sigma, xi) tail on [U_TAIL, 1] with probability p_tail."""

    body_mean: float
    p_tail: float
    sigma: float
    xi: float
    body_cap: float

    @property
    def tail_mean(self) -> float:
        return U_TAIL + tgpd_mean(self.sigma, self.xi, 1 - U_TAIL) if self.p_tail > 0 else 0.0

    @property
    def mean(self) -> float:
        return (1 - self.p_tail) * self.body_mean + self.p_tail * self.tail_mean


def sev_params(peril: str, body: float, m: Mitigations, delta_h: float = 0.0) -> SevParams:
    psi = math.exp(-_sum(peril, m, "psi"))
    if peril == "FLOOD":
        # The Hazus curve is already a mean damage function over the whole loss range, so no separate
        # GPD tail is layered on top (that would double count deep-water losses).
        return SevParams(min(1.0, body * psi), 0.0, 1.0, 1.0, 1.0)  # sigma, xi unused: no tail
    a0, a_dh, sigma0, xi = TAIL[peril]
    p_tail = _PHI(a0 - _sum(peril, m, "alpha") - a_dh * delta_h)
    sigma = sigma0 * math.exp(-_sum(peril, m, "theta"))
    return SevParams(min(U_TAIL, body * psi), p_tail, sigma, xi, U_TAIL)


def _flood(h: PublicHazardLayer, v: PrivateVerificationLayer, m: Mitigations, a: float) -> PerilTerm:
    dh = h.freeboard_delta_h_ft if h.freeboard_delta_h_ft is not None else c("flood.freeboard_default_ft")
    d100 = h.noaa_atlas15_p24h_100yr_in * h.atlas15_cmip6_mult
    elevated = float(v.elev_cert_verified and dh >= ELEVATED_BLDG_FT)
    pi = _sigmoid(GAMMA0 + GAMMA1 * max(0.0, dh) + GAMMA2 * h.hand_rel_elev_ft + _sum("FLOOD", m, "eta"))
    lam = math.exp(a + BETA1 * d100 + BETA2 * h.twi_index - BETA3 * dh - BETA4 * elevated)
    depth = FLOOD_STAGE0_FT + FLOOD_STAGE_PER_IN * d100 - dh
    sp = sev_params("FLOOD", ddf(depth), m, dh)
    return PerilTerm("FLOOD", pi, (1 - pi) * lam, sp.mean, depth, sp)


def burn_probability_multiplier(bp: float | None) -> float:
    """Scale the fuel/slope wildfire rate by USFS Wildfire Risk to Communities burn probability relative to
    the reference value the intercept was calibrated at. None (not ingested) leaves the rate unchanged."""
    if bp is None:
        return 1.0
    lo, hi = c("wildfire.burn_prob_multiplier_clamp")
    return min(hi, max(lo, bp / c("wildfire.burn_prob_reference")))


def _wildfire(
    h: PublicHazardLayer, v: PrivateVerificationLayer, m: Mitigations, firewise: bool, a: float
) -> PerilTerm:
    overhang = v.cv_overhang_ft * (1 - m.canopy_trim)
    pi = _sigmoid(ETA0 + _sum("WILDFIRE", m, "eta"))
    lam = math.exp(
        a
        + DELTA1 * fuel_index(h.landfire_fbfm40_code)
        + DELTA2 * h.slope_deg
        + DELTA3_CANOPY * overhang
        - DELTA4_FIREWISE * float(firewise)
    )
    lam *= burn_probability_multiplier(h.wrc_burn_probability)
    sp = sev_params("WILDFIRE", BODY_WILDFIRE, m)
    return PerilTerm("WILDFIRE", pi, (1 - pi) * lam, sp.mean, None, sp)


def _wind(state: str, year_built: int, m: Mitigations, a: float) -> PerilTerm:
    pi = _sigmoid(OMEGA0 + _sum("WIND_HAIL", m, "eta"))
    lam = math.exp(a + V1_REGION * STATE_WIND_INDEX.get(state, DEFAULT_WIND_INDEX) + V2_PRE_CODE * float(year_built < PRE_CODE_YEAR))
    sp = sev_params("WIND_HAIL", BODY_WIND, m)
    return PerilTerm("WIND_HAIL", pi, (1 - pi) * lam, sp.mean, None, sp)


def _reference_intercept(
    peril: str, base_rates: BaseRates, h: PublicHazardLayer, v: PrivateVerificationLayer, state: str
) -> float:
    """Closed-form intercept so the reference home's loss rate (E[N] * E[S]) equals `rate`.

    The reference home is unmitigated, built in the tract-typical era, has no verified freeboard (first floor
    at the base flood elevation) and no verified elevation certificate, no overhang and no Firewise status.
    Rain, terrain and fuel are the tract's reference values (base_rates.reference_hazard) when known, so the
    parcel's own values act as relativities; with none, the parcel's stand in for the tract's.
    """
    ref_h = (base_rates.reference_hazard or h).model_copy(update={"freeboard_delta_h_ft": 0.0, "wrc_burn_probability": None})
    ref_v = v.model_copy(update={"elev_cert_verified": False, "cv_overhang_ft": 0.0})
    zero = Mitigations()
    if peril == "FLOOD":
        t = _flood(ref_h, ref_v, zero, 0.0)
    elif peril == "WILDFIRE":
        t = _wildfire(ref_h, ref_v, zero, False, 0.0)
    else:
        t = _wind(state, int(c("nri.reference_year_built")), zero, 0.0)
    return intercept_for(base_rates.for_peril(peril), t.n * t.s)


def peril_terms(
    hazard: PublicHazardLayer,
    verification: PrivateVerificationLayer,
    *,
    state: str,
    year_built: int,
    firewise: bool = False,
    mitigations: Mitigations | None = None,
    base_rates: BaseRates,
) -> list[PerilTerm]:
    """Per-peril (pi, E[N], E[S]); `mitigations` overrides the doses read from `verification`.

    Each intercept is solved so the reference home matches the tract loss rate in `base_rates` (NRI).
    """
    m = mitigations if mitigations is not None else mitigations_from(verification)

    def a(peril: str) -> float:
        return _reference_intercept(peril, base_rates, hazard, verification, state)

    terms = []
    for peril in active_perils(hazard):
        if peril == "FLOOD":
            terms.append(_flood(hazard, verification, m, a(peril)))
        elif peril == "WILDFIRE":
            terms.append(_wildfire(hazard, verification, m, firewise, a(peril)))
        else:
            terms.append(_wind(state, year_built, m, a(peril)))
    return terms


def parcel_raw_lcr(hazard: PublicHazardLayer, verification: PrivateVerificationLayer, **ctx) -> float:
    """AAL / RCV = sum_p E[N_p] * E[S_p] (spec 3.1)."""
    return sum(t.n * t.s for t in peril_terms(hazard, verification, **ctx))


def peril_split(
    hazard: PublicHazardLayer, verification: PrivateVerificationLayer, rcv: float, *, scale: float = 1.0, **ctx
) -> list[PerilSplit]:
    """Contract rows: expected_sev_s and peril_aal_usd are dollars (fraction * RCV).

    `scale` multiplies severity (and so each AAL) proportionally, used to restate the rows at the
    credibility-weighted rate (posterior LCR / raw LCR) so they sum to the priced AAL.
    """
    return [
        PerilSplit(
            peril=t.peril,
            zip_immunity_pi=round(t.pi, 4),
            expected_freq_n=round(t.n, 5),
            expected_sev_s=round(t.s * scale * rcv, 2),
            peril_aal_usd=round(t.n * t.s * scale * rcv, 2),
        )
        for t in peril_terms(hazard, verification, **ctx)
    ]
