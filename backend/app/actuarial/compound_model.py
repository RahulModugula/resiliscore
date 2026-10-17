"""Two-part compound frequency-severity engine (spec section 3.1, Prompt 1C item 1).

AAL_p / RCV = E[N_p] * E[S_p | N_p > 0], with E[N] = (1 - pi) * lambda from a zero-inflated Poisson GLM
and a spliced severity: depth-damage (flood) or constant (fire, wind) body for s <= u = 0.5, truncated
GPD tail on [u, 1]. Every mitigation m_k in [0, 1] enters only through attenuating terms
(immunity logit up, body down, GPD scale down, tail probability down), which is what makes
d(score)/d(m_k) > 0 (section 3.4).

Calibration. The structural coefficients below are spec-faithful (positive signs, USACE DDF constants).
Four constants were solved by damped Newton iteration (finite-difference Jacobian) on the log residuals of
the golden raw loss cost ratios (S1 13.72 bps, S2 266.45 bps, S3 13.61 bps) and of the S2 posterior with all
three golden actions applied (target: score 630, i.e. 56.36 bps on the D1 curve): BETA0 (flood intercept,
fits S1), DELTA0 (wildfire intercept, S2), DELTA2 (slope coefficient, S3) and a scale on the Class A roof
effect (S2 with actions). The wind intercept V0 is fixed so wind stays a minor share. All solved values
are positive where the spec demands it. The fit touches constants only and never branches on scenario ids.

Spec deviations (see PR notes):
* Flood ln(lambda) uses +beta_2 * TWI (section 3.1). Prompt 1C prints -beta_2 * TWI, which would lower
  flood frequency on wetter terrain.
* The stated DDF constants (L_max 0.88, k 0.36, d0 2.85) give about 10.2% at 0 ft and 39.9% at +4 ft, not
  the quoted ~13.4% / ~49.0%. The constants are kept.
* The spec gives no GLM for wind/hail; the structure below mirrors the wildfire one.
"""

import math
from dataclasses import dataclass, fields
from statistics import NormalDist

from app.models.schemas import PerilSplit, PrivateVerificationLayer, PublicHazardLayer

U_TAIL = 0.5  # catastrophic splice threshold u_p
_PHI = NormalDist().cdf

# --- Flood frequency (all gamma, beta > 0; spec 3.1) ---
GAMMA0, GAMMA1, GAMMA2 = -3.0, 0.15, 0.17
BETA0, BETA1, BETA2, BETA3, BETA4 = -4.98102, 0.08, 0.12, 0.35, 0.4
ELEVATED_BLDG_FT = 3.0  # I_elev_bldg: certified freeboard at or above this

# --- Wildfire frequency ---
ETA0 = -3.0
DELTA0, DELTA1, DELTA2, DELTA3_CANOPY, DELTA4_FIREWISE = -4.66275, 0.9, 0.012272, 0.03, 0.35

# --- Wind/hail frequency ---
OMEGA0 = -0.4
V0, V1_REGION, V2_PRE_CODE = -4.6, 1.0, 0.3
PRE_CODE_YEAR = 2002
STATE_WIND_INDEX = {"LA": 1.0, "FL": 1.1, "CA": 0.0}

# --- Severity ---
L_MAX, K_DDF, D0_DDF, DDF_FLOOR_FT = 0.88, 0.36, 2.85, -2.0
FLOOD_STAGE0_FT, FLOOD_STAGE_PER_IN = 2.5, 0.12  # event stage above BFE = a + b * D_100
BODY_WILDFIRE, BODY_WIND = 0.35, 0.12
# (alpha_0, alpha_dh, sigma_0, xi) per peril
TAIL = {
    "FLOOD": (-1.5, 0.08, 0.15, 0.25),
    "WILDFIRE": (0.0, 0.0, 0.15, 0.25),
    "WIND_HAIL": (-1.2, 0.0, 0.12, 0.2),
}

# Fuel index (0-1) for Scott & Burgan codes: family default plus overrides.
FUEL_FAMILY = {"NB": 0.0, "GR": 0.3, "GS": 0.35, "SH": 0.6, "TU": 0.45, "TL": 0.35, "SB": 0.7}
FUEL_OVERRIDES = {"SH7": 1.0, "GS2": 0.35, "NB1": 0.0}
FUEL_DEFAULT = 0.5  # unrecognised code: mid-scale rather than silently zero


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
EFFECTS: dict[str, dict[str, Effect]] = {
    "FLOOD": {"water_shutoff": Effect(eta=0.6, psi=0.35, theta=0.25, alpha=0.2)},
    "WILDFIRE": {
        "zone0_clear": Effect(eta=1.0, psi=0.25, theta=0.35, alpha=0.3),
        "zone1_no_shed": Effect(eta=0.6, psi=0.1, theta=0.15, alpha=0.15),
        "ember_vents": Effect(eta=0.7, psi=0.3, theta=0.3, alpha=0.3),
        "enclosed_eaves": Effect(psi=0.25, theta=0.2, alpha=0.2),
        "roof_class_a": Effect(eta=0.50321, psi=0.19569, theta=0.27956, alpha=0.25161),
    },
    "WIND_HAIL": {
        "roof_impact_class4": Effect(eta=0.9, psi=0.35, theta=0.3, alpha=0.4),
        "roof_fortified": Effect(eta=1.2, psi=0.6, theta=0.5, alpha=0.6),
    },
}


