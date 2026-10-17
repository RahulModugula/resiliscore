"""Model v2: constants registry, NRI base rates, property tests, Shapley attribution, uncertainty, insurance."""

import ast
import itertools
import json
import math
import time
from pathlib import Path

import numpy as np
import pytest

from app.actuarial import base_rates as br
from app.actuarial import compound_model as cm
from app.actuarial import constants, insurance, uncertainty
from app.actuarial.attribution import shapley
from app.actuarial.credibility import SIGMA2_EVPV, TAU2_VHM, K
from app.actuarial.optimizer import ACTIONS, evaluate, simulate
from app.actuarial.score_map import score_continuous
from app.fixtures import load_golden

S1, S2, S3 = "SCENARIO_1_LA_FLOOD", "SCENARIO_2_CA_WUI", "SCENARIO_3_ESCONDIDO_HITL"
S2_ACTIONS = ["CA_ZONE0_1_CLEARANCE", "CA_EMBER_VENTS_EAVES", "CA_IBHS_WPH_CLASS_A_ROOF"]
APP = Path(__file__).resolve().parents[1] / "app" / "actuarial"


def golden(key):
    return load_golden()[key]


def with_hazard(r, **changes):
    return r.model_copy(update={"public_hazard_layer": r.public_hazard_layer.model_copy(update=changes)})


def terms_of(r, **overrides):
    return cm.peril_terms(
        r.public_hazard_layer, r.private_verification_layer, state=r.parcel_identity.state,
        year_built=r.parcel_identity.year_built,
        firewise=r.regulatory_compliance.ca_2644_9_factors.cat_a_firewise_usa,
        base_rates=overrides.pop("base_rates", br.context_for(r)[0]), **overrides,
    )


def peril_term(r, peril, **overrides):
    return next(t for t in terms_of(r, **overrides) if t.peril == peril)


def peril_aal(r, peril):
    t = peril_term(r, peril)
    return t.n * t.s


def score_of(r):
    return evaluate(r, r.private_verification_layer).score


# --- registry ---
def test_every_constant_has_provenance_fields():
    for key, const in constants.REGISTRY.items():
        assert const.source_url and const.source_date and const.note, key
        assert isinstance(const.validated, bool), key


def test_validated_constants_cite_a_url():
    for key, const in constants.REGISTRY.items():
        if const.validated:
            assert const.source_url.startswith(("http", "docs/validation/")), key


def test_wildfire_and_wind_coefficients_are_priors():
    # Study data points (P(no damage), reductions) may be validated; the coefficients derived from them are not.
    data_points = {
        "wildfire.p_no_damage_one_feature", "wildfire.p_no_damage_four_features",
        "wildfire.zone0_fuel_destruction_risk", "wildfire.p_total_loss_given_ignition",
        "wind.fortified_roof.freq_reduction", "wind.fortified_roof.sev_reduction",
        "wind.fortified_gold.freq_reduction", "wind.fortified_gold.sev_reduction",
    }
    for key, const in constants.REGISTRY.items():
        if key.startswith(("wildfire.", "wind.")) and key not in data_points:
            assert not const.validated, key


def test_nothing_fitted_to_a_demo_output_remains_except_the_named_credibility_weights():
    fitted = [k for k, c in constants.REGISTRY.items() if c.source_url == constants.CAL]
    assert fitted == ["credibility.channel_weights"]
    for gone in ("flood.freq.beta0", "wildfire.delta0", "wind.v0", "credibility.k"):
        assert gone not in constants.REGISTRY


def test_hazus_table_is_the_registry_value_and_flood_curve_uses_it():
    table = constants.get("flood.ddf.usace_iwr_res1_1s_nb")
    assert len(table) == 19 and table[:5] == (0, 3, 13, 23, 32)
    for i, pct in enumerate(table):
        assert cm.ddf(-2.0 + i) == pytest.approx(pct / 100)


def test_credibility_k_is_the_variance_ratio_of_registered_priors():
    assert K == pytest.approx(SIGMA2_EVPV / TAU2_VHM)
    assert SIGMA2_EVPV == constants.get("credibility.sigma2_evpv")


