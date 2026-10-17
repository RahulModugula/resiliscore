"""NYC model: pluvial and sewer-backup perils, basement terms, retrofits (relativities on the NRI tract level)."""

import json
import math
from dataclasses import replace
from pathlib import Path

import pytest

from app.actuarial import base_rates as br
from app.actuarial import compound_model as cm
from app.actuarial import constants, nyc, uncertainty
from app.actuarial.optimizer import ACTIONS, evaluate, simulate
from app.actuarial.score_map import score_continuous
from app.fixtures import load_golden
from app.ingestion import nri
from app.models.schemas import DepStormwater, NycLayer

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "nri_nyc_tracts.json").read_text())
SCENARIOS = ("LIMITED_CURRENT", "MODERATE_CURRENT", "EXTREME_2080")
ALL_NYC = [a.action_id for a in ACTIONS if a.nyc_dose]


def tract(name="red_hook_brooklyn"):
    return nri.parse_nri({"features": [{"attributes": FIXTURE["tracts"][name]["attributes"]}]})


def base_parcel():
    base = load_golden()["SCENARIO_1_LA_FLOOD"]
    hazard = base.public_hazard_layer.model_copy(
        update={"fema_flood_zone": "AE", "wui_class": "NON_WUI", "freeboard_delta_h_ft": 0.0}
    )
    return base.model_copy(update={"public_hazard_layer": hazard})


PARCEL = base_parcel()
TRACT = br.nri_from_tract(tract(), PARCEL.public_hazard_layer)


def layer(kind="PARTIAL", dep="NUISANCE", **kw) -> NycLayer:
    scenarios = [DepStormwater(scenario=s, flood_class=dep) for s in SCENARIOS] if dep else []
    fields = {
        "sewer_backup_311_500m_5y": 60, "catch_basins_150m": 14, "residential_units_500m": 3650,
        "dob_cellar_conversion_flag": False, "sandy_inundated": False, "floodnet_events_500m_5y": 0,
    }
    return nyc.blank_layer(bbl="3000000001", basement_type=kind, dep_stormwater=scenarios, **{**fields, **kw})


def run(nyc_layer, ids=()):
    return simulate(PARCEL, list(ids), nri=TRACT, nyc=nyc_layer)


def aal(out, peril):
    return next(p.peril_aal_usd for p in out.actuarial_breakdown.peril_split if p.peril == peril)


def terms(nyc_layer, installed=frozenset()):
    return {
        t.peril: t
        for t in cm.peril_terms(
            PARCEL.public_hazard_layer, PARCEL.private_verification_layer, state="NY", year_built=1930,
            base_rates=br.context_for(PARCEL, TRACT, nyc=True)[0], nyc_layer=nyc_layer, nyc_installed=installed,
        )
    }


# --- rainfall to exceedance and DEP parsing ---
def test_exceedance_follows_the_noaa_table_and_falls_with_intensity():
    p = [nyc.annual_exceedance(r) for r in (1.77, 2.13, 3.66)]
    assert p[0] > p[1] > p[2]
    assert 0.10 < p[0] < 0.20 and 0.04 < p[1] < 0.10 and 0.001 < p[2] < 0.01  # 1.77 in/hr sits between 5 and 10 years
    assert nyc.annual_exceedance(1.91) == pytest.approx(0.10)  # the 10-year point of the table
    assert nyc.annual_exceedance(1.0) == pytest.approx(1.0) and nyc.annual_exceedance(9.0) == pytest.approx(0.001)


def test_dep_scenarios_map_to_their_rainfall_rates_and_classes_to_depths():
    rows = [
        DepStormwater(scenario="LIMITED_CURRENT", flood_class="NUISANCE"),
        DepStormwater(scenario="MODERATE_2050", flood_class="DEEP_CONTIGUOUS"),
        DepStormwater(scenario="EXTREME_2080", flood_class="DEEP_CONTIGUOUS"),
    ]
    ladder = nyc.scenario_ladder(layer(dep=None).model_copy(update={"dep_stormwater": rows}))
    depths = constants.get("nyc.dep_class_depth_ft")
    assert [d for _, d in ladder] == [depths["NUISANCE"], depths["DEEP_CONTIGUOUS"], depths["DEEP_CONTIGUOUS"]]


