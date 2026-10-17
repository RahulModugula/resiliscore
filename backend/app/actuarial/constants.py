"""Constants registry: every coefficient the engine uses, with its provenance.

Each entry carries {value, source_url, source_date, validated, note}. `validated=True` means the value is
taken from, or derived by a documented rule from, a primary or official source. `validated=False` is a prior:
a placeholder, an engineering judgement, or a value that only a secondary source supports. Priors are not
validated against loss data and must not be presented as such.

Entries with source_url "internal:calibration" were solved by damped Newton to the demo reference parcels
(scripts and tests/test_actuarial.py describe the targets). They are labelled as such and never validated.
Dates are the day the source was read.
"""

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Const:
    value: float | tuple | dict
    source_url: str
    source_date: str
    validated: bool
    note: str


SPEC = "internal:docs/SPEC.md"
CAL = "internal:calibration"
JUDGEMENT = "internal:engineering-judgement"
_D = "2026-10-17"

_HAZUS = "https://zenodo.org/records/10027236/files/haz_fl_dept.csv?download=1"
_SALLY = "https://culverhouse.ua.edu/?p=29203"
_IBHS_LA = (
    "https://abgt.assembly.ca.gov/system/files/2026-05/"
    "panel-1-steve-hawks-2026-5-6-ca-assembly-4-hearing.pdf"
)
_LA_DISC = "https://www.wafb.com/2026/09/24/louisiana-homeowners-could-qualify-up-49-hurricane-insurance-discount/"

# Hazus RES1 depth-damage, structure, as % of replacement value at -2..+16 ft relative to the first finished floor.
_HAZUS_129 = (0, 3, 13, 23, 32, 40, 47, 53, 59, 63, 67, 71, 73, 75, 77, 79, 80, 81, 81)
_HAZUS_105 = (0, 0, 18, 22, 25, 28, 30, 31, 40, 43, 43, 45, 46, 47, 47, 49, 50, 50, 50)
_HAZUS_113 = (0, 0, 8, 10, 14, 26, 28, 29, 41, 43, 44, 45, 46, 47, 48, 49, 50, 51, 52)