def test_no_bare_float_literals_outside_the_registry():
    # 0 / 1 / 0.5 / 100 are structural; 99 and 1e4 are the no-payback sentinel and bps; the percentile pair defines
    # the 1-in-100 and 1-in-250 return periods; the two epsilons are numerical guards.
    allowed = {0.0, 0.5, 1.0, 100.0, 99.0, 10000.0, 99.6, 1e-9, 5e-05}
    offenders = []
    for name in ("compound_model", "credibility", "optimizer", "uncertainty", "insurance", "attribution", "base_rates", "nyc"):
        for node in ast.walk(ast.parse((APP / f"{name}.py").read_text())):
            if isinstance(node, ast.Constant) and isinstance(node.value, float) and node.value not in allowed:
                offenders.append((name, node.lineno, node.value))
    assert not offenders, offenders


# --- cited effects reconcile to their sources ---
def test_ibhs_feature_effect_reproduces_the_study_points():
    def p_no_damage(n_features):
        names = ["zone0_clear", "zone1_no_shed", "ember_vents", "enclosed_eaves", "roof_class_a"][:n_features]
        m = cm.Mitigations(**dict.fromkeys(names, 1.0))
        return cm._sigmoid(cm.ETA0 + cm._sum("WILDFIRE", m, "eta"))

    assert p_no_damage(1) == pytest.approx(0.36, abs=0.005)
    assert p_no_damage(4) == pytest.approx(0.54, abs=0.005)


def test_every_wildfire_feature_carries_only_the_ibhs_immunity_lift():
    for effect in cm.EFFECTS["WILDFIRE"].values():
        assert effect == cm.Effect(eta=constants.get("wildfire.eta_per_feature"))


def test_fortified_roof_reproduces_the_sally_frequency_and_severity_cuts():
    bare, fort = cm.Mitigations(), cm.Mitigations(roof_fortified=1.0, roof_impact_class4=1.0)

    def wind(m):
        sp = cm.sev_params("WIND_HAIL", cm.BODY_WIND, m)
        return (1 - cm._sigmoid(cm.OMEGA0 + cm._sum("WIND_HAIL", m, "eta"))), sp.mean

    (n0, s0), (n1, s1) = wind(bare), wind(fort)
    assert 1 - n1 / n0 == pytest.approx(constants.get("wind.fortified_roof.freq_reduction"), abs=0.005)
    assert 1 - s1 / s0 == pytest.approx(constants.get("wind.fortified_roof.sev_reduction"), abs=0.005)


# --- NRI base rates ---
TRACTS = [("22051028900", S1), ("06037460200", S2), ("06073020214", S3)]


def _nri(tractfips):
    return next(rates for _, rates, _ in br._tracts() if rates.tractfips == tractfips)


def test_nri_reference_file_records_version_and_fetch_date():
    doc = json.loads(br.DATA_PATH.read_text())
    assert doc["nri_version"] == "v1.20" and doc["fetched"] == "2026-10-17"
    assert doc["source_url"].startswith("https://services.arcgis.com/")
    for tractfips, _ in TRACTS:
        const = constants.REGISTRY[f"nri.tract.{tractfips}"]
        assert const.validated and const.source_date == "2026-10-17"


@pytest.mark.parametrize(("tractfips", "key"), TRACTS)
def test_reference_home_reproduces_the_nri_rate_within_one_percent(tractfips, key):
    nri = _nri(tractfips)
    rates = br.base_rates_for(nri)
    ref = nri.reference_hazard.model_copy(update={
        "freeboard_delta_h_ft": 0.0, "wrc_burn_probability": None, "fema_flood_zone": "AE", "wui_class": "INTERMIX",
    })
    r = golden(key)
    v = r.private_verification_layer.model_copy(update={"elev_cert_verified": False, "cv_overhang_ft": 0.0})
    terms = cm.peril_terms(
        ref, v, state=r.parcel_identity.state, year_built=int(constants.get("nri.reference_year_built")),
        firewise=False, mitigations=cm.Mitigations(), base_rates=rates,
    )
    assert {t.peril for t in terms} == {"FLOOD", "WILDFIRE", "WIND_HAIL"}
    floor = constants.get("nri.rate_floor")
    for t in terms:
        assert t.n * t.s == pytest.approx(max(rates.for_peril(t.peril), floor), rel=0.01), t.peril


