"""Contract tests: golden scenarios, JSON Schema and Pydantic models must agree."""

import json
import typing
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import BaseModel, ValidationError

from app.models.schemas import ParcelScoreResponse

CONTRACTS = Path(__file__).resolve().parents[2] / "contracts"
SCHEMA = json.loads((CONTRACTS / "parcel_score_schema.json").read_text())
GOLDEN = json.loads((CONTRACTS / "golden_scenarios.json").read_text())
KEYS = [
    "SCENARIO_1_LA_FLOOD",
    "SCENARIO_2_CA_WUI",
    "SCENARIO_3_ESCONDIDO_HITL",
    "SCENARIO_3_ESCONDIDO_HITL__UNPERMITTED",
]


def test_schema_is_valid_and_strict():
    Draft202012Validator.check_schema(SCHEMA)

    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "object" and "properties" in node:
                assert node["additionalProperties"] is False
                assert sorted(node["required"]) == sorted(node["properties"])
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(SCHEMA)


def test_golden_has_exactly_expected_keys():
    assert sorted(GOLDEN) == sorted(KEYS)


@pytest.mark.parametrize("key", KEYS)
def test_golden_validates_against_json_schema(key):
    Draft202012Validator(SCHEMA).validate(GOLDEN[key])


@pytest.mark.parametrize("key", KEYS)
def test_golden_validates_against_pydantic(key):
    model = ParcelScoreResponse.model_validate(GOLDEN[key])
    assert model.model_dump(mode="json")["actuarial_breakdown"] == GOLDEN[key]["actuarial_breakdown"]


def test_negative_extra_field_rejected():
    bad = json.loads(json.dumps(GOLDEN[KEYS[0]]))
    bad["hitl_status"]["surprise"] = 1
    with pytest.raises(ValidationError):
        ParcelScoreResponse.model_validate(bad)
    assert not Draft202012Validator(SCHEMA).is_valid(bad)


def _deref(node):
    if "$ref" in node:
        target = SCHEMA
        for part in node["$ref"].split("/")[1:]:
            target = target[part]
        return _deref(target)
    return node


def _inner_models(annotation):
    """Yield BaseModel subclasses nested in an annotation (list/Optional/tuple/dict)."""
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        yield annotation
    for arg in typing.get_args(annotation):
        yield from _inner_models(arg)


def _compare(model, node, path):
    node = _deref(node)
    props = node["properties"]
    assert set(model.model_fields) == set(props), f"{path}: field mismatch"
    for name, field in model.model_fields.items():
        sub = _deref(props[name])
        inner = list(_inner_models(field.annotation))
        if sub.get("type") == "array":
            sub = _deref(sub["items"])
        if "properties" in sub:
            assert len(inner) == 1, f"{path}.{name}: expected one nested model"
            _compare(inner[0], sub, f"{path}.{name}")
        else:
            assert not inner, f"{path}.{name}: model has nested model but schema is a leaf"


def test_pydantic_fields_match_json_schema_recursively():
    _compare(ParcelScoreResponse, SCHEMA, "$")


def test_enums_match():
    """Literal values in Pydantic must equal the schema enums."""
    defs = SCHEMA["$defs"]
    pairs = {
        ("PrivateVerificationLayer", "cv_roof_class"),
        ("PrivateVerificationLayer", "ibhs_fortified_tier"),
        ("PrivateVerificationLayer", "ibhs_wph_tier"),
        ("ParcelIdentity", "state"),
        ("PerilSplit", "peril"),
        ("ActuarialBreakdown", "underwriting_tier"),
        ("HitlStatus", "trigger_code"),
    }
    from app.models import schemas

    for d, f in pairs:
        model = getattr(schemas, d)
        assert set(typing.get_args(model.model_fields[f].annotation)) == set(defs[d]["properties"][f]["enum"]), (d, f)


def test_ca_factors_are_twelve():
    assert len(SCHEMA["$defs"]["Ca26449Factors"]["properties"]) == 12


def test_scenario_1_numbers():
    s = GOLDEN["SCENARIO_1_LA_FLOOD"]
    a, h = s["actuarial_breakdown"], s["public_hazard_layer"]
    assert s["parcel_identity"]["rcv_usd"] == 450000
    assert a["baseline_macro_score"] == 430
    assert a["resili_score"] == 765
    assert a["credibility_weight_z"] == 0.94
    assert a["underwriting_tier"] == "TIER_1_AUTO_BIND"
    assert a["statutory_discount_pct"] == 38
    assert a["tract_prior_lcr"] == 0.0185
    assert a["posterior_lcr"] == 0.0024
    assert a["expected_annual_loss_usd"] == 1080
    assert (h["fema_flood_zone"], h["bfe_ft_navd88"], h["usgs_lag_ft"], h["est_ffe_ft"]) == ("AE", 9.0, 7.2, 13.2)
    assert h["freeboard_delta_h_ft"] == pytest.approx(h["est_ffe_ft"] - h["bfe_ft_navd88"])
    assert h["hand_rel_elev_ft"] == 6.4
    assert a["annual_discounted_premium_usd"] == pytest.approx(a["annual_base_premium_usd"] * 0.62)