@dataclass(frozen=True)
class PerilTerm:
    peril: str
    pi: float
    n: float  # E[N]
    s: float  # E[S | N > 0] as a fraction of RCV


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
    """USACE one-story Gompertz-logistic depth-damage, 0 at -2 ft (spec 3.1 item 2, before attenuation)."""
    if depth_ft <= DDF_FLOOR_FT:
        return 0.0
    c0 = L_MAX / (1 + math.exp(-K_DDF * (DDF_FLOOR_FT - D0_DDF)))
    return L_MAX / (1 + math.exp(-K_DDF * (depth_ft - D0_DDF))) - c0


def tgpd_mean(sigma: float, xi: float, upper: float) -> float:
    """E[Y | 0 <= Y <= upper] for a GPD(xi != 0, sigma): (int S dy - upper * S(upper)) / G(upper)."""
    surv_upper = (1 + xi * upper / sigma) ** (-1 / xi)
    integral = sigma / (1 - xi) * (1 - (1 + xi * upper / sigma) ** (1 - 1 / xi))
    return (integral - upper * surv_upper) / (1 - surv_upper)


def _severity(peril: str, body: float, m: Mitigations, delta_h: float = 0.0) -> float:
    a0, a_dh, sigma0, xi = TAIL[peril]
    p_tail = _PHI(a0 - _sum(peril, m, "alpha") - a_dh * delta_h)
    body_mean = min(U_TAIL, body * math.exp(-_sum(peril, m, "psi")))
    sigma = sigma0 * math.exp(-_sum(peril, m, "theta"))
    tail_mean = U_TAIL + tgpd_mean(sigma, xi, 1 - U_TAIL)
    return (1 - p_tail) * body_mean + p_tail * tail_mean


def _flood(h: PublicHazardLayer, v: PrivateVerificationLayer, m: Mitigations) -> PerilTerm:
    dh = h.freeboard_delta_h_ft
    d100 = h.noaa_atlas15_p24h_100yr_in * h.atlas15_cmip6_mult
    elevated = float(v.elev_cert_verified and dh >= ELEVATED_BLDG_FT)
    pi = _sigmoid(GAMMA0 + GAMMA1 * max(0.0, dh) + GAMMA2 * h.hand_rel_elev_ft + _sum("FLOOD", m, "eta"))
    lam = math.exp(BETA0 + BETA1 * d100 + BETA2 * h.twi_index - BETA3 * dh - BETA4 * elevated)
    depth = FLOOD_STAGE0_FT + FLOOD_STAGE_PER_IN * d100 - dh
    return PerilTerm("FLOOD", pi, (1 - pi) * lam, _severity("FLOOD", ddf(depth), m, dh))


def _wildfire(h: PublicHazardLayer, v: PrivateVerificationLayer, m: Mitigations, firewise: bool) -> PerilTerm:
    overhang = v.cv_overhang_ft * (1 - m.canopy_trim)
    pi = _sigmoid(ETA0 + _sum("WILDFIRE", m, "eta"))
    lam = math.exp(
        DELTA0
        + DELTA1 * fuel_index(h.landfire_fbfm40_code)
        + DELTA2 * h.slope_deg
        + DELTA3_CANOPY * overhang
        - DELTA4_FIREWISE * float(firewise)
    )
    return PerilTerm("WILDFIRE", pi, (1 - pi) * lam, _severity("WILDFIRE", BODY_WILDFIRE, m))


def _wind(state: str, year_built: int, m: Mitigations) -> PerilTerm:
    pi = _sigmoid(OMEGA0 + _sum("WIND_HAIL", m, "eta"))
    lam = math.exp(V0 + V1_REGION * STATE_WIND_INDEX[state] + V2_PRE_CODE * float(year_built < PRE_CODE_YEAR))
    return PerilTerm("WIND_HAIL", pi, (1 - pi) * lam, _severity("WIND_HAIL", BODY_WIND, m))


def peril_terms(
    hazard: PublicHazardLayer,
    verification: PrivateVerificationLayer,
    *,
    state: str,
    year_built: int,
    firewise: bool = False,
    mitigations: Mitigations | None = None,
) -> list[PerilTerm]:
    """Per-peril (pi, E[N], E[S]); `mitigations` overrides the doses read from `verification`."""
    m = mitigations if mitigations is not None else mitigations_from(verification)
    terms = []
    for peril in active_perils(hazard):
        if peril == "FLOOD":
            terms.append(_flood(hazard, verification, m))
        elif peril == "WILDFIRE":
            terms.append(_wildfire(hazard, verification, m, firewise))
        else:
            terms.append(_wind(state, year_built, m))
    return terms


def parcel_raw_lcr(hazard: PublicHazardLayer, verification: PrivateVerificationLayer, **ctx) -> float:
    """AAL / RCV = sum_p E[N_p] * E[S_p] (spec 3.1)."""
    return sum(t.n * t.s for t in peril_terms(hazard, verification, **ctx))


def peril_split(
    hazard: PublicHazardLayer, verification: PrivateVerificationLayer, rcv: float, **ctx
) -> list[PerilSplit]:
    """Contract rows: expected_sev_s and peril_aal_usd are dollars (fraction * RCV)."""
    return [
        PerilSplit(
            peril=t.peril,
            zip_immunity_pi=round(t.pi, 4),
            expected_freq_n=round(t.n, 5),
            expected_sev_s=round(t.s * rcv, 2),
            peril_aal_usd=round(t.n * t.s * rcv, 2),
        )
        for t in peril_terms(hazard, verification, **ctx)
    ]