def test_s2_exposed_basis_is_the_published_nri_ratio():
    nri = _nri("06037460200")
    assert br.base_rates_for(nri).wildfire == pytest.approx(357351.566083465 / 42537142.788447276)
    assert br.base_rates_for(nri, "all").wildfire == pytest.approx(357351.566083465 / 915306337)
    assert nri.tract_prior_lcr == pytest.approx(
        (1477623.5463 + 357351.566083465 + 82.58337609640596 + 1600.5240372029152) / 915306337
    )


@pytest.mark.parametrize("peril", ["FLOOD", "WILDFIRE", "WIND_HAIL"])
def test_changing_the_nri_rate_moves_the_base_rate_proportionally(peril):
    r = golden(S2)  # every peril has a non-zero NRI rate in this tract
    r = r.model_copy(update={
        "public_hazard_layer": r.public_hazard_layer.model_copy(update={"fema_flood_zone": "AE", "wui_class": "INTERMIX"})
    })
    base = br.context_for(r)[0]
    for factor in (1.5, 2.0, 3.0):  # stay above the rate floor
        scaled = br.BaseRates(
            flood=base.flood * (factor if peril == "FLOOD" else 1),
            wildfire=base.wildfire * (factor if peril == "WILDFIRE" else 1),
            wind=base.wind * (factor if peril == "WIND_HAIL" else 1),
            reference_hazard=base.reference_hazard,
        )
        a = peril_term(r, peril, base_rates=base)
        b = peril_term(r, peril, base_rates=scaled)
        assert (b.n * b.s) / (a.n * a.s) == pytest.approx(factor, rel=1e-9)


def _far(r):
    return r.model_copy(update={"parcel_identity": r.parcel_identity.model_copy(update={"centroid": (-97.0, 32.0)})})


def test_without_a_tract_a_far_parcel_uses_a_flagged_stand_in():
    far = _far(golden(S1))
    tract, stand_in = br.resolve(far, None)
    assert tract.tractfips in {t for t, _ in TRACTS} and stand_in is True
    out = simulate(far, [])
    assert out.indicative_only is True
    rows = [p for p in out.input_provenance if p.field == "actuarial_breakdown.base_rates"]
    assert len(rows) == 1 and "stand-in" in rows[0].source_name
    assert len(simulate(out, []).input_provenance) == len(out.input_provenance)  # re-simulating adds no duplicate


def test_a_golden_parcel_is_its_own_reference_and_is_not_indicative():
    out = simulate(golden(S1), [])
    assert out.indicative_only is False
    assert br.resolve(golden(S1), None)[1] is False
    assert all("stand-in" not in p.source_name for p in out.input_provenance)


def test_same_address_different_tracts_score_independently():
    base = golden(S2)
    a, b = _nri("06037460200"), _nri("06073020214")
    first = simulate(base, [], nri=a)
    other = simulate(base, [], nri=b)
    again = simulate(base, [], nri=a)
    assert first.actuarial_breakdown.resili_score != other.actuarial_breakdown.resili_score
    assert first.actuarial_breakdown.resili_score == again.actuarial_breakdown.resili_score
    assert first.actuarial_breakdown.tract_prior_lcr == pytest.approx(a.tract_prior_lcr)
    assert other.actuarial_breakdown.tract_prior_lcr == pytest.approx(b.tract_prior_lcr)


def test_nri_none_never_reads_another_parcels_data():
    s1 = golden(S1)
    before = simulate(s1, []).actuarial_breakdown.resili_score
    simulate(s1, [], nri=_nri("06073020214"))  # a different tract for the same parcel
    assert simulate(s1, []).actuarial_breakdown.resili_score == before == 823


def test_no_function_in_the_actuarial_package_mutates_module_level_state():
    mutators = {"append", "extend", "add", "update", "setdefault", "pop", "popitem", "clear", "move_to_end"}
    offenders = []
    for path in sorted(APP.glob("*.py")):
        tree = ast.parse(path.read_text())
        containers = set()
        for node in tree.body:
            if isinstance(node, ast.Assign | ast.AnnAssign) and isinstance(
                node.value, ast.Dict | ast.List | ast.Set | ast.Call
            ):
                targets = [node.target] if isinstance(node, ast.AnnAssign) else node.targets
                containers |= {t.id for t in targets if isinstance(t, ast.Name)}
        for fn in (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)):
            if fn.name == "_register_nri_tracts":  # builds the registry once, at import
                continue
            for node in ast.walk(fn):
                if isinstance(node, ast.Global):
                    offenders.append((path.name, fn.name, "global"))
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id in containers
                    and node.func.attr in mutators
                ):
                    offenders.append((path.name, fn.name, node.func.attr))
                if (
                    isinstance(node, ast.Subscript)
                    and isinstance(node.ctx, ast.Store)
                    and isinstance(node.value, ast.Name)
                    and node.value.id in containers
                ):
                    offenders.append((path.name, fn.name, "item assignment"))
    assert not offenders, offenders


