"""Flood validation: the statistics, the split, and the full report on the committed claims sample (no network)."""

import json
import math
import os

import numpy as np
import pytest

from app.actuarial.base_rates import NriRates
from app.actuarial.compound_model import ddf
from validation import flood_backtest as fb
from validation import flood_ranking as fr
from validation import flood_report as rep

SAMPLE = rep.SAMPLE


def claims(depth, ratio, state="LA", event="", year=2016, date="2016-08-13", basement=0):
    n = len(ratio)

    def col(v):
        return np.array(v if isinstance(v, list) else [v] * n)

    return fb.Claims(np.array(depth, dtype=float), np.array(ratio, dtype=float), col(state), col(event),
                     col(year), col(date), col(basement), col("22000000000"), col("AE"))


# ---- statistics ----

def test_pava_pools_violators():
    assert list(fb.pava(np.array([1, 3, 2, 4.0]), np.ones(4))) == [1, 2.5, 2.5, 4]
    assert list(fb.pava(np.array([1, 2, 3.0]), np.ones(3))) == [1, 2, 3]
    assert list(fb.pava(np.array([3, 1.0]), np.array([1.0, 3.0]))) == [1.5, 1.5]


def test_isotonic_fit_is_monotone_and_recovers_a_line():
    rng = np.random.default_rng(1)
    depth = rng.uniform(0, 10, 4000)
    ratio = np.clip(0.05 * depth + rng.normal(0, 0.1, 4000), 0, 1)
    curve = fb.fit_isotonic(depth, ratio, np.arange(0, 10.1, 1.0))
    assert np.all(np.diff(curve.values) >= -1e-12)
    assert abs(curve(np.array([5.0]))[0] - 0.25) < 0.04


def test_spearman_known_values():
    a = np.array([1.0, 2, 3, 4, 5])
    assert fr.spearman(a, a * 10) == pytest.approx(1.0)
    assert fr.spearman(a, -a) == pytest.approx(-1.0)
    assert fr.spearman(a, np.array([1.0, 1, 1, 1, 1])) != fr.spearman(a, a)  # constant gives nan


def test_gini_and_deciles():
    rng = np.random.default_rng(2)
    pred = rng.uniform(0.001, 0.01, 400)
    expo = rng.uniform(1, 5, 400)
    informative = rng.poisson(pred * expo * 4000).astype(float)
    noise = rng.poisson(pred.mean() * expo * 4000).astype(float)
    assert fr.gini(pred, informative, expo) > 0.1
    assert abs(fr.gini(pred, noise, expo)) < 0.1
    table = fr.decile_table(pred, informative, expo)
    assert [r["decile"] for r in table] == list(range(1, 11))
    assert table[-1]["claims_per_m_per_yr"] > table[0]["claims_per_m_per_yr"]
    assert sum(r["expected_claims"] for r in table) == pytest.approx(informative.sum())


def test_bootstrap_ci_excludes_zero_only_for_a_real_difference():
    clusters = np.repeat(np.arange(20), 50)
    _, lo, hi = fb.cluster_bootstrap_ci(np.full(1000, -0.02), clusters, reps=300)
    assert hi < 0
    rng = np.random.default_rng(3)
    _, lo, hi = fb.cluster_bootstrap_ci(rng.normal(0, 0.05, 1000), clusters, reps=300)
    assert lo < 0 < hi


# ---- curves ----

def test_engine_curves_are_read_unchanged():
    d = np.array([0.0, 1.0, 3.0, 6.5])
    assert list(fb.hazus_129(d)) == [ddf(float(x)) for x in d]
    assert fb.hazus_129(np.array([0.0]))[0] == pytest.approx(0.13)
    assert fb.fia_105(np.array([0.0]))[0] == pytest.approx(0.18)
    assert fb.fia_105(np.array([-5.0]))[0] == 0.0


def test_bucket_table_counts_and_means():
    c = claims([0.2, 0.3, 1.5, 9.0], [0.1, 0.3, 0.5, 0.9])
    rows = fb.bucket_table(c, {"hazus129": fb.hazus_129(c.depth_ft)})
    assert sum(r["n"] for r in rows) == 4
    first = rows[0]
    assert first["n"] == 2 and first["observed_mean"] == pytest.approx(0.2)
    assert math.isnan(rows[4]["observed_mean"])  # empty bucket
    assert first["hazus129_bias"] == pytest.approx(first["hazus129_mean"] - 0.2)


# ---- split and leave-one-event-out ----

def test_holdout_is_by_region_and_event_never_random_rows():
    c = claims([1, 1, 1, 1], [0.1] * 4, state=["TX", "NY", "NJ", "LA"],
               event=["", "", "", "Hurricane Ida"])
    assert list(fb.is_holdout(c)) == [False, True, True, True]


