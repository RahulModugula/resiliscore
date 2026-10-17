"""Guidewire mock and MCP tools, served from the golden scenarios (SPEC Prompt 1D)."""

import re

import pytest
from fastapi.testclient import TestClient

from app.fixtures import by_scenario
from app.integrations import mcp_server
from app.integrations.guidewire_mock import issue_decision, policy_number
from app.main import app

S1 = "SCENARIO_1_LA_FLOOD"
S2 = "SCENARIO_2_CA_WUI"
S3 = "SCENARIO_3_ESCONDIDO_HITL"
S3_UNPERMITTED = "SCENARIO_3_ESCONDIDO_HITL__UNPERMITTED"

client = TestClient(app)


def quote_then_issue(submission_id: str, scenario_id: str):
    q = client.post(f"/v1/guidewire/submissions/{submission_id}/quote", json={"scenario_id": scenario_id})
    assert q.status_code == 200, q.text
    return q.json(), client.post(f"/v1/guidewire/submissions/{submission_id}/issue")


def test_s1_quote_then_auto_bind():
    quote, issued = quote_then_issue("SUB-S1", S1)
    ext = quote["ResiliScore_Ext"]
    assert (ext["score"], ext["tier"]) == (765, "TIER_1_AUTO_BIND")
    assert quote["appliedRules"] == ["LA_FORTIFIED_ROOF_CREDIT"]
    assert quote["idmDocumentId"].startswith("IDM-")
    assert quote["premium"]["totalPremium"] == 2604.0
    body = issued.json()
    assert issued.status_code == 200
    assert body["bindType"] == "AUTO_BIND"
    assert re.fullmatch(r"RS-LA-\d{8}", body["policyNumber"])


def test_s2_issue_is_referred_with_409():
    quote, issued = quote_then_issue("SUB-S2", S2)
    assert quote["appliedRules"] == []
    assert issued.status_code == 409
    detail = issued.json()["detail"]
    assert detail["status"] == "ReferredToUnderwriting"
    assert detail["referral"]["queue"] == "UNDERWRITING_REFERRAL"


def test_s3_quote_then_bind_with_california_rules():
    quote, issued = quote_then_issue("SUB-S3", S3)
    assert "CA_CCR_2644_9_CAT_B1_B2" in quote["appliedRules"]
    assert "CA_CCR_2644_9_CAT_A" in quote["appliedRules"]
    assert issued.status_code == 200
    assert re.fullmatch(r"RS-CA-\d{8}", issued.json()["policyNumber"])


def test_escalated_hitl_parcel_is_referred_despite_tier_1():
    _, issued = quote_then_issue("SUB-S3U", S3_UNPERMITTED)
    assert issued.status_code == 409
    assert "unpermitted" in issued.json()["detail"]["referral"]["reason"].lower()


def test_tier_2_gets_conditional_bind_with_60_day_plan():
    s2 = by_scenario(S2)
    tier2 = s2.model_copy(
        update={"actuarial_breakdown": s2.actuarial_breakdown.model_copy(
            update={"resili_score": 630, "underwriting_tier": "TIER_2_CONDITIONAL"})}
    )
    status, body = issue_decision(tier2, "SUB-T2")
    assert status == 200
    assert body["bindType"] == "CONDITIONAL"
    assert body["actionPlan"]["deadlineDays"] == 60
    plan = [a["actionId"] for a in body["actionPlan"]["actions"]]
    assert plan[:3] == ["CA_ZONE0_1_CLEARANCE", "CA_EMBER_VENTS_EAVES", "CA_IBHS_WPH_CLASS_A_ROOF"]


def test_policy_numbers_are_deterministic():
    assert policy_number("SUB-X", "LA") == policy_number("SUB-X", "LA")
    assert policy_number("SUB-X", "LA") != policy_number("SUB-Y", "LA")
    first = quote_then_issue("SUB-DET", S1)[1].json()["policyNumber"]
    again = quote_then_issue("SUB-DET", S1)[1].json()["policyNumber"]
    assert first == again == policy_number("SUB-DET", "LA")