def test_an_extreme_nri_rate_cannot_blow_up_the_simulation():
    s1 = golden(S1)
    t = _nri("22051028900")
    wild = br.NriRates(
        tractfips="9", buildvalue_usd=1e9, ealb_usd={**t.ealb_usd, "IFLD": 1e18, "HRCN": 1e18},
        expb_usd={**t.expb_usd, "IFLD": 1e9, "HRCN": 1e9}, reference_hazard=t.reference_hazard,
    )
    start = time.perf_counter()
    out = simulate(s1, [], nri=wild)
    assert time.perf_counter() - start < 5.0
    u = out.uncertainty
    assert math.isfinite(u.loss_1_in_250_usd) and u.loss_1_in_250_usd <= s1.parcel_identity.rcv_usd
    assert 300 <= out.actuarial_breakdown.resili_score <= 850


def test_poisson_event_count_is_capped():
    huge = cm.PerilTerm("FLOOD", 0.0, 1e9, 0.1, None, cm.SevParams(0.1, 0.0, 1.0, 1.0, 1.0))
    mc = uncertainty.simulate_losses([huge], state="LA", rcv_usd=1e5, tract_prior_lcr=0.001, z=0.9, draws=2_000)
    assert math.isfinite(mc.loss_1_in_250_usd) and mc.loss_1_in_250_usd <= 1e5


# --- property tests ---
def _flood_ready(r):
    return with_hazard(r, fema_flood_zone="AE")


def test_freeboard_frequency_channel_holding_severity_fixed(monkeypatch):
    monkeypatch.setattr(cm, "ddf", lambda depth: 0.3)
    r = _flood_ready(golden(S1))
    ns = [peril_term(with_hazard(r, freeboard_delta_h_ft=dh), "FLOOD").n for dh in (0.0, 1.0, 2.0, 4.0, 6.0)]
    assert all(a > b for a, b in itertools.pairwise(ns))
    sevs = {peril_term(with_hazard(r, freeboard_delta_h_ft=dh), "FLOOD").s for dh in (0.0, 3.0)}
    assert len(sevs) == 1


def test_depth_damage_channel_holding_frequency_fixed(monkeypatch):
    monkeypatch.setattr(cm, "BETA3", 0.0)
    monkeypatch.setattr(cm, "GAMMA1", 0.0)
    r = _flood_ready(golden(S1))
    terms = [peril_term(with_hazard(r, freeboard_delta_h_ft=dh), "FLOOD") for dh in (-1.0, 0.0, 1.0, 2.0)]  # below the elevated-building threshold
    assert len({t.n for t in terms}) == 1
    assert all(a.s > b.s for a, b in itertools.pairwise(terms))


@pytest.mark.parametrize("freeboard", [-2.0, 0.0, 1.0, 3.0, 5.0])
def test_more_freeboard_lowers_flood_aal(freeboard):
    r = _flood_ready(golden(S1))
    assert peril_aal(with_hazard(r, freeboard_delta_h_ft=freeboard + 1.0), "FLOOD") < peril_aal(
        with_hazard(r, freeboard_delta_h_ft=freeboard), "FLOOD"
    )


def _rain_channels_rise():
    r = _flood_ready(golden(S1))
    lo = peril_term(with_hazard(r, noaa_atlas15_p24h_100yr_in=8.0), "FLOOD")
    hi = peril_term(with_hazard(r, noaa_atlas15_p24h_100yr_in=10.0), "FLOOD")
    return hi.n > lo.n, hi.s > lo.s


def test_more_rain_raises_both_the_frequency_and_the_severity_channel():
    assert _rain_channels_rise() == (True, True)


def test_the_rain_test_has_teeth_it_fails_when_beta1_alone_goes_negative(monkeypatch):
    monkeypatch.setattr(cm, "BETA1", -cm.BETA1)
    assert _rain_channels_rise() != (True, True)