def test_the_deeper_of_two_moderate_maps_wins():
    rows = [
        DepStormwater(scenario="MODERATE_CURRENT", flood_class="NUISANCE"),
        DepStormwater(scenario="MODERATE_2050", flood_class="DEEP_CONTIGUOUS"),
    ]
    ladder = nyc.scenario_ladder(layer(dep=None).model_copy(update={"dep_stormwater": rows}))
    assert ladder[1][1] == constants.get("nyc.dep_class_depth_ft")["DEEP_CONTIGUOUS"] and ladder[0][1] == 0.0


def test_unavailable_and_none_classes_carry_no_depth_and_all_unavailable_is_missing_data():
    rows = [DepStormwater(scenario="LIMITED_CURRENT", flood_class="UNAVAILABLE"),
            DepStormwater(scenario="MODERATE_CURRENT", flood_class="NONE")]
    only = layer("PARTIAL", None).model_copy(update={"dep_stormwater": rows[:1]})
    assert nyc.data_missing(only) is True
    mixed = layer("PARTIAL", None).model_copy(update={"dep_stormwater": rows})
    assert nyc.data_missing(mixed) is False  # one known scenario is enough; Limited is unavailable by design
    assert all(d == 0.0 for _, d in nyc.scenario_ladder(mixed))


# --- the NRI tract total stays consistent ---
def test_the_reference_home_reproduces_the_tract_flood_total_across_the_three_flood_perils():
    ref = nyc.reference_layer()
    ref_hazard = PARCEL.public_hazard_layer
    t = cm.peril_terms(
        ref_hazard, PARCEL.private_verification_layer.model_copy(update={"elev_cert_verified": False, "cv_overhang_ft": 0.0}),
        state="NY", year_built=int(constants.get("nri.reference_year_built")), mitigations=cm.Mitigations(),
        base_rates=br.context_for(PARCEL, TRACT, nyc=True)[0], nyc_layer=ref,
    )
    by = {x.peril: x.n * x.s for x in t}
    total = by["FLOOD"] + by["PLUVIAL"] + by["SEWER_BACKUP"]
    assert total == pytest.approx(br.base_rates_for(TRACT).flood, rel=0.01)
    split = constants.get("nyc.ifld_split")
    inland = TRACT.ealb_usd["IFLD"] / TRACT.expb_usd["IFLD"]
    assert by["PLUVIAL"] == pytest.approx(split["PLUVIAL"] * inland, rel=0.01)
    assert by["SEWER_BACKUP"] == pytest.approx(split["SEWER_BACKUP"] * inland, rel=0.01)


def test_the_nyc_split_leaves_the_non_nyc_rates_alone():
    plain, nyc_rates = br.base_rates_for(TRACT), br.base_rates_for(TRACT, nyc=True)
    assert (plain.wildfire, plain.wind) == (nyc_rates.wildfire, nyc_rates.wind)
    assert nyc_rates.flood + nyc_rates.pluvial + nyc_rates.sewer == pytest.approx(plain.flood)
    assert plain.pluvial == plain.sewer == 0.0


# --- property tests ---
def test_a_deeper_dep_class_means_a_higher_pluvial_aal():
    nuisance, deep = terms(layer("PARTIAL", "NUISANCE"))["PLUVIAL"], terms(layer("PARTIAL", "DEEP_CONTIGUOUS"))["PLUVIAL"]
    none = terms(layer("PARTIAL", None))["PLUVIAL"]
    assert none.n * none.s == 0.0 < nuisance.n * nuisance.s < deep.n * deep.s


def test_more_mapped_scenarios_mean_a_higher_pluvial_aal():
    def with_scenarios(k):
        rows = [DepStormwater(scenario=s, flood_class="DEEP_CONTIGUOUS") for s in SCENARIOS[-k:]]
        return layer(dep=None).model_copy(update={"dep_stormwater": rows})

    values = [terms(with_scenarios(k))["PLUVIAL"] for k in (1, 2, 3)]
    assert values[0].n * values[0].s < values[1].n * values[1].s < values[2].n * values[2].s