def test_held_out_event_never_reaches_training():
    # Event rows have ratio 1.0 and everything else 0. If the event leaked into training the fitted curve
    # for the held-out event would be well above zero.
    n = 300
    c = claims([2.0] * n, [0.0] * n, state="TX", date="2017-01-01")
    ev = claims([2.0] * 60, [1.0] * 60, state="TX", date="2017-08-25")
    both = fb.Claims(**{k: np.concatenate([getattr(c, k), getattr(ev, k)]) for k in c.__dict__})
    rows = rep.leave_one_event_out(both)
    harvey = next(r for r in rows if r["event"] == "Harvey 2017")
    assert harvey["n"] == 60 and harvey["observed_mean"] == 1.0
    assert harvey["fitted_mean"] == pytest.approx(0.0, abs=1e-9)
    assert harvey["fitted_mae"] == pytest.approx(1.0)


# ---- the report on the committed sample ----

@pytest.fixture(scope="module")
def report(tmp_path_factory):
    out = tmp_path_factory.mktemp("flood")
    result = rep.run_report(SAMPLE, out / "results", out / "fitted", source="sample", fetched="2026-10-17")
    return result, out


def test_sample_is_small_and_covers_the_states():
    assert SAMPLE.stat().st_size < 2_000_000
    allc = fb.read_claims(SAMPLE)
    assert {"LA", "TX", "FL", "NJ", "NY"} <= set(allc.state)


def test_report_writes_all_outputs(report):
    _, out = report
    for name in ("flood_severity_buckets.csv", "flood_holdout_buckets.csv", "flood_events.csv", "flood_summary.json"):
        assert (out / "results" / name).exists()
    summary = json.loads((out / "results" / "flood_summary.json").read_text())
    assert summary["verdict"] in {"adopt", "keep Hazus"}
    assert summary["split"]["train_n"] > 0 and summary["split"]["holdout_n"] > 0
    assert summary["split"]["train_n"] + summary["split"]["holdout_n"] == summary["claims_no_basement"]


def test_adopt_rule_is_enforced(report):
    result, out = report
    ci = result["mae_diff_fitted_minus_hazus"]
    proposal = out / "fitted" / "flood_ddf.json"
    if result["verdict"] == "adopt":
        assert ci["ci_hi"] < 0
        doc = json.loads(proposal.read_text())
        assert set(doc) >= {"knots", "values", "train_n", "holdout_n", "holdout_mae", "hazus_holdout_mae",
                            "fit_date", "method"}
        assert doc["holdout_mae"] < doc["hazus_holdout_mae"]
        assert all(b >= a for a, b in zip(doc["values"], doc["values"][1:], strict=False))
    else:
        assert ci["ci_hi"] >= 0 or result["holdout"]["n"] == 0
        assert not proposal.exists()


def test_event_table_has_every_event(report):
    result, _ = report
    assert [r["event"] for r in result["events"]] == list(fb.EVENTS)


def test_training_excludes_the_holdout(report):
    _ = report
    allc = fb.read_claims(SAMPLE)
    c0 = allc.take(allc.basement == 0)
    train = c0.take(~fb.is_holdout(c0))
    assert not np.isin(train.state, fb.HOLDOUT_STATES).any()
    assert not (train.event == fb.HOLDOUT_EVENT).any()


# ---- ranking: the model side is the NRI rate by construction ----

def test_reference_home_flood_lcr_equals_the_nri_rate():
    nri = NriRates("22051000100", 5e8, {"IFLD": 2.0e6, "CFLD": 1.0e6}, {"IFLD": 2.5e8, "CFLD": 1.0e8})
    tract = fr.Tract("22051000100", "LA", nri)
    assert fr.model_flood_lcr(tract) == pytest.approx(nri.loss_rate("FLOOD"), rel=1e-6)


# ---- live (network) ----

@pytest.mark.skipif(os.environ.get("RS_LIVE") != "1", reason="set RS_LIVE=1 to hit OpenFEMA and the NRI service")
def test_live_fetch_matches_the_documented_fields():
    import httpx

    from validation import flood_fetch as ff

    with httpx.Client() as client:
        rows = ff.fetch_rows(client, "state eq 'NJ' and yearOfLoss eq 2012 and occupancyType eq 1 "
                                     "and numberOfFloorsInTheInsuredBuilding eq 1 and waterDepth ge 0 "
                                     "and buildingPropertyValue ge 20000 and basementEnclosureCrawlspaceType eq 0")
    assert rows and set(ff.FIELDS) >= set(rows[0])