@pytest.mark.parametrize(
    ("key", "field", "delta"),
    [
        (S1, "noaa_atlas15_p24h_100yr_in", 2.0),
        (S1, "twi_index", 1.0),
        (S1, "freeboard_delta_h_ft", -1.5),
        (S2, "slope_deg", 5.0),
        (S2, "wrc_burn_probability", 0.01),
    ],
)
def test_higher_hazard_never_raises_the_score(key, field, delta):
    r = golden(key)
    current = getattr(r.public_hazard_layer, field)
    start = current if current is not None else constants.get("wildfire.burn_prob_reference")
    assert score_of(with_hazard(r, **{field: start + delta})) <= score_of(with_hazard(r, **{field: start}))


def test_burn_probability_scales_wildfire_and_none_leaves_the_rate_alone():
    s2 = golden(S2)
    assert s2.public_hazard_layer.wrc_burn_probability is None
    base = peril_aal(s2, "WILDFIRE")
    ref = constants.get("wildfire.burn_prob_reference")
    assert peril_aal(with_hazard(s2, wrc_burn_probability=ref), "WILDFIRE") == pytest.approx(base)
    assert peril_aal(with_hazard(s2, wrc_burn_probability=2 * ref), "WILDFIRE") == pytest.approx(2 * base)


# --- attribution ---
def test_shapley_is_exact_on_a_game_with_a_known_answer():
    # v(S) = 3*[0 in S] + 5*[1 in S] + 4*[0 and 1 in S] + 2*[2 in S]: the interaction splits evenly between 0 and 1.
    def value(s):
        return 3 * (0 in s) + 5 * (1 in s) + 4 * ((0 in s) and (1 in s)) + 2 * (2 in s)

    assert shapley(3, value) == pytest.approx([5.0, 7.0, 2.0])
    assert sum(shapley(3, value)) == pytest.approx(value(frozenset({0, 1, 2})) - value(frozenset()))


@pytest.mark.parametrize("key", [S1, S2, S3])
def test_attribution_is_additive_to_score_minus_baseline(key):
    for ids in ([], S2_ACTIONS if key == S2 else []):
        out = simulate(golden(key), ids)
        a = out.actuarial_breakdown
        total = sum(f.score_points for f in out.factor_contributions)
        want = score_continuous(a.posterior_lcr) - score_continuous(a.tract_prior_lcr)
        assert total == pytest.approx(want, abs=0.1)  # posterior is rounded to 6 dp in the response
        assert abs(total - (a.resili_score - a.baseline_macro_score)) < 1.0
        assert len({f.factor for f in out.factor_contributions}) == len(out.factor_contributions)


def test_one_attribution_row_matches_an_independent_recomputation():
    # Wildfire hardening is the only active dose group, so its Shapley value averages its marginal effect over the
    # other active groups. Recompute the two extreme marginals independently and require the row to lie between them.
    r = golden(S2)
    out = simulate(r, S2_ACTIONS)
    row = next(f.score_points for f in out.factor_contributions if f.factor == "Wildfire home hardening")
    v_on = out.private_verification_layer
    v_off = v_on.model_copy(update={
        "cv_zone0_clear": False, "cv_zone1_no_shed": False, "cv_enclosed_eaves": False, "cv_ember_vents": False,
        "cv_roof_class": "WOOD_SHAKE_UNRATED",
    })
    marginal = score_continuous(evaluate(r, v_on).posterior_lcr) - score_continuous(evaluate(r, v_off).posterior_lcr)
    assert row > 0 and marginal > 0
    assert 0.5 * min(row, marginal) <= max(row, marginal) <= 2 * min(row, marginal) + 1


def test_attribution_credits_hardening_when_s2_actions_are_on():
    rows = {f.factor: f.score_points for f in simulate(golden(S2), S2_ACTIONS).factor_contributions}
    assert rows["Wildfire home hardening"] > 0
    assert "Wildfire home hardening" not in {f.factor for f in simulate(golden(S2), []).factor_contributions}


# --- uncertainty ---
def _mc(key, ids=()):
    r = golden(key)
    v = simulate(r, list(ids)).private_verification_layer
    ev = evaluate(r, v)
    return uncertainty.simulate_losses(
        ev.terms, state=r.parcel_identity.state, rcv_usd=r.parcel_identity.rcv_usd,
        tract_prior_lcr=br.context_for(r)[1], z=ev.credibility.z,
    )


def _p_any(mc):
    return float(mc.method.split("p_any_loss=")[1])


