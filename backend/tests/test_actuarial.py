"""Actuarial core: golden reproduction, simulate, credibility, score map, HITL, latency."""

import itertools
import json
import math
import time
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from app.actuarial import compliance
from app.actuarial import compound_model as cm
from app.actuarial.credibility import K, credibility, posterior_lcr
from app.actuarial.optimizer import ACTIONS, evaluate, premium_discount, simulate
from app.actuarial.score_map import score, score_continuous, spec_sigmoid, tier
from app.models.schemas import ParcelScoreResponse

CONTRACTS = Path(__file__).resolve().parents[2] / "contracts"
GOLDEN = json.loads((CONTRACTS / "golden_scenarios.json").read_text())
SCHEMA = json.loads((CONTRACTS / "parcel_score_schema.json").read_text())
S1, S2, S3 = "SCENARIO_1_LA_FLOOD", "SCENARIO_2_CA_WUI", "SCENARIO_3_ESCONDIDO_HITL"
S3_BAD = "SCENARIO_3_ESCONDIDO_HITL__UNPERMITTED"
S2_ALL = ["CA_ZONE0_1_CLEARANCE", "CA_EMBER_VENTS_EAVES", "CA_IBHS_WPH_CLASS_A_ROOF"]


def load(key: str) -> ParcelScoreResponse:
    return ParcelScoreResponse.model_validate(GOLDEN[key])


@pytest.mark.parametrize("key", [S1, S2, S3])
def test_golden_reproduction(key):
    r = load(key)
    gold = r.actuarial_breakdown
    ev = evaluate(r, r.private_verification_layer)
    assert abs(ev.posterior_lcr - gold.posterior_lcr) <= 1e-4  # 1 bp
    assert abs(ev.raw_lcr - gold.parcel_raw_lcr) <= 5e-5
    assert abs(ev.credibility.z - gold.credibility_weight_z) <= 0.01
    assert abs(ev.score - gold.resili_score) <= 1
    assert ev.tier == gold.underwriting_tier
    assert abs(score(gold.tract_prior_lcr) - gold.baseline_macro_score) <= 1


def test_simulate_baseline_matches_golden_headline_numbers():
    out = simulate(load(S1), [])
    b = out.actuarial_breakdown
    assert (b.resili_score, b.underwriting_tier) == (765, "TIER_1_AUTO_BIND")
    assert b.statutory_discount_pct == 38.0
    assert b.annual_discounted_premium_usd == 2604.0
    assert b.baseline_macro_score == 430


def test_s2_with_all_three_mitigations_scores_630_tier_2():
    out = simulate(load(S2), S2_ALL)
    assert out.actuarial_breakdown.resili_score == 630
    assert out.actuarial_breakdown.underwriting_tier == "TIER_2_CONDITIONAL"
    assert out.actuarial_breakdown.credibility_weight_z > load(S2).actuarial_breakdown.credibility_weight_z
    assert all(m.currently_applied for m in out.prescriptive_mitigations if m.action_id in S2_ALL)


def test_spec_aliases_equal_canonical_ids():
    by_alias = simulate(load(S2), ["zone0_clear", "ember_vents_eaves", "ibhs_wph_class_a_roof"])
    assert by_alias.actuarial_breakdown == simulate(load(S2), S2_ALL).actuarial_breakdown


def test_unknown_action_is_rejected():
    with pytest.raises(ValueError, match="unknown mitigation"):
        simulate(load(S2), ["NOT_AN_ACTION"])


def test_each_selected_action_improves_s2():
    base = simulate(load(S2), []).actuarial_breakdown.resili_score
    for action in (a.action_id for a in ACTIONS if a.action_id in S2_ALL):
        assert simulate(load(S2), [action]).actuarial_breakdown.resili_score > base


def test_s3_unpermitted_fires_hitl_02_and_base_s3_does_not():
    bad = simulate(load(S3_BAD), []).hitl_status
    assert bad.escalated and bad.trigger_code == "HITL_TRIGGER_02_UNPERMITTED_ADDITION"
    assert bad.trigger_reason == GOLDEN[S3_BAD]["hitl_status"]["trigger_reason"]
    assert bad.recommended_underwriter_action == GOLDEN[S3_BAD]["hitl_status"]["recommended_underwriter_action"]
    assert not simulate(load(S3), []).hitl_status.escalated


def test_la_fortified_grant_payback_and_resale():
    r = load(S1)
    row = next(m for m in simulate(r, []).prescriptive_mitigations if m.action_id == "LA_FORTIFIED_ROOF")
    assert (row.gross_capex_usd, row.grant_subsidy_usd, row.net_capex_usd) == (18000.0, 10000.0, 8000.0)
    assert row.resale_value_bump_pct == 6.8
    assert row.currently_applied
    assert row.payback_years == pytest.approx(row.net_capex_usd / row.annual_premium_savings_usd, abs=0.01)
    ca = simulate(load(S2), [])
    assert all(m.grant_subsidy_usd == 0 for m in ca.prescriptive_mitigations)


def test_discount_caps_and_flood_excluded_from_homeowners_premium():
    r = load(S3)
    assert 0.20 < premium_discount(r, r.private_verification_layer) <= 0.30  # wildfire cap 30%, wind 12.4%
    s1 = load(S1)
    assert premium_discount(s1, s1.private_verification_layer) == 0.38  # wind only; flood is NFIP
    s2 = load(S2)
    assert premium_discount(s2, s2.private_verification_layer) == 0.0