REGISTRY: dict[str, Const] = {
    # ---- Flood severity: Hazus depth-damage (validated) ----
    "flood.ddf.usace_iwr_res1_1s_nb": Const(
        _HAZUS_129, _HAZUS, _D, True,
        "Hazus export, DmgFnId 129 (USACE-IWR RES1, one story, no basement, structure), percent damage at "
        "-2..+16 ft relative to first finished floor; checked against the CSV on the read date. Used as "
        "the flood depth-damage body (replaces the spec Gompertz-logistic curve).",
    ),
    "flood.ddf.fia_a_zone_low": Const(
        _HAZUS_105, _HAZUS, _D, True,
        "Hazus DmgFnId 105 (FIA RES1 one floor, no basement, structure, A-Zone); low-case sensitivity curve.",
    ),
    "flood.ddf.fia_v_zone": Const(
        _HAZUS_113, _HAZUS, _D, True,
        "Hazus DmgFnId 113 (FIA RES1 one floor, no basement, structure, V-Zone); sensitivity curve.",
    ),
    "flood.ddf.depth_clamp_ft": Const(
        (-2.0, 16.0), _HAZUS, _D, True, "Curve support; depth is clamped to this range."
    ),
    # ---- Flood stage and frequency (priors / calibration) ----
    "flood.stage0_ft": Const(
        2.5, JUDGEMENT, _D, False,
        "Event stage above BFE = a + b * D_100. a and b are priors; no citable source. Freeboard acts by "
        "shifting first-floor height through the Hazus curve: depth = stage - freeboard (RR2.0 rates on "
        "first-floor height).",
    ),
    "flood.stage_per_in": Const(0.12, JUDGEMENT, _D, False, "Stage per inch of 24h 100-yr rain; prior."),
    "flood.zip.gamma": Const((-3.0, 0.15, 0.17), SPEC, _D, False, "Immunity logit (gamma0..gamma2) from spec 3.1."),
    "flood.freq.beta": Const((0.08, 0.12, 0.35, 0.4), SPEC, _D, False, "beta1 rain, beta2 TWI (+), beta3 freeboard, beta4 elevated."),
    "flood.freeboard_default_ft": Const(
        -1.0, JUDGEMENT, _D, False,
        "Used when freeboard is unavailable (no BFE or failed elevation lookup): first floor one foot below the "
        "base flood elevation, the neutral-to-adverse reading for existing homes in a special flood hazard area. "
        "A prior, not a Hazus foundation-type default; replace with Hazus first-floor-height defaults by foundation "
        "type. It differs from 0.0 on purpose so a missing value is never read as 'at BFE'.",
    ),
    "flood.elevated_bldg_ft": Const(3.0, SPEC, _D, False, "Certified freeboard threshold for I_elev_bldg."),
    "flood.effect.water_shutoff": Const(
        (0.6, 0.35, 0.25, 0.2), JUDGEMENT, _D, False, "(eta, psi, theta, alpha); no loss-reduction study cited."
    ),
    # ---- Wildfire (priors, with IBHS-derived feature effect) ----
    "wildfire.p_no_damage_one_feature": Const(
        0.36, _IBHS_LA, "2026-05-06", True,
        "IBHS LA conflagration study (Dec 2025, panel slides): probability of avoiding damage with 1 hardening "
        "feature. One event (LA 2025 fires); not a rate study.",
    ),
    "wildfire.p_no_damage_four_features": Const(
        0.54, _IBHS_LA, "2026-05-06", True, "Same study: 4 hardening features."
    ),
    "wildfire.eta_per_feature": Const(
        0.2453, _IBHS_LA, "2026-05-06", False,
        "Logit lift per feature solving logit(0.54) = ETA0 + 4e and logit(0.36) = ETA0 + e. Equal weight for "
        "each of our five features (zone 0, zone 1, ember vents, eaves, Class A roof) is a simplification: the "
        "study's feature list differs from ours. Prior, applied outside its sample.",
    ),
    "wildfire.eta0": Const(
        -0.8207, _IBHS_LA, "2026-05-06", False, "Immunity logit with zero features; solved from the two points above."
    ),
    "wildfire.zone0_fuel_destruction_risk": Const(
        0.90, _IBHS_LA, "2026-05-06", True,
        "Zone 0 fuel coverage above 25%: about 90% damage or destruction risk (same study). Reference only.",
    ),
    "wildfire.p_total_loss_given_ignition": Const(
        0.90, _IBHS_LA, "2026-05-06", True,
        "Ignition means total loss more than 90% of the time: wildfire severity is near total, so the tail "
        "carries most of the mass. Sets the unmitigated tail probability prior (alpha0 = 1.28).",
    ),
    "wildfire.freq": Const(
        (0.9, 0.02, 0.03, 0.35), SPEC, _D, False,
        "delta1 fuel, delta2 slope (a prior; pre-v2 it was fitted to a golden score and has been reset), "
        "delta3 overhang, delta4 firewise. Priors, no source. The wildfire intercept is the NRI-solved one.",
    ),
    "wildfire.burn_prob_reference": Const(
        0.004, "https://wildfirerisk.org/", "2026-10-17", False,
        "Burn probability (annual chance a fire burns the location, USFS Wildfire Risk to Communities, "
        "RDS-2020-0016-2) at which the wildfire intercept applies. The fuel/slope rate is multiplied by "
        "BP / reference, elasticity 1. The reference is a prior, not fitted; the golden parcels carry no BP.",
    ),
    "wildfire.burn_prob_multiplier_clamp": Const(
        (0.1, 10.0), JUDGEMENT, _D, False, "Bounds on the burn-probability multiplier."
    ),
    "wildfire.body": Const(0.35, JUDGEMENT, _D, False, "Partial-loss body mean; prior (wildfire is mostly total loss)."),
    "wildfire.fuel_overrides": Const(
        {"SH7": 1.0, "GS2": 0.35, "NB1": 0.0}, JUDGEMENT, _D, False, "Per-code fuel index overrides; judgement."
    ),
    "wildfire.effect.feature": Const(
        (0.2453, 0.0, 0.0, 0.0), _IBHS_LA, "2026-05-06", False,
        "(eta, psi, theta, alpha) for each of the five hardening features, including the Class A roof. The "
        "IBHS study speaks only to the probability of avoiding damage, so only the immunity lift is non-zero; "
        "no severity attenuation is invented. Pre-v2 roof_class_a severity scales (0.196/0.280/0.252) were "
        "fitted to a golden score and are gone.",
    ),
    "wildfire.tail": Const(
        (1.28, 0.0, 0.40, 0.25), _IBHS_LA, "2026-05-06", False,
        "(alpha0, alpha_dh, sigma0, xi): Phi(1.28) = 0.90 tail probability and a heavy GPD scale, per the "
        "ignition-means-total-loss finding. Wildfire is a prior, validated: false.",
    ),
    "wildfire.fuel_family": Const(
        {"NB": 0.0, "GR": 0.3, "GS": 0.35, "SH": 0.6, "TU": 0.45, "TL": 0.35, "SB": 0.7},
        JUDGEMENT, _D, False, "Scott & Burgan fuel family to 0-1 index; ordering is judgement.",
    ),
    "wildfire.fuel_default": Const(0.5, JUDGEMENT, _D, False, "Unrecognised code: mid-scale."),
    # ---- Wind / hail (priors, with Sally-derived FORTIFIED effect) ----
    "wind.omega0": Const(-0.4, SPEC, _D, False, "Wind immunity logit intercept; prior."),
    "wind.v_region_precode": Const((1.0, 0.3), SPEC, _D, False, "Region and pre-code coefficients; priors."),
    "wind.pre_code_year": Const(2002, JUDGEMENT, _D, False, "Pre-code cut-off year; prior."),
    "wind.state_index": Const(
        {"LA": 1.0, "AL": 1.0, "FL": 1.1, "CA": 0.0}, JUDGEMENT, _D, False, "Hurricane exposure index by state; prior."
    ),
    "wind.state_index_default": Const(0.5, JUDGEMENT, _D, False, "States outside the table."),
    "wind.body": Const(0.12, JUDGEMENT, _D, False, "Wind/hail body mean; prior."),
    "wind.tail": Const((-1.2, 0.0, 0.12, 0.2), SPEC, _D, False, "Wind/hail tail; priors."),
    "wind.fortified_roof.freq_reduction": Const(
        0.73, _SALLY, "2026-10-17", True,
        "Hurricane Sally study (Univ. of Alabama CRIR for ALDOI, 2025): FORTIFIED Roof claim frequency -73%. "
        "One storm, one state.",
    ),
    "wind.fortified_roof.sev_reduction": Const(0.15, _SALLY, "2026-10-17", True, "Same study: severity -15%."),
    "wind.fortified_gold.freq_reduction": Const(0.76, _SALLY, "2026-10-17", True, "FORTIFIED Gold, frequency (reference)."),
    "wind.fortified_gold.sev_reduction": Const(0.24, _SALLY, "2026-10-17", True, "FORTIFIED Gold, severity (reference)."),
    "wind.class4.freq_reduction": Const(
        0.30, "https://ibhs.org/", "2026-10-17", False,
        "IBHS DFW hail study reports -40% to -55% claim rate but sources conflict (secondary). Conservative "
        "-30% used as a prior. UNVERIFIED.",
    ),
    "wind.effect.roof_impact_class4": Const(
        (0.72655, 0.0, 0.0, 0.0), JUDGEMENT, _D, False,
        "(eta, psi, theta, alpha): eta from the -30% claim-rate prior at the baseline immunity; severity unchanged.",
    ),
    "wind.effect.roof_fortified": Const(
        (1.31949, 0.13523, 0.11269, 0.13523), _SALLY, "2026-10-17", False,
        "(eta, psi, theta, alpha) solved so a FORTIFIED Roof (which also sets the Class 4 dose) cuts the "
        "unmitigated wind claim frequency by 73% and mean severity by 15%, per one storm (Sally). Tests "
        "reconcile both ratios. Applied to all wind regions, outside its sample.",
    ),
    # ---- Credibility ----
    "credibility.sigma2_evpv": Const(
        0.6, "https://en.wikipedia.org/wiki/B%C3%BChlmann_model", "2026-10-17", False,
        "Expected process variance. Z = w / (w + k), k = EPV / VHM: the standard Buhlmann-Straub formula; no CAS "
        "primary source was fetched, so the reference is UNVERIFIED. The value is a prior.",
    ),
    "credibility.tau2_vhm": Const(
        0.75, "https://en.wikipedia.org/wiki/B%C3%BChlmann_model", "2026-10-17", False,
        "Variance of hypothetical means; a prior (see credibility.sigma2_evpv).",
    ),
    "tail.splice_u": Const(0.5, SPEC, _D, False, "Catastrophic splice threshold u (share of RCV); spec prior."),
    "action.economics": Const(
        {
            "CA_ZONE0_1_CLEARANCE": (1800.0, 0.4), "CA_EMBER_VENTS_EAVES": (3200.0, 0.6),
            "CA_IBHS_WPH_CLASS_A_ROOF": (14500.0, 1.2), "CA_IBHS_WPH_PLUS": (15000.0, 1.5),
            "LA_FORTIFIED_ROOF": (18000.0, 6.8), "HAIL_CLASS4_ROOF": (9000.0, 0.8),
            "SMART_WATER_SHUTOFF": (650.0, 0.2),
        },
        SPEC, _D, False,
        "(gross capex USD, resale value bump %) per action: demo estimates from the spec, not quotes. The 6.8% "
        "FORTIFIED resale figure is the spec's.",
    ),
    "credibility.channel_weights": Const(
        {"lidar": 0.6, "cv": 0.775, "elev_cert": 7.0, "iot": 8.0, "fortified": {"ROOF": 4.2, "SILVER": 6.0, "GOLD": 8.0},
         "wph": {"BASE": 9.0, "PLUS": 16.5}},
        CAL, _D, False,
        "Channel weights chosen in the pre-v2 build so the reference parcels land on the spec's published "
        "credibility factors (0.94 / 0.62 / 0.97). That is a fit to spec outputs; they are priors, not estimated "
        "from sensor accuracy, and remain the one item tied to the demo.",
    ),
    "credibility.limited_fluctuation_full_claims": Const(
        1082, "https://en.wikipedia.org/wiki/Credibility_theory", "2026-10-17", False,
        "Full-credibility standard at 90% / +-5%. Reference only, UNVERIFIED.",
    ),
    "prior.openfema_tract": Const(
        0.0, "https://www.fema.gov/openfema-data-page/fima-nfip-redacted-claims-v2", "2026-10-17", False,
        "The tract prior is the mean claim-level loss cost ratio of the county's NFIP claims (Gamma moment "
        "fit). It is not an exposure-weighted Poisson-Gamma posterior: OpenFEMA claims carry no policy-years "
        "in force, so a conjugate frequency update is not possible without the policies dataset. Labelled "
        "as a prior.",
    ),
    # ---- Statutory credits ----
    "credit.la_fortified": Const(
        {"ROOF": {"South": 0.29, "Central": 0.27, "North": 0.16}, "SILVER": {"South": 0.43, "Central": 0.35, "North": 0.20},
         "GOLD": {"South": 0.49, "Central": 0.42, "North": 0.24}},
        _LA_DISC, "2026-09-24", False,
        "Louisiana FORTIFIED hurricane-portion discounts by region. News report, secondary source. The "
        "engine uses the South values (Gulf parishes); Alabama percentages are UNVERIFIED and reuse them.",
    ),
    "credit.grant_usd": Const(
        10_000.0, "https://aldoi.gov/SAH/Home.aspx", "2026-10-17", True, "Alabama SAH grant up to $10k; Louisiana Fortify Homes $10k."
    ),
    "credit.wildfire": Const(
        {"zone0_clear": 0.06, "zone1_no_shed": 0.03, "ember_vents": 0.05, "enclosed_eaves": 0.03, "roof_class_a": 0.08},
        "https://www.law.cornell.edu/regulations/california/10-CCR-2644.9", "2026-10-17", False,
        "10 CCR 2644.9 lists the mitigation factors but sets no percentages; these filed-credit shares are priors.",
    ),
    "credit.wildfire_cap": Const(0.30, SPEC, _D, False, "Wildfire peril discount cap (WPH Plus earns the cap); prior."),
    "credit.wph_base_bonus": Const(0.05, SPEC, _D, False, "WPH Base bonus; prior."),
    "credit.wind_cap": Const(0.55, SPEC, _D, False, "Wind peril discount cap; prior."),
    "credit.class4": Const(0.124, SPEC, _D, False, "Class 4 hail credit; prior."),
    # ---- Insurance layer ----
    "premium.expense_load": Const(
        0.30, JUDGEMENT, _D, False,
        "Variable expense ratio. No primary figure found: replace with the filed rate manual / NAIC "
        "Profitability by Line.",
    ),
    "premium.profit_load": Const(0.05, JUDGEMENT, _D, False, "Profit and contingency load; replace as above."),
    "premium.fixed_expense_usd": Const(0.0, JUDGEMENT, _D, False, "Per-policy fixed expense; zero until a filing supplies it."),
    "premium.deductible_pct_rcv": Const(
        0.01, JUDGEMENT, _D, False, "Typical HO-3 percentage deductible (1% of coverage A); prior, not a filed value."
    ),
    # ---- NRI-calibrated base rates ----
    "nri.rate_floor": Const(
        1e-6, JUDGEMENT, _D, False,
        "Lower bound on a target loss rate (0.01 bp) so the closed-form intercept stays finite where NRI reports "
        "zero expected loss (for example wildfire in the Escondido tract).",
    ),
    "nri.reference_year_built": Const(
        1985, JUDGEMENT, _D, False,
        "Tract-typical construction year of the reference home (pre-2002 code era). No tract median year-built "
        "is ingested; replace with the ACS median.",
    ),
    # ---- Uncertainty ----
    "mc.draws": Const(10_000, JUDGEMENT, _D, False, "Monte Carlo draws."),
    "mc.seed": Const(20261017, JUDGEMENT, _D, False, "Fixed seed: results are deterministic."),
    "mc.param_cv": Const(
        {"FLOOD": 0.45, "WILDFIRE": 0.60, "WIND_HAIL": 0.50}, JUDGEMENT, _D, False,
        "Lognormal parameter-uncertainty CV on each peril's expected loss. Priors; wildfire and wind are the "
        "least constrained.",
    ),
    "mc.freeboard_missing_cv_mult": Const(
        1.5, JUDGEMENT, _D, False, "Flood parameter-uncertainty CV multiplier when freeboard is unavailable."
    ),
    "mc.copula_rho_gulf": Const(
        0.5, JUDGEMENT, _D, False, "Gaussian copula correlation between flood and wind drivers in Gulf states."
    ),
    "mc.copula_rho_other": Const(0.15, JUDGEMENT, _D, False, "Correlation between any other peril pair."),
    "mc.body_cv": Const(0.6, JUDGEMENT, _D, False, "Per-event severity noise (lognormal CV) in the partial-loss body."),
}


def get(key: str):
    return REGISTRY[key].value


def unvalidated() -> list[str]:
    return sorted(k for k, c in REGISTRY.items() if not c.validated)


def _register_nri_tracts() -> None:
    """One entry per reference tract from backend/data/nri_reference_tracts.json (FEMA NRI, primary source)."""
    path = Path(__file__).resolve().parents[2] / "data" / "nri_reference_tracts.json"
    doc = json.loads(path.read_text())
    for t in doc["tracts"]:
        eal = {h: v["ealb_usd"] for h, v in t["hazards"].items()}
        REGISTRY[f"nri.tract.{t['tractfips']}"] = Const(
            {"buildvalue_usd": t["buildvalue_usd"], "ealb_usd": eal, "expb_usd": {h: v["expb_usd"] for h, v in t["hazards"].items()}},
            doc["source_url"], doc["fetched"], True,
            f"FEMA National Risk Index {doc['nri_version']} ({doc['nri_ver_field']}), tract {t['tractfips']}, "
            f"reference tract for {', '.join(t['scenario_ids'])}. Field names checked against the layer metadata.",
        )


_register_nri_tracts()