@pytest.mark.parametrize("key", [S1, S2, S3])
def test_uncertainty_is_ordered_and_brackets_the_priced_loss(key):
    mc = _mc(key)
    priced = simulate(golden(key), []).actuarial_breakdown
    assert mc.aal_p05_usd <= mc.aal_p50_usd <= mc.aal_p95_usd
    assert mc.aal_p05_usd <= priced.expected_annual_loss_usd <= mc.aal_p95_usd
    assert mc.score_p05 <= priced.resili_score <= mc.score_p95
    assert mc.loss_1_in_100_usd <= mc.loss_1_in_250_usd <= golden(key).parcel_identity.rcv_usd
    assert 0.0 <= _p_any(mc) <= 1.0


@pytest.mark.parametrize("key", [S1, S2, S3])
def test_one_in_100_is_not_below_the_aal_when_a_loss_is_at_least_1_percent_likely(key):
    mc = _mc(key)
    aal = simulate(golden(key), []).actuarial_breakdown.expected_annual_loss_usd
    if _p_any(mc) >= 0.01:
        assert mc.loss_1_in_100_usd >= aal
    else:
        # Documented: below 1% the 99th percentile is the no-event value, which can sit under a mean carried by
        # rare large losses. It cannot be asserted in general for heavy-tailed rare perils.
        assert mc.loss_1_in_100_usd <= mc.loss_1_in_250_usd


def test_uncertainty_is_seeded_and_fast():
    _mc(S2)  # warm numpy
    t0 = time.perf_counter()
    first = _mc(S2)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    assert first == _mc(S2)
    assert elapsed_ms < 50


def test_gulf_copula_correlates_flood_and_wind():
    perils = ["FLOOD", "WILDFIRE", "WIND_HAIL"]
    gulf, ca = uncertainty.correlation(perils, "LA"), uncertainty.correlation(perils, "CA")
    assert gulf[0, 2] == pytest.approx(constants.get("mc.copula_rho_gulf"))
    assert ca[0, 2] == pytest.approx(constants.get("mc.copula_rho_other"))
    assert np.allclose(gulf, gulf.T) and np.all(np.linalg.eigvalsh(gulf) > 0)


def test_correlation_fattens_the_tail():
    s1 = golden(S1)
    ev = evaluate(s1, s1.private_verification_layer)
    args = {"rcv_usd": s1.parcel_identity.rcv_usd, "tract_prior_lcr": br.context_for(s1)[1], "z": ev.credibility.z}
    gulf = uncertainty.simulate_losses(ev.terms, state="LA", **args)
    other = uncertainty.simulate_losses(ev.terms, state="CA", **args)
    assert gulf.aal_p95_usd > other.aal_p95_usd


# --- insurance layer ---
def test_premium_build_arithmetic_and_deductible_effect():
    out = simulate(golden(S2), S2_ACTIONS)
    pb = out.premium_build
    assert pb.net_expected_loss_usd < pb.expected_loss_usd
    loads = (pb.expense_load_pct + pb.profit_load_pct) / 100
    assert pb.indicated_premium_usd == pytest.approx(pb.net_expected_loss_usd / (1 - loads), abs=0.01)
    assert pb.filed_mitigation_credit_pct == out.actuarial_breakdown.statutory_discount_pct
    assert pb.deductible_usd == pytest.approx(0.01 * out.parcel_identity.rcv_usd)


def test_indicated_premium_is_reported_beside_the_filed_premium_for_s2():
    # The reconciliation note in D3: indicated vs filed is reported, not hidden.
    out = simulate(golden(S2), [])
    assert out.premium_build.indicated_premium_usd == pytest.approx(11986.86, abs=0.01)
    assert out.actuarial_breakdown.annual_discounted_premium_usd == 11200.0


def test_bigger_deductible_lowers_net_loss():
    s1 = golden(S1)
    ev = evaluate(s1, s1.private_verification_layer)
    scale = ev.posterior_lcr / ev.raw_lcr
    args = {"scale": scale, "rcv_usd": s1.parcel_identity.rcv_usd}
    nets = [insurance.net_expected_loss(ev.terms, deductible_pct=d, **args) for d in (0.0, 0.01, 0.02, 0.05)]
    assert nets[0] == pytest.approx(ev.posterior_lcr * s1.parcel_identity.rcv_usd, rel=0.02)
    assert all(a > b for a, b in itertools.pairwise(nets))