def test_simulate_output_validates_against_the_contract():
    validator = Draft202012Validator(SCHEMA)
    for key, ids in ((S1, []), (S2, S2_ALL), (S3_BAD, [])):
        out = simulate(load(key), ids)
        validator.validate(json.loads(out.model_dump_json()))
        assert out.regulatory_compliance.monotonicity_verified
        assert out.regulatory_compliance.ny_dfs_cl7_ecdis_free


def test_simulate_runs_under_50ms():
    r = load(S2)
    simulate(r, S2_ALL)  # warm-up
    best = min(_timed(r) for _ in range(10))
    assert best < 50.0, best


def _timed(r) -> float:
    t0 = time.perf_counter()
    simulate(r, S2_ALL)
    return (time.perf_counter() - t0) * 1000


# --- score map ---
@pytest.mark.parametrize(
    ("bps", "expected"), [(185, 430), (24, 765), (245, 385), (18, 815), (1, 850), (1000, 300), (0.1, 850), (5000, 300)]
)
def test_score_map_anchors_and_clamps(bps, expected):
    assert score(bps / 1e4) == expected


def test_score_map_is_strictly_decreasing_between_pins():
    lcrs = [math.exp(math.log(1e-4) + i * (math.log(0.1) - math.log(1e-4)) / 400) for i in range(401)]
    values = [score_continuous(x) for x in lcrs]
    assert all(a > b for a, b in itertools.pairwise(values))


@pytest.mark.parametrize(
    ("s", "expected"),
    [(850, "TIER_1_AUTO_BIND"), (720, "TIER_1_AUTO_BIND"), (719, "TIER_2_CONDITIONAL"), (580, "TIER_2_CONDITIONAL"),
     (579, "TIER_3_DECLINE_ESCALATE"), (300, "TIER_3_DECLINE_ESCALATE")],
)
def test_tier_bands(s, expected):
    assert tier(s) == expected


def test_spec_sigmoid_is_kept_but_disagrees_with_golden():
    assert spec_sigmoid(0.0185) == 460  # D1: reference only; the golden scenario says 430
    assert score(0.0185) == 430


# --- credibility ---
def test_credibility_weights_are_exposed_and_sum_to_w():
    v = load(S3).private_verification_layer
    c = credibility(v)
    assert set(c.channel_weights) == {"lidar_1m", "aerial_cv", "elevation_certificate", "ibhs_registry", "iot_smart_valve"}
    assert c.w == pytest.approx(sum(c.channel_weights.values()))
    assert c.z == pytest.approx(c.w / (c.w + K))
    assert 0 <= c.z <= 1


def test_posterior_is_the_credibility_weighted_blend():
    assert posterior_lcr(0.01, 0.03, 0.75) == pytest.approx(0.0150)


# --- compound model ---
def test_ddf_is_zero_at_floor_and_increasing():
    assert cm.ddf(-2.0) == 0.0 and cm.ddf(-5.0) == 0.0
    depths = [-1.9 + 0.1 * i for i in range(200)]
    assert all(cm.ddf(a) < cm.ddf(b) for a, b in itertools.pairwise(depths))
    assert 0.09 < cm.ddf(0.0) < 0.11  # see module docstring: spec constants give ~10.2%, not 13.4%


def test_tgpd_mean_lies_inside_the_truncation_interval():
    for sigma in (0.05, 0.15, 0.4):
        assert 0 < cm.tgpd_mean(sigma, 0.25, 0.5) < 0.5


def test_peril_split_rows_are_consistent_and_dollar_valued():
    r = load(S2)
    rows = cm.peril_split(
        r.public_hazard_layer, r.private_verification_layer, r.parcel_identity.rcv_usd,
        state="CA", year_built=r.parcel_identity.year_built, firewise=False,
    )
    assert [x.peril for x in rows] == ["WILDFIRE", "WIND_HAIL"]
    for x in rows:
        assert x.peril_aal_usd == pytest.approx(x.expected_freq_n * x.expected_sev_s, rel=1e-3)


# --- HITL ---
def _hitl(**kw):
    base = {"rcv_usd": 500_000.0, "cv_confidence": 0.95, "unpermitted_footprint_delta_sqft": 0.0, "resili_score": 700}
    return compliance.hitl_status(**{**base, **kw})


@pytest.mark.parametrize(
    ("override", "code"),
    [
        ({"cv_confidence": 0.84}, "HITL_TRIGGER_01_SENSOR_DIVERGENCE"),
        ({"delta_z_lidar_ft": 5.0, "delta_z_cert_ft": 3.4}, "HITL_TRIGGER_01_SENSOR_DIVERGENCE"),
        ({"unpermitted_footprint_delta_sqft": 151.0}, "HITL_TRIGGER_02_UNPERMITTED_ADDITION"),
        ({"rcv_usd": 5_000_001.0}, "HITL_TRIGGER_03_HIGH_TIV"),
        ({"resili_score": 570}, "HITL_TRIGGER_04_BOUNDARY_CONFLICT"),
        ({"resili_score": 590}, "HITL_TRIGGER_04_BOUNDARY_CONFLICT"),
    ],
)
def test_hitl_triggers_fire(override, code):
    status = _hitl(**override)
    assert status.escalated and status.trigger_code == code
    assert status.trigger_reason and status.recommended_underwriter_action


@pytest.mark.parametrize(
    "override",
    [{}, {"cv_confidence": 0.85}, {"delta_z_lidar_ft": 5.0, "delta_z_cert_ft": 3.5},
     {"unpermitted_footprint_delta_sqft": 150.0}, {"rcv_usd": 5_000_000.0}, {"resili_score": 569},
     {"resili_score": 591}],
)
def test_hitl_does_not_fire_at_the_limits(override):
    status = _hitl(**override)
    assert not status.escalated and status.trigger_code == "NONE"
