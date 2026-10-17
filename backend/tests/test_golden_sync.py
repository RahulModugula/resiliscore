"""The golden file must equal the engine's output; regenerate with scripts/regen_golden.py."""

import json

import pytest
from jsonschema import Draft202012Validator

from app.actuarial.optimizer import simulate
from app.fixtures import (
    GOLDEN_PATH,
    SIMULATIONS_PATH,
    SIMULATIONS_SCHEMA_PATH,
    reconcile,
    simulation_table,
    subset_key,
)
from app.models.schemas import ParcelScoreResponse

RAW = json.loads(GOLDEN_PATH.read_text())


@pytest.mark.parametrize("key", RAW)
def test_golden_equals_engine_output(key):
    assert reconcile(RAW[key]) == RAW[key], "run: uv run --directory backend python scripts/regen_golden.py"


def test_headline_pins_hold():
    ab = {k: v["actuarial_breakdown"] for k, v in RAW.items()}
    s1 = ab["SCENARIO_1_LA_FLOOD"]
    assert (s1["baseline_macro_score"], s1["resili_score"], s1["statutory_discount_pct"]) == (430, 765, 38.0)
    assert s1["annual_discounted_premium_usd"] == 2604.0
    assert (ab["SCENARIO_2_CA_WUI"]["resili_score"], ab["SCENARIO_3_ESCONDIDO_HITL"]["resili_score"]) == (385, 815)
    assert ab["SCENARIO_3_ESCONDIDO_HITL__UNPERMITTED"]["resili_score"] == 780
    assert (
        RAW["SCENARIO_3_ESCONDIDO_HITL__UNPERMITTED"]["hitl_status"]["trigger_code"]
        == "HITL_TRIGGER_02_UNPERMITTED_ADDITION"
    )
    assert all(v["regulatory_compliance"]["dataset_vintages"]["OpenFEMA"] == "NfipClaims_v3" for v in RAW.values())


# --- golden_simulations.json ---
SIMS = json.loads(SIMULATIONS_PATH.read_text())
GOLDEN_THREE = ["CA_ZONE0_1_CLEARANCE", "CA_EMBER_VENTS_EAVES", "CA_IBHS_WPH_CLASS_A_ROOF"]


def test_simulations_file_equals_engine_output():
    assert SIMS == {k: simulation_table(v) for k, v in RAW.items()}, "run scripts/regen_golden.py"


def test_every_entry_equals_simulate_for_that_subset():
    for key, table in SIMS.items():
        base = ParcelScoreResponse.model_validate(RAW[key])
        for subset, entry in table.items():
            ids = subset.split("+") if subset else []
            b = simulate(base, ids).actuarial_breakdown
            assert (entry["resili_score"], entry["underwriting_tier"]) == (b.resili_score, b.underwriting_tier)
            assert entry["posterior_lcr"] == b.posterior_lcr
            assert entry["total_annual_savings_usd"] == round(
                b.annual_base_premium_usd - b.annual_discounted_premium_usd, 2
            )


def test_simulations_cover_every_subset_and_validate():
    Draft202012Validator(json.loads(SIMULATIONS_SCHEMA_PATH.read_text())).validate(SIMS)
    assert set(SIMS) == set(RAW)
    assert len(SIMS["SCENARIO_2_CA_WUI"]) == 2**5
    assert "" in SIMS["SCENARIO_1_LA_FLOOD"]
    for table in SIMS.values():
        assert all(subset == subset_key(subset.split("+") if subset else []) for subset in table)


def test_s2_three_golden_actions_entry():
    entry = SIMS["SCENARIO_2_CA_WUI"][subset_key(GOLDEN_THREE)]
    assert (entry["resili_score"], entry["underwriting_tier"]) == (630, "TIER_2_CONDITIONAL")
    assert entry["total_annual_savings_usd"] == 3071.96  # engine; the spec's $2,140 assumed additive rows
    assert entry["net_capex_usd"] == 19500.0