def test_modeled_credit_is_zero_without_mitigation_and_positive_with():
    s2 = golden(S2)
    assert simulate(s2, []).premium_build.modeled_mitigation_credit_pct == pytest.approx(0.0, abs=1e-6)
    assert simulate(s2, S2_ACTIONS).premium_build.modeled_mitigation_credit_pct > 20


def test_score_band_boundary_feeds_hitl_trigger_04():
    from app.actuarial.compliance import hitl_status

    out = hitl_status(rcv_usd=500_000.0, cv_confidence=0.95, unpermitted_footprint_delta_sqft=0.0, resili_score=585)
    assert out.trigger_code == "HITL_TRIGGER_04_BOUNDARY_CONFLICT"


def test_math_is_finite_everywhere():
    for key in (S1, S2, S3):
        out = simulate(golden(key), [])
        for value in out.premium_build.model_dump().values():
            assert math.isfinite(value)


# --- mitigation rows are physical effects at the as-found credibility ---
@pytest.mark.parametrize("key", [S1, S2, S3, "SCENARIO_3_ESCONDIDO_HITL__UNPERMITTED"])
def test_no_mitigation_row_scores_negative(key):
    r = golden(key)
    for ids in ([], S2_ACTIONS if key == S2 else []):
        for row in simulate(r, ids).prescriptive_mitigations:
            assert row.score_delta_pts >= 0, row.action_id
            assert row.lcr_delta_bps <= 0, row.action_id


def test_a_row_holds_z_at_the_as_found_value():
    r = golden(S2)
    row = next(m for m in simulate(r, []).prescriptive_mitigations if m.action_id == "CA_IBHS_WPH_CLASS_A_ROOF")
    assert row.score_delta_pts > 0  # was -40 when the WPH certificate's evidence was folded into the row
    v = r.private_verification_layer
    action = next(a for a in ACTIONS if a.action_id == row.action_id)
    z = evaluate(r, v).credibility.z
    on, off = evaluate(r, action.with_(v), z=z), evaluate(r, action.without(v), z=z)
    assert row.score_delta_pts == on.score - off.score


def test_the_evidence_leg_is_still_visible_in_the_headline_score():
    r = golden(S2)
    headline = simulate(r, ["CA_IBHS_WPH_CLASS_A_ROOF"]).actuarial_breakdown
    assert headline.credibility_weight_z > simulate(r, []).actuarial_breakdown.credibility_weight_z


# --- missing freeboard ---
def _no_freeboard(r):
    return with_hazard(r, freeboard_delta_h_ft=None)


def test_missing_freeboard_is_not_the_same_as_zero_and_is_flagged_indicative():
    s1 = golden(S1)
    none, zero = simulate(_no_freeboard(s1), []), simulate(with_hazard(s1, freeboard_delta_h_ft=0.0), [])
    assert none.actuarial_breakdown.parcel_raw_lcr != zero.actuarial_breakdown.parcel_raw_lcr
    assert none.indicative_only is True and zero.indicative_only is False
    assert none.actuarial_breakdown.parcel_raw_lcr > golden_raw(S1)  # default sits below the BFE


def golden_raw(key):
    return simulate(golden(key), []).actuarial_breakdown.parcel_raw_lcr


def test_missing_freeboard_widens_the_flood_uncertainty_band():
    s1 = golden(S1)
    ev = evaluate(s1, s1.private_verification_layer)
    args = {"state": "LA", "rcv_usd": s1.parcel_identity.rcv_usd, "tract_prior_lcr": br.context_for(s1)[1], "z": ev.credibility.z}
    known = uncertainty.simulate_losses(ev.terms, freeboard_known=True, **args)
    unknown = uncertainty.simulate_losses(ev.terms, freeboard_known=False, **args)
    assert unknown.aal_p95_usd - unknown.aal_p05_usd > known.aal_p95_usd - known.aal_p05_usd


def test_missing_freeboard_is_unavailable_in_provenance_and_scores_without_error():
    out = simulate(_no_freeboard(golden(S1)), [])
    from app import provenance

    rows = {p.field: p.value_source for p in provenance.build(out)}
    assert rows["public_hazard_layer.freeboard_delta_h_ft"] == "UNAVAILABLE"
    assert 300 <= out.actuarial_breakdown.resili_score <= 850
