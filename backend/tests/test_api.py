"""API skeleton tests: every route serves the golden demo and the contract holds."""

import json
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from app.fixtures import by_scenario
from app.main import _tier, app
from app.models.schemas import ParcelScoreResponse

CONTRACTS = Path(__file__).resolve().parents[2] / "contracts"
SCHEMA = json.loads((CONTRACTS / "parcel_score_schema.json").read_text())
SCENARIOS = [
    "SCENARIO_1_LA_FLOOD",
    "SCENARIO_2_CA_WUI",
    "SCENARIO_3_ESCONDIDO_HITL",
    "SCENARIO_3_ESCONDIDO_HITL__UNPERMITTED",
]
WUI_APN = "58430120180000"
WUI_ACTIONS = ["CA_ZONE0_1_CLEARANCE", "CA_EMBER_VENTS_EAVES", "CA_IBHS_WPH_CLASS_A_ROOF"]


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.mark.parametrize("scenario_id", SCENARIOS)
def test_scenario_returns_200_and_validates(client, scenario_id):
    resp = client.post("/v1/parcel/score", json={"scenario_id": scenario_id})
    assert resp.status_code == 200
    body = resp.json()
    Draft202012Validator(SCHEMA).validate(body)
    ParcelScoreResponse.model_validate(body)
    assert body["actuarial_breakdown"] == by_scenario(scenario_id).actuarial_breakdown.model_dump(mode="json")


def test_each_score_gets_a_fresh_request_id(client):
    first = client.post("/v1/parcel/score", json={"scenario_id": SCENARIOS[0]}).json()
    second = client.post("/v1/parcel/score", json={"scenario_id": SCENARIOS[0]}).json()
    assert first["request_id"] != second["request_id"]
    assert uuid.UUID(second["request_id"])
    assert second["processing_time_ms"] >= 0


def test_address_match_is_case_insensitive(client):
    resp = client.post("/v1/parcel/score", json={"address": "1840 CANYON CREST DR, ALTADENA, CA"})
    assert resp.status_code == 200
    assert resp.json()["parcel_identity"]["apn_uid"] == WUI_APN


def test_unknown_address_is_404(client):
    resp = client.post("/v1/parcel/score", json={"address": "1 Nowhere Ln, Atlantis, XX"})
    assert resp.status_code == 404


def test_unknown_scenario_is_404(client):
    resp = client.post("/v1/parcel/score", json={"scenario_id": "SCENARIO_NOPE"})
    assert resp.status_code == 404


def test_score_needs_scenario_or_address(client):
    assert client.post("/v1/parcel/score", json={}).status_code == 422


def test_s2_toggling_all_three_mitigations_gives_630_tier_2(client):
    base = client.post("/v1/parcel/simulate-mitigation", json={"apn_uid": WUI_APN, "action_ids": []}).json()
    assert base["actuarial_breakdown"]["resili_score"] == 385
    assert base["actuarial_breakdown"]["underwriting_tier"] == "TIER_3_DECLINE_ESCALATE"

    resp = client.post("/v1/parcel/simulate-mitigation", json={"apn_uid": WUI_APN, "action_ids": WUI_ACTIONS})
    assert resp.status_code == 200
    body = resp.json()
    Draft202012Validator(SCHEMA).validate(body)
    assert body["actuarial_breakdown"]["resili_score"] == 630
    assert body["actuarial_breakdown"]["underwriting_tier"] == "TIER_2_CONDITIONAL"
    assert all(m["currently_applied"] for m in body["prescriptive_mitigations"])


def test_simulate_unknown_apn_is_404(client):
    resp = client.post("/v1/parcel/simulate-mitigation", json={"apn_uid": "0" * 14, "action_ids": []})
    assert resp.status_code == 404


def test_simulate_unknown_action_is_422(client):
    resp = client.post("/v1/parcel/simulate-mitigation", json={"apn_uid": WUI_APN, "action_ids": ["NOPE"]})
    assert resp.status_code == 422


@pytest.mark.parametrize(
    ("score", "tier"),
    [
        (720, "TIER_1_AUTO_BIND"),
        (719, "TIER_2_CONDITIONAL"),
        (580, "TIER_2_CONDITIONAL"),
        (579, "TIER_3_DECLINE_ESCALATE"),
    ],
)
def test_tier_band_edges(score, tier):
    assert _tier(score) == tier


def test_verify_override_clears_hitl(client):
    resp = client.post("/v1/hitl/verify-override", json={"apn_uid": "23312045070000"})
    assert resp.status_code == 200
    body = resp.json()
    Draft202012Validator(SCHEMA).validate(body)
    assert body["private_verification_layer"]["cv_confidence"] == 0.99
    assert body["hitl_status"] == {
        "escalated": False,
        "trigger_code": "NONE",
        "trigger_reason": None,
        "recommended_underwriter_action": None,
    }


def test_verify_override_unknown_apn_is_404(client):
    assert client.post("/v1/hitl/verify-override", json={"apn_uid": "0" * 14}).status_code == 404


def test_healthz_still_served(client):
    assert client.get("/healthz").json() == {"status": "ok"}