@pytest.mark.parametrize("dep", ["NUISANCE", "DEEP_CONTIGUOUS"])
def test_a_basement_means_a_higher_severity(dep):
    s = {k: terms(layer(k, dep))["PLUVIAL"].s for k in ("NONE", "PARTIAL", "FULL")}
    assert s["NONE"] <= s["PARTIAL"] < s["FULL"]
    sewer = {k: terms(layer(k, dep))["SEWER_BACKUP"].s for k in ("NONE", "PARTIAL", "FULL")}
    assert sewer["NONE"] < sewer["PARTIAL"] < sewer["FULL"]


def test_a_basement_raises_the_mapped_zone_flood_severity_too():
    none, full = terms(layer("NONE"))["FLOOD"], terms(layer("FULL"))["FLOOD"]
    assert full.s > none.s


def test_a_backwater_valve_means_a_lower_sewer_backup_loss():
    bare, valved = terms(layer("FULL"))["SEWER_BACKUP"], terms(layer("FULL"), frozenset({"backwater_valve"}))["SEWER_BACKUP"]
    assert valved.n * valved.s == pytest.approx(bare.n * bare.s * (1 - constants.get("nyc.freq_reduction")["backwater_valve"]))


@pytest.mark.parametrize(
    ("dose", "peril"),
    [
        ("sump_pump_battery", "PLUVIAL"), ("dry_floodproofing", "PLUVIAL"), ("elevated_mechanicals", "PLUVIAL"),
        ("elevated_mechanicals", "SEWER_BACKUP"), ("flood_vents", "FLOOD"), ("dry_floodproofing", "FLOOD"),
    ],
)
def test_each_retrofit_lowers_the_loss_it_targets(dose, peril):
    deep = layer("FULL", "DEEP_CONTIGUOUS", sandy_inundated=True)
    bare, fitted = terms(deep)[peril], terms(deep, frozenset({dose}))[peril]
    assert fitted.n * fitted.s < bare.n * bare.s


def test_reversing_a_cellar_conversion_only_helps_a_flagged_cellar():
    flagged, unflagged = layer("FULL", dob_cellar_conversion_flag=True), layer("FULL")
    f0, f1 = terms(flagged)["SEWER_BACKUP"], terms(flagged, frozenset({"cellar_reversal"}))["SEWER_BACKUP"]
    u0, u1 = terms(unflagged)["SEWER_BACKUP"], terms(unflagged, frozenset({"cellar_reversal"}))["SEWER_BACKUP"]
    assert f1.s < f0.s and u1.s == u0.s


def test_sandy_inundation_raises_only_the_mapped_zone_flood_by_the_registered_relativity():
    base, sandy = terms(layer("FULL")), terms(layer("FULL", sandy_inundated=True))
    assert sandy["FLOOD"].n / base["FLOOD"].n == pytest.approx(math.exp(constants.get("nyc.sandy_relativity")))
    assert sandy["PLUVIAL"].n == base["PLUVIAL"].n


def test_311_density_and_catch_basins_move_the_sewer_backup_frequency():
    low, mid, high = (terms(layer(sewer_backup_311_500m_5y=n))["SEWER_BACKUP"].n for n in (5, 60, 400))
    assert low < mid < high
    few, many = (terms(layer(catch_basins_150m=n))["SEWER_BACKUP"].n for n in (2, 40))
    assert many < few
    assert terms(layer(sewer_backup_311_500m_5y=None))["SEWER_BACKUP"].n == pytest.approx(terms(layer(sewer_backup_311_500m_5y=mid_count()))["SEWER_BACKUP"].n, rel=0.05)


def mid_count():
    """The 311 count whose density equals the citywide level for 3,650 units: the neutral relativity."""
    return round(constants.get("nyc.sewer.ref_density_per_1000_units_yr") * 3.65 * 5)


def test_an_absurd_311_count_is_clamped():
    clamp = constants.get("nyc.sewer.relativity_clamp")[1]
    assert nyc.sewer_density_relativity(layer(sewer_backup_311_500m_5y=10**9, catch_basins_150m=None)) == clamp


def test_floodnet_history_raises_the_pluvial_frequency():
    quiet, wet = terms(layer(floodnet_events_500m_5y=0))["PLUVIAL"], terms(layer(floodnet_events_500m_5y=10))["PLUVIAL"]
    assert wet.n > quiet.n and wet.s == quiet.s


