"""Wildfire validation against the committed DINS sample (no network)."""

import json
import math

import numpy as np
import pytest

from validation import wildfire_model as wm
from validation import wildfire_run as wr


@pytest.fixture(scope="module")
def result() -> dict:
    return wr.run()


def test_auc_matches_hand_computed_values_including_ties():
    y = np.array([0, 0, 1, 1])
    assert wm.auc(np.array([1.0, 2.0, 3.0, 4.0]), y) == 1.0
    assert wm.auc(np.array([4.0, 3.0, 2.0, 1.0]), y) == 0.0
    assert wm.auc(np.array([1.0, 1.0, 1.0, 1.0]), y) == 0.5
    assert wm.auc(np.array([1.0, 2.0, 2.0, 3.0]), y) == pytest.approx(0.875)


def test_logit_recovers_known_coefficients():
    rng = np.random.default_rng(7)
    x = np.column_stack([np.ones(20_000), rng.normal(size=20_000)])
    y = (rng.random(20_000) < wm._sigmoid(x @ np.array([-0.5, 1.2]))).astype(float)
    fit = wm.fit_logit(x, y)
    assert fit.beta == pytest.approx([-0.5, 1.2], abs=0.08)
    assert all(abs(b - t) < 3 * s for b, t, s in zip(fit.beta, [-0.5, 1.2], fit.se))


def test_mantel_haenszel_ratio_on_a_two_fire_table():
    def home(fire, destroyed, favourable):
        return wm.Home(fire, destroyed, {f: favourable for f in wm.BINARY}, None)

    homes = (
        [home("a", i < 10, 1) for i in range(100)] + [home("a", i < 20, 0) for i in range(100)]
        + [home("b", i < 30, 1) for i in range(100)] + [home("b", i < 60, 0) for i in range(100)]
    )  # fmt: skip
    assert wm.mh_risk_ratio(homes, "roof_class_a")["rr"] == pytest.approx(0.5)


def test_engine_relativities_come_from_the_constants():
    d, loss = wm.engine_relativity({})
    assert d == pytest.approx(1.0) and loss == pytest.approx(1.0)
    vent_d, vent_loss = wm.engine_relativity({"ember_vents": 1.0})
    assert 0 < vent_d < 1 and 0 < vent_loss < 1
    # Adding a mitigation never raises modelled risk.
    both = wm.engine_relativity({"ember_vents": 1.0, "enclosed_eaves": 1.0})
    assert both[0] < vent_d and both[1] < vent_loss


def test_sample_is_small_and_complete():
    homes = wm.load_homes()
    assert wm.DATA.stat().st_size < 2_000_000
    assert len({h.fire for h in homes}) >= 25
    population = json.loads(wm.POPULATION.read_text())
    assert {h.fire for h in homes} <= {k for k, v in population.items() if v["in_sample"]}
    assert all(population[k]["inspected"] >= 300 for k in {h.fire for h in homes})


def test_lofo_has_one_row_per_fire_and_never_trains_on_the_held_out_fire(result):
    fires = {h.fire for h in wm.load_homes()}
    assert {r["fire"] for r in result["lofo"]} == fires
    assert wr.HOLDOUT_FIRE not in result["proposal"]["train_fires"]
    assert "Palisades" not in wr.EXAMPLE_TRAIN


def test_unknown_levels_are_not_scored():
    homes = wm.load_homes()
    model, _ = wr._fit(homes)
    known = next(h for h in homes if all(v is not None for v in h.flags.values()) and h.era)
    blank = wm.Home(known.fire, known.destroyed, {f: None for f in wm.BINARY}, None)
    assert wr._fitted_lp(model, [blank])[0] == 0.0


def test_proposal_only_contains_protective_features_with_ci_below_one(result):
    proposal = result["proposal"]
    meta = {"train_fires", "holdout_fire", "holdout_auc", "current_holdout_auc", "fit_date", "method"}
    features = {k: v for k, v in proposal.items() if k not in meta}
    assert features, "the Palisades holdout is expected to beat the current model"
    for v in features.values():
        assert v["ci_high"] < 1 and v["ci_low"] < v["odds_ratio"] < v["ci_high"]
    assert proposal["holdout_auc"] > proposal["current_holdout_auc"]
    assert "noncombustible_siding" not in features  # OR above 1: a recording artifact, not a finding


def test_committed_results_match_a_fresh_run(result):
    summary = json.loads((wr.RESULTS / "wildfire_summary.json").read_text())
    assert summary["palisades_holdout"]["auc_fitted"] == pytest.approx(result["palisades_holdout"]["auc_fitted"], abs=1e-4)
    assert summary["palisades_holdout"]["auc_current"] == pytest.approx(result["palisades_holdout"]["auc_current"], abs=1e-4)
    committed = json.loads((wr.FITTED / "wildfire_relativities.json").read_text())
    assert committed["holdout_auc"] == pytest.approx(result["proposal"]["holdout_auc"], abs=1e-4)


def test_no_image_features_are_invented(result):
    rows = {r["feature"]: r for r in result["features"]}
    assert rows["roof_class_a"]["observed_rr"] < 1  # Class A roofs lose less, as modelled
    assert math.isnan(rows["noncombustible_siding"]["observed_rr"]) is False
    assert rows["noncombustible_siding"]["modelled_rr_destroyed"] is None  # not an engine feature