def test_quote_by_apn_matches_quote_by_scenario():
    by_apn = client.post("/v1/guidewire/submissions/SUB-A/quote", json={"apn_uid": "02200100041200"})
    assert by_apn.json()["ResiliScore_Ext"]["score"] == 765


@pytest.mark.parametrize(
    ("path", "body", "status"),
    [
        ("/v1/guidewire/submissions/SUB-NOQ/issue", None, 404),
        ("/v1/guidewire/submissions/SUB-E/quote", {"scenario_id": "NOPE"}, 404),
        ("/v1/guidewire/submissions/SUB-E/quote", {}, 422),
        ("/v1/guidewire/submissions/SUB-E/quote", {"scenario_id": S1, "apn_uid": "02200100041200"}, 422),
    ],
)
def test_bad_requests(path, body, status):
    assert client.post(path, json=body).status_code == status


def test_mcp_registers_four_tools():
    import asyncio

    names = {t.name for t in asyncio.run(mcp_server.mcp.list_tools())}
    assert names == {
        "get_parcel_resiliscore", "verify_zone0_clearance", "query_usgs_freeboard", "simulate_mitigation_roi"
    }


def test_get_parcel_resiliscore_returns_valid_data():
    out = mcp_server.get_parcel_resiliscore("1840 canyon crest dr, altadena, ca")
    assert out["actuarial_breakdown"]["resili_score"] == 385
    with pytest.raises(ValueError):
        mcp_server.get_parcel_resiliscore("1 Nowhere St")


def test_verify_zone0_clearance():
    assert mcp_server.verify_zone0_clearance("02200100041200")["zone0_clear"] is True
    s2 = mcp_server.verify_zone0_clearance("58430120180000")
    assert s2["zone0_clear"] is False
    s3 = mcp_server.verify_zone0_clearance("23312045070000")
    assert s3["needs_human_review"] is False


def test_query_usgs_freeboard():
    out = mcp_server.query_usgs_freeboard(29.9657, -90.1032)
    assert out["apn_uid"] == "02200100041200"
    assert out["freeboard_ft"] == 4.2
    with pytest.raises(ValueError):
        mcp_server.query_usgs_freeboard(0.0, 0.0)


def test_simulate_mitigation_roi_s2_all_three_actions_gives_630():
    actions = ["CA_ZONE0_1_CLEARANCE", "CA_EMBER_VENTS_EAVES", "CA_IBHS_WPH_CLASS_A_ROOF"]
    out = mcp_server.simulate_mitigation_roi("58430120180000", actions)
    assert out["new_score"] == 630
    assert out["new_tier"] == "TIER_2_CONDITIONAL"
    assert out["net_capex_usd"] == 19500.0
    assert out["annual_premium_savings_usd"] == pytest.approx(3071.96, abs=0.01)  # engine: premium before - after


def test_simulate_mitigation_roi_edges():
    one = mcp_server.simulate_mitigation_roi("58430120180000", ["CA_ZONE0_1_CLEARANCE"])
    assert (one["new_score"], one["new_tier"]) == (478, "TIER_3_DECLINE_ESCALATE")
    already = mcp_server.simulate_mitigation_roi("02200100041200", ["LA_FORTIFIED_ROOF"])
    assert already["new_score"] == 765 and already["payback_years"] is None
    with pytest.raises(ValueError):
        mcp_server.simulate_mitigation_roi("58430120180000", ["NOPE"])


def test_quote_and_mcp_use_the_same_engine():
    actions = ["CA_ZONE0_1_CLEARANCE", "CA_EMBER_VENTS_EAVES", "CA_IBHS_WPH_CLASS_A_ROOF"]
    quoted = TestClient(app).post(
        "/v1/guidewire/submissions/SUB-ENG/quote", json={"apn_uid": "58430120180000", "action_ids": actions}
    )
    roi = mcp_server.simulate_mitigation_roi("58430120180000", actions)
    assert quoted.json()["ResiliScore_Ext"]["score"] == roi["new_score"] == 630