# --- scoring ---
def test_nyc_perils_appear_in_the_split_and_the_total_still_reconciles():
    out = run(layer("FULL", "DEEP_CONTIGUOUS"))
    a = out.actuarial_breakdown
    perils = {p.peril for p in a.peril_split}
    assert {"PLUVIAL", "SEWER_BACKUP", "FLOOD", "WIND_HAIL"} <= perils
    assert sum(p.peril_aal_usd for p in a.peril_split) == pytest.approx(a.expected_annual_loss_usd, abs=0.1)
    assert out.nyc is not None and out.nyc.bbl == "3000000001"


def test_a_parcel_without_the_nyc_layer_scores_as_before():
    assert run(None).actuarial_breakdown == simulate(PARCEL, [], nri=TRACT).actuarial_breakdown
    assert all(p.peril not in nyc.NYC_PERILS for p in run(None).actuarial_breakdown.peril_split)


def test_deep_flooding_with_a_full_basement_lowers_the_score():
    shallow, deep = run(layer("PARTIAL", "NUISANCE")), run(layer("FULL", "DEEP_CONTIGUOUS"))
    assert deep.actuarial_breakdown.resili_score < shallow.actuarial_breakdown.resili_score


def test_no_nyc_row_scores_negative_and_all_six_are_offered():
    out = run(layer("FULL", "DEEP_CONTIGUOUS", dob_cellar_conversion_flag=True, sandy_inundated=True))
    rows = {m.action_id: m for m in out.prescriptive_mitigations}
    assert set(ALL_NYC) <= set(rows)
    for action_id in ALL_NYC:
        assert rows[action_id].score_delta_pts >= 0 and rows[action_id].lcr_delta_bps <= 0
        assert rows[action_id].annual_premium_savings_usd > 0 and rows[action_id].payback_years > 0
    assert not any(rows[a].currently_applied for a in ALL_NYC)


def test_a_retrofit_selected_lowers_the_modeled_loss_and_is_marked_applied():
    base = run(layer("FULL", "DEEP_CONTIGUOUS"))
    fitted = run(layer("FULL", "DEEP_CONTIGUOUS"), ["NYC_DRY_FLOODPROOFING", "backwater_valve"])
    assert fitted.actuarial_breakdown.expected_annual_loss_usd < base.actuarial_breakdown.expected_annual_loss_usd
    rows = {m.action_id: m for m in fitted.prescriptive_mitigations}
    assert rows["NYC_DRY_FLOODPROOFING"].currently_applied and rows["NYC_BACKWATER_VALVE"].currently_applied


def test_nyc_actions_are_not_offered_without_the_layer_or_where_they_do_not_apply():
    assert not any(m.action_id in ALL_NYC for m in simulate(PARCEL, [], nri=TRACT).prescriptive_mitigations)
    ids = {m.action_id for m in run(layer("NONE", "NUISANCE")).prescriptive_mitigations}
    assert "NYC_SUMP_PUMP_BATTERY" not in ids and "NYC_ELEVATED_MECHANICALS" not in ids
    assert "NYC_CELLAR_CONVERSION_REVERSAL" not in {m.action_id for m in run(layer("FULL")).prescriptive_mitigations}


def test_a_nyc_retrofit_has_no_effect_on_the_filed_statutory_discount():
    a = run(layer("FULL", "DEEP_CONTIGUOUS")).actuarial_breakdown.statutory_discount_pct
    assert run(layer("FULL", "DEEP_CONTIGUOUS"), ["NYC_BACKWATER_VALVE"]).actuarial_breakdown.statutory_discount_pct == a


def test_unknown_basement_or_missing_dep_data_is_indicative_and_widens_the_band():
    known = run(layer("PARTIAL", "NUISANCE"))
    unknown = run(layer("UNKNOWN", "NUISANCE"))
    assert known.indicative_only is False and unknown.indicative_only is True
    assert nyc.basement_kind(layer("UNKNOWN"))[0] == constants.get("nyc.basement_unknown_default")
    assert run(layer("PARTIAL", None)).indicative_only is True
    width = lambda o: o.uncertainty.aal_p95_usd - o.uncertainty.aal_p05_usd
    same_kind = run(layer("PARTIAL", "NUISANCE").model_copy(update={"basement_type": "weird"}))
    assert same_kind.indicative_only is True and width(same_kind) > width(known)


