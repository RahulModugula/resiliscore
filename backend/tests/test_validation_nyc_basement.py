"""NYC basement validation: the statistics and the committed sample (no network)."""

import json

import numpy as np
import pytest

from app.actuarial import constants
from app.actuarial.compound_model import ddf
from validation import nyc_basement_run as run

CLAIMS = run.load(run.SAMPLE)


def tiny(event, depth, ratio, tract="t"):
    n = len(depth)
    return run.Claims(np.array([event] * n), np.array(depth, float), np.array(ratio, float), np.array([tract] * n))


def test_the_sample_holds_both_events_and_the_committed_counts():
    assert (CLAIMS.event == "Ida 2021 NY/NJ").sum() == 2572 and (CLAIMS.event == "Sandy 2012").sum() == 5000
    assert CLAIMS.ratio.max() <= 1.0 and CLAIMS.depth_ft.min() >= 0.0


def test_isotonic_is_non_decreasing_and_exact_on_monotone_data():
    x, y = np.array([0.0, 1.0, 2.0, 3.0]), np.array([0.1, 0.3, 0.2, 0.6])
    fit = run.isotonic(x, y)(np.array([0.0, 1.0, 2.0, 3.0]))
    assert np.all(np.diff(fit) >= -1e-12) and fit[0] == pytest.approx(0.1) and fit[1] == pytest.approx(0.25)
    assert run.isotonic(x, np.array([0.1, 0.2, 0.3, 0.4]))(x) == pytest.approx([0.1, 0.2, 0.3, 0.4])


def test_the_scale_fit_recovers_a_known_scale():
    depth = np.linspace(0.0, 8.0, 400)
    truth = np.minimum(1.0, 0.8 * np.array([ddf(d) for d in depth]))
    claims = tiny("Sandy 2012", depth, truth)
    everything = np.ones(len(depth), dtype=bool)
    assert run.fit_scale(claims, everything, "mse") == pytest.approx(0.8, abs=0.011)
    assert run.fit_scale(claims, everything, "mae") == pytest.approx(0.8, abs=0.011)


def test_a_paired_interval_is_negative_for_a_better_model_and_zero_against_itself():
    rng = np.random.default_rng(1)
    truth = rng.uniform(0, 1, 400)
    claims = run.Claims(np.array(["a"] * 400), np.zeros(400), truth, np.array([f"t{i % 40}" for i in range(400)]))
    test = np.ones(400, dtype=bool)
    better, worse = truth + rng.normal(0, 0.02, 400), truth + rng.normal(0, 0.3, 400)
    diff, _lo, hi = run.paired_interval(better, worse, claims, test, "mse")
    assert diff < 0 and hi < 0
    assert run.paired_interval(worse, worse, claims, test, "mae") == (0.0, 0.0, 0.0)


@pytest.fixture(scope="module")
def result():
    return run.run(CLAIMS)


def test_both_directions_are_run_and_hazus_129_is_the_reference(result):
    assert [(d["train"], d["test"]) for d in result["directions"]] == [
        ("Sandy 2012", "Ida 2021 NY/NJ"), ("Ida 2021 NY/NJ", "Sandy 2012")
    ]
    for d in result["directions"]:
        ref = next(r for r in d["rows"] if r["candidate"] == "Hazus 129")
        assert ref["mse_vs_hazus"] == {"diff": 0.0, "lo": 0.0, "hi": 0.0}


def test_every_structure_curve_plus_finish_loses_to_hazus_129_in_both_directions(result):
    for d in result["directions"]:
        rows = [r for r in d["rows"] if "+" in r["candidate"] and "first-draft" in r["candidate"]]
        assert len(rows) == 4
        for r in rows:
            assert r["mse_vs_hazus"]["lo"] > 0 and r["bias"] < -0.1, r["candidate"]
    assert all(v == {"mae": "keep Hazus 129", "mse": "keep Hazus 129"}
               for k, v in result["verdicts"].items() if "+" in k)


def test_a_squared_error_scale_passes_the_absolute_error_rule(result):
    assert result["verdicts"]["Hazus 129 x k (mse fit)"]["mae"] == "adopt"
    assert 0.8 < result["pooled_k"]["mse"] < 1.0 and result["pooled_k"]["mae"] < result["pooled_k"]["mse"]


def test_the_registered_scale_matches_the_validated_scale_and_cites_the_doc():
    const = constants.REGISTRY["nyc.basement_scale"]
    assert const.validated is True and const.source_url == "docs/validation/nyc_basement.md"
    assert const.value == pytest.approx(0.91, abs=0.005)


def test_the_committed_full_results_agree_with_the_registry():
    full = json.loads((run.RESULTS / "nyc_basement.json").read_text())
    assert full["pooled_k"]["mse"] == pytest.approx(constants.get("nyc.basement_scale"), abs=0.005)
    assert [(d["n_train"], d["n_test"]) for d in full["directions"]] == [(27014, 2572), (2572, 27014)]
    assert full["verdicts"]["Hazus 129 x k (mse fit)"] == {"mae": "adopt", "mse": "keep Hazus 129"}