def test_scenario_2_numbers():
    s = GOLDEN["SCENARIO_2_CA_WUI"]
    a, p = s["actuarial_breakdown"], s["private_verification_layer"]
    assert s["parcel_identity"]["rcv_usd"] == 850000 and s["parcel_identity"]["year_built"] == 1974
    assert a["resili_score"] == 385 and a["underwriting_tier"] == "TIER_3_DECLINE_ESCALATE"
    assert a["tract_prior_lcr"] == 0.021 and a["posterior_lcr"] == 0.0245
    assert s["public_hazard_layer"]["landfire_fbfm40_code"] == "SH7" and s["public_hazard_layer"]["slope_deg"] == 28
    assert p["cv_roof_class"] == "WOOD_SHAKE_UNRATED" and p["cv_overhang_ft"] == 16.5
    mits = s["prescriptive_mitigations"]
    assert [m["gross_capex_usd"] for m in mits] == [1800, 3200, 14500]
    assert [m["score_delta_pts"] for m in mits] == [65, 55, 125]
    assert sum(m["score_delta_pts"] for m in mits) == 245
    assert a["resili_score"] + 245 == 630
    assert sum(m["annual_premium_savings_usd"] for m in mits) == 2140
    assert not any(m["currently_applied"] for m in mits)


def test_scenario_3_numbers():
    s = GOLDEN["SCENARIO_3_ESCONDIDO_HITL"]
    a, p = s["actuarial_breakdown"], s["private_verification_layer"]
    assert s["parcel_identity"]["rcv_usd"] == 720000
    assert a["resili_score"] == 815 and a["credibility_weight_z"] == 0.97 and a["posterior_lcr"] == 0.0018
    assert a["underwriting_tier"] == "TIER_1_AUTO_BIND"
    assert (p["ibhs_wph_tier"], p["cv_roof_class"], p["cv_zone0_clear"], p["iot_shutoff_active"]) == (
        "PLUS", "CLASS_A_IMPACT_4", True, True)
    assert s["hitl_status"] == {"escalated": False, "trigger_code": "NONE", "trigger_reason": None,
                                "recommended_underwriter_action": None}
    assert p["unpermitted_footprint_delta_sqft"] == 0


def test_scenario_3_unpermitted_variant():
    base = GOLDEN["SCENARIO_3_ESCONDIDO_HITL"]
    v = GOLDEN["SCENARIO_3_ESCONDIDO_HITL__UNPERMITTED"]
    assert v["private_verification_layer"]["unpermitted_footprint_delta_sqft"] == 240
    assert v["hitl_status"]["escalated"] is True
    assert v["hitl_status"]["trigger_code"] == "HITL_TRIGGER_02_UNPERMITTED_ADDITION"
    assert v["hitl_status"]["trigger_reason"] and v["hitl_status"]["recommended_underwriter_action"]
    assert v["actuarial_breakdown"] == base["actuarial_breakdown"]
    assert v["parcel_identity"]["address"] == base["parcel_identity"]["address"]


@pytest.mark.parametrize("key", KEYS)
def test_peril_aal_sums_to_expected_annual_loss(key):
    a = GOLDEN[key]["actuarial_breakdown"]
    assert abs(sum(r["peril_aal_usd"] for r in a["peril_split"]) - a["expected_annual_loss_usd"]) < 1.0


@pytest.mark.parametrize("key", KEYS)
def test_aal_matches_posterior_lcr_times_rcv(key):
    s = GOLDEN[key]
    assert s["actuarial_breakdown"]["posterior_lcr"] * s["parcel_identity"]["rcv_usd"] == pytest.approx(
        s["actuarial_breakdown"]["expected_annual_loss_usd"], abs=1.0)


@pytest.mark.parametrize("key", KEYS)
def test_geometry_kinds_present_and_rings_closed(key):
    feats = GOLDEN[key]["parcel_identity"]["geometries"]["features"]
    kinds = {f["properties"]["kind"] for f in feats}
    assert kinds >= {"parcel_polygon", "building_footprint", "zone_0_ring_0_5ft", "zone_1_ring_5_30ft",
                     "zone_2_ring_30_100ft", "cv_detection"}
    for f in feats:
        for ring in f["geometry"]["coordinates"]:
            assert ring[0] == ring[-1]


def _band(score):
    return "TIER_1_AUTO_BIND" if score >= 720 else "TIER_2_CONDITIONAL" if score >= 580 else "TIER_3_DECLINE_ESCALATE"


@pytest.mark.parametrize("key", KEYS)
def test_internal_arithmetic_consistency(key):
    a = GOLDEN[key]["actuarial_breakdown"]
    z = a["credibility_weight_z"]
    assert a["posterior_lcr"] == pytest.approx(z * a["parcel_raw_lcr"] + (1 - z) * a["tract_prior_lcr"], abs=1e-5)
    assert a["annual_discounted_premium_usd"] == pytest.approx(
        a["annual_base_premium_usd"] * (1 - a["statutory_discount_pct"] / 100), abs=0.5)
    assert a["underwriting_tier"] == _band(a["resili_score"])
    # Tract-prior-only baselines are all sub-580 in the goldens (prior LCRs are 160-210 bps).
    assert _band(a["baseline_macro_score"]) == "TIER_3_DECLINE_ESCALATE"
    for m in GOLDEN[key]["prescriptive_mitigations"]:
        assert m["net_capex_usd"] == pytest.approx(m["gross_capex_usd"] - m["grant_subsidy_usd"])
        if m["annual_premium_savings_usd"] > 0:
            assert m["payback_years"] == pytest.approx(m["net_capex_usd"] / m["annual_premium_savings_usd"], abs=0.01)