def test_ground_elevation_and_bfe_stand_in_for_a_missing_freeboard():
    hazard = PARCEL.public_hazard_layer.model_copy(update={"freeboard_delta_h_ft": None, "bfe_ft_navd88": 10.0})
    parcel = PARCEL.model_copy(update={"public_hazard_layer": hazard})
    with_ground = simulate(parcel, [], nri=TRACT, nyc=layer("PARTIAL", ground_elevation_ft=14.0))
    without = simulate(parcel, [], nri=TRACT, nyc=layer("PARTIAL"))
    assert with_ground.indicative_only is False and without.indicative_only is True
    assert cm.effective_freeboard(hazard, layer(ground_elevation_ft=14.0)) == pytest.approx(5.0)


def test_attribution_is_additive_and_names_the_nyc_groups():
    out = run(layer("FULL", "DEEP_CONTIGUOUS"), ["NYC_DRY_FLOODPROOFING"])
    a = out.actuarial_breakdown
    total = sum(f.score_points for f in out.factor_contributions)
    assert total == pytest.approx(score_continuous(a.posterior_lcr) - score_continuous(a.tract_prior_lcr), abs=0.1)
    names = {f.factor for f in out.factor_contributions}
    assert any(n.startswith("NYC site") for n in names) and "NYC flood retrofits" in names


def test_the_copula_ties_pluvial_and_sewer_backup_to_one_rainfall_driver():
    rho = uncertainty.correlation(["FLOOD", "PLUVIAL", "SEWER_BACKUP"], "NY")
    assert rho[1, 2] == pytest.approx(constants.get("mc.nyc_rain_rho")) and rho[0, 1] == rho[0, 2]


def test_same_layer_on_two_tracts_scores_independently_and_nothing_is_stored():
    other = br.nri_from_tract(tract("rockaway_queens"), PARCEL.public_hazard_layer)
    a = simulate(PARCEL, [], nri=TRACT, nyc=layer("FULL", "DEEP_CONTIGUOUS"))
    b = simulate(PARCEL, [], nri=other, nyc=layer("FULL", "DEEP_CONTIGUOUS"))
    again = simulate(PARCEL, [], nri=TRACT, nyc=layer("FULL", "DEEP_CONTIGUOUS"))
    assert a.actuarial_breakdown.expected_annual_loss_usd != b.actuarial_breakdown.expected_annual_loss_usd
    assert a.actuarial_breakdown == again.actuarial_breakdown


def test_basement_curves_are_registered_with_their_source_and_flagged_as_priors():
    for key in ("fia_1floor_basement_a", "fia_2floor_basement_a", "fia_mod_2floor_basement_a", "usace_chicago_1story_basement"):
        const = constants.REGISTRY[f"nyc.ddf.{key}"]
        assert const.validated is False and "zenodo" in const.source_url and len(const.value) == 13


def test_the_evaluate_helper_accepts_installed_retrofits():
    r = PARCEL.model_copy(update={"nyc": layer("FULL", "DEEP_CONTIGUOUS")})
    v = r.private_verification_layer
    base = evaluate(r, v, nri=TRACT).raw_lcr
    assert evaluate(r, v, nri=TRACT, installed=frozenset({"dry_floodproofing"})).raw_lcr < base
    assert replace(cm.Mitigations(), backwater_valve=1.0).backwater_valve == 1.0


# --- the three NYC golden parcels (built from the recorded fixtures through the engine) ---
S2_ACTIONS = ["CA_ZONE0_1_CLEARANCE", "CA_EMBER_VENTS_EAVES", "CA_IBHS_WPH_CLASS_A_ROOF"]
NYC_GOLDEN = {"NYC_RED_HOOK": "3005130048", "NYC_HOLLIS": "4072730030", "NYC_ROCKAWAY": "4160790031"}
NYC_PINS = {"NYC_RED_HOOK": (835, 122.04), "NYC_HOLLIS": (829, 205.46), "NYC_ROCKAWAY": (821, 398.16)}


@pytest.mark.parametrize("key", NYC_GOLDEN)
def test_nyc_golden_parcel_scores_are_pinned_and_use_the_real_layer(key):
    g = load_golden()[key]
    a = g.actuarial_breakdown
    assert g.nyc is not None and g.nyc.bbl == NYC_GOLDEN[key] and g.parcel_identity.apn_uid == NYC_GOLDEN[key] + "0000"
    assert (a.resili_score, a.expected_annual_loss_usd) == (NYC_PINS[key][0], pytest.approx(NYC_PINS[key][1], abs=0.01))
    perils = {p.peril for p in a.peril_split}
    assert "SEWER_BACKUP" in perils and "PLUVIAL" in perils
    assert g.indicative_only is False and g.nyc.residential_units_500m


