"""The golden file must equal the engine's output; regenerate with scripts/regen_golden.py."""

import json

import pytest

from app.fixtures import GOLDEN_PATH, reconcile

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