def test_the_existing_golden_scores_are_unchanged_by_the_nyc_model():
    g = load_golden()
    assert [g[k].actuarial_breakdown.resili_score for k in
            ("SCENARIO_1_LA_FLOOD", "SCENARIO_2_CA_WUI", "SCENARIO_3_ESCONDIDO_HITL", "SCENARIO_3_ESCONDIDO_HITL__UNPERMITTED")] == [
        823, 551, 850, 850]
    assert simulate(g["SCENARIO_2_CA_WUI"], S2_ACTIONS).actuarial_breakdown.resili_score == 661
    assert all(g[k].nyc is None for k in ("SCENARIO_1_LA_FLOOD", "SCENARIO_2_CA_WUI", "SCENARIO_3_ESCONDIDO_HITL"))


@pytest.mark.parametrize("key", NYC_GOLDEN)
def test_nyc_golden_toggles_lower_the_modeled_loss_offline(key):
    g = load_golden()[key]
    rows = {m.action_id for m in g.prescriptive_mitigations}
    assert {"NYC_BACKWATER_VALVE", "NYC_ELEVATED_MECHANICALS", "NYC_SUMP_PUMP_BATTERY", "NYC_DRY_FLOODPROOFING"} <= rows
    assert all(m.score_delta_pts >= 0 for m in g.prescriptive_mitigations)
    base = g.actuarial_breakdown.expected_annual_loss_usd
    fitted = simulate(g, ["NYC_BACKWATER_VALVE", "NYC_ELEVATED_MECHANICALS"]).actuarial_breakdown
    assert fitted.expected_annual_loss_usd < base and fitted.resili_score >= g.actuarial_breakdown.resili_score


def test_rockaway_is_coastal_exposed_and_has_flood_vents_the_others_do_not():
    g = load_golden()
    assert g["NYC_ROCKAWAY"].nyc.sandy_inundated is True
    assert "FLOOD" in {p.peril for p in g["NYC_ROCKAWAY"].actuarial_breakdown.peril_split}
    assert "NYC_FLOOD_VENTS" in {m.action_id for m in g["NYC_ROCKAWAY"].prescriptive_mitigations}
    assert "NYC_FLOOD_VENTS" not in {m.action_id for m in g["NYC_RED_HOOK"].prescriptive_mitigations}


def test_nyc_golden_simulations_cover_the_nyc_subsets():
    import json

    from app.fixtures import SIMULATIONS_PATH

    sims = json.loads(SIMULATIONS_PATH.read_text())
    table = sims["NYC_HOLLIS"]
    assert "" in table and "NYC_BACKWATER_VALVE" in table
    assert table["NYC_BACKWATER_VALVE"]["expected_annual_loss_usd"] < table[""]["expected_annual_loss_usd"]


def test_the_score_endpoint_serves_the_nyc_scenarios():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        body = client.post("/v1/parcel/score", json={"scenario_id": "NYC_RED_HOOK"}).json()
        out = client.post(
            "/v1/parcel/simulate-mitigation",
            json={"apn_uid": "30051300480000", "action_ids": ["NYC_BACKWATER_VALVE"]},
        ).json()
    assert body["nyc"]["bbl"] == "3005130048" and body["actuarial_breakdown"]["resili_score"] == 835
    assert out["actuarial_breakdown"]["expected_annual_loss_usd"] < body["actuarial_breakdown"]["expected_annual_loss_usd"]


def test_the_nyc_split_with_unequal_ifld_and_cfld_exposures_keeps_flood_non_negative_and_the_total():
    odd = br.NriRates("x", 1e9, {"IFLD": 1e6, "CFLD": 1e5}, {"IFLD": 1e8, "CFLD": 1e9})
    plain, split = br.base_rates_for(odd), br.base_rates_for(odd, nyc=True)
    assert split.flood >= 0 and split.pluvial >= 0 and split.sewer >= 0
    assert split.flood + split.pluvial + split.sewer == pytest.approx(plain.flood)
    assert br.base_rates_for(odd, "all", nyc=True).flood >= 0
