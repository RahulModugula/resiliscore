"""Rules registry, evidence loop, consortium prototype and the broker MCP tools."""

import asyncio
from urllib.parse import urlparse

import pytest
from fastapi.testclient import TestClient

from app.actuarial.optimizer import simulate
from app.fixtures import by_apn
from app.integrations import mcp_server
from app.main import app
from app.rules import registry
from app.rules.applicability import applied_rule_ids, grant_ids
from app.verification import evidence
from app.verification.consortium import REFERENCE_W, estimate_k, run_experiment

client = TestClient(app)

S1_APN = "02200100041200"
S2_APN = "58430120180000"
S2_ALL = ["CA_ZONE0_1_CLEARANCE", "CA_EMBER_VENTS_EAVES", "CA_IBHS_WPH_CLASS_A_ROOF"]


@pytest.fixture(autouse=True)
def fresh_store(monkeypatch):
    monkeypatch.setattr(evidence, "store", evidence.InMemoryEvidenceStore())


# ---- registry ----

def test_registry_seed_ids_and_types():
    assert set(registry.ids()) >= {
        "CA_CCR_2644_9", "CA_FAIR_PLAN_WILDFIRE_CAP", "LA_FORTIFY_HOMES_GRANT", "LA_REG_136",
        "AL_STRENGTHEN_ALABAMA_HOMES", "NY_DFS_CL_2024_07",
    }
    assert registry.get("LA_REG_136").effective_date == "2027-01-01"
    assert registry.get("CA_FAIR_PLAN_WILDFIRE_CAP").effective_date == "2025-11-15"
    assert registry.get("LA_FORTIFY_HOMES_GRANT").type == "GRANT"


def test_every_rule_is_cited_and_unverified_ones_say_so():
    for rule in registry.RULES:
        assert urlparse(rule.source_url).scheme == "https"
        assert rule.source_date == "2026-10-17"
        assert rule.summary and rule.amount_or_range
    assert registry.get("LA_SB_355").verified is False
    assert registry.get("LA_SB_355").note


def test_registry_ids_are_unique():
    assert len(registry.ids()) == len(registry.RULES)


# ---- applicability / Guidewire ----

def test_applied_rules_use_registry_ids():
    assert applied_rule_ids(simulate(by_apn(S1_APN), [])) == ["LA_REG_136"]
    assert applied_rule_ids(simulate(by_apn(S2_APN), [])) == []
    assert applied_rule_ids(simulate(by_apn(S2_APN), S2_ALL)) == ["CA_CCR_2644_9"]


def test_guidewire_quote_applied_rules_exist_in_registry():
    for scenario in ("SCENARIO_1_LA_FLOOD", "SCENARIO_2_CA_WUI", "SCENARIO_3_ESCONDIDO_HITL"):
        body = client.post("/v1/guidewire/submissions/SUB-REG/quote", json={"scenario_id": scenario}).json()
        assert set(body["appliedRules"]) <= set(registry.ids())


def test_grant_only_for_unapplied_funded_action():
    s1 = simulate(by_apn(S1_APN), [])
    assert grant_ids(s1, ["LA_FORTIFIED_ROOF"]) == []  # S1 already has the roof
    pvl = s1.private_verification_layer.model_copy(
        update={"ibhs_fortified_tier": "NONE", "cv_roof_class": "CLASS_A_ASPHALT"}
    )
    bare = simulate(s1.model_copy(update={"private_verification_layer": pvl}), [])
    assert grant_ids(bare, ["LA_FORTIFIED_ROOF"]) == ["LA_FORTIFY_HOMES_GRANT"]
    assert applied_rule_ids(bare) == []


# ---- evidence loop ----

def post(apn, channel, meta=None):
    return client.post("/v1/verification/evidence", json={"apn_uid": apn, "channel": channel, "payload_meta": meta or {}})


def test_elevation_cert_raises_z_by_the_channel_weight():
    r = post(S2_APN, "ELEVATION_CERT")
    assert r.status_code == 200
    entry = r.json()["evidence_log"][0]
    assert entry["weight_added"] == 7.0
    assert entry["z_before"] == 0.62 and entry["z_after"] == 0.9121
    assert entry["evidence_id"] == f"EV-{S2_APN}-001" and entry["channel"] == "ELEVATION_CERT"
    assert r.json()["actuarial_breakdown"]["credibility_weight_z"] == entry["z_after"]
    assert r.json()["private_verification_layer"]["elev_cert_verified"] is True


def test_evidence_accumulates_and_matches_engine():
    post(S2_APN, "ELEVATION_CERT")
    r = post(S2_APN, "IBHS_CERT", {"wph_tier": "PLUS"}).json()
    log = r["evidence_log"]
    assert [e["evidence_id"][-3:] for e in log] == ["001", "002"]
    assert log[1]["z_before"] == log[0]["z_after"]
    assert log[1]["weight_added"] == 16.5
    expect = simulate(by_apn(S2_APN).model_copy(update={"private_verification_layer": by_apn(S2_APN)
        .private_verification_layer.model_copy(update={"elev_cert_verified": True, "ibhs_wph_tier": "PLUS"})}), [])
    assert r["actuarial_breakdown"]["resili_score"] == expect.actuarial_breakdown.resili_score
    assert log[1]["score_after"] == expect.actuarial_breakdown.resili_score


def test_lidar_adds_no_weight():
    entry = post(S2_APN, "LIDAR").json()["evidence_log"][0]
    assert entry["weight_added"] == 0 and entry["z_before"] == entry["z_after"]


def test_self_inspect_and_iot_channels():
    s3 = "23312045070000"
    assert post(S2_APN, "IOT").json()["evidence_log"][0]["weight_added"] == 8.0
    entry = post(s3, "PHOTO_SELF_INSPECT").json()["evidence_log"][0]
    assert entry["weight_added"] >= 0 and entry["z_after"] >= entry["z_before"]


def test_evidence_is_per_parcel():
    post(S2_APN, "ELEVATION_CERT")
    assert len(post(S1_APN, "IOT").json()["evidence_log"]) == 1


@pytest.mark.parametrize(
    ("body", "status"),
    [
        ({"apn_uid": "00000000000000", "channel": "IOT"}, 404),
        ({"apn_uid": S2_APN, "channel": "TELEPATHY"}, 422),
        ({"apn_uid": "short", "channel": "IOT"}, 422),
        ({"apn_uid": S2_APN, "channel": "IBHS_CERT"}, 422),
        ({"apn_uid": S2_APN, "channel": "IBHS_CERT", "payload_meta": {"fortified_tier": "PLATINUM"}}, 422),
        ({"apn_uid": S2_APN, "channel": "IBHS_CERT", "payload_meta": {"wph_tier": "BASE", "fortified_tier": "ROOF"}}, 422),
    ],
)
def test_evidence_bad_requests(body, status):
    assert client.post("/v1/verification/evidence", json=body).status_code == status


def test_store_is_swappable_behind_the_interface():
    class Spy(evidence.InMemoryEvidenceStore):
        calls = 0

        def save(self, apn_uid, parcel):
            Spy.calls += 1
            super().save(apn_uid, parcel)

    evidence.store = Spy()
    post(S2_APN, "IOT")
    assert Spy.calls == 1


# ---- consortium ----

def test_consortium_is_labelled_synthetic():
    body = client.get("/v1/consortium/credibility").json()
    assert body["synthetic"] is True
    assert all(c.startswith("SYNTHETIC_") for c in body["carriers"])
    assert "synthetic" in body["disclaimer"].lower()


def test_pooling_tightens_k_and_z():
    steps = run_experiment()
    for step in steps:
        assert step["pooled"]["k_sd"] < step["carrier_alone"]["k_sd"]
        assert step["pooled"]["z_sd"] < step["carrier_alone"]["z_sd"]
    assert [s["pooled"]["k_sd"] for s in steps] == sorted((s["pooled"]["k_sd"] for s in steps), reverse=True)
    assert [s["pooled"]["z_sd"] for s in steps] == sorted((s["pooled"]["z_sd"] for s in steps), reverse=True)
    assert abs(steps[-1]["pooled"]["k_mean"] - client.get("/v1/consortium/credibility").json()["true_k"]) < 0.1
    assert 0 < steps[0]["pooled"]["z_mean"] < 1 and REFERENCE_W > 0


def test_estimate_k_needs_between_cohort_variance():
    flat = [[1.0, 2.0, 3.0]] * 4  # identical cohorts: tau^2 is not positive
    assert estimate_k(flat) is None


# ---- MCP ----

def test_mcp_registers_broker_tools():
    names = {t.name for t in asyncio.run(mcp_server.mcp.list_tools())}
    assert {"what_if_mitigation", "explain_score"} <= names


def test_what_if_s2_all_actions():
    out = mcp_server.what_if_mitigation("1840 Canyon Crest Dr, Altadena, CA", S2_ALL)
    assert (out["score_before"], out["score_after"], out["score_delta"]) == (385, 630, 245)
    assert out["tier_after"] == "TIER_2_CONDITIONAL"
    assert out["premium_delta_usd"] < 0
    assert out["discount_mandates"] == ["CA_CCR_2644_9"] == out["newly_unlocked_mandates"]
    assert out["grant_eligibility"] == {"eligible": False, "grant_ids": [], "grant_usd": 0.0}
    cited = {c["id"]: c for c in out["cited_rules"]}
    assert cited["CA_CCR_2644_9"]["source_url"].startswith("https://")
    assert cited["CA_CCR_2644_9"]["verified"] is True


def test_what_if_accepts_apn_and_reports_applied_mandate():
    out = mcp_server.what_if_mitigation(S1_APN, ["LA_FORTIFIED_ROOF"])
    assert out["discount_mandates"] == ["LA_REG_136"] and out["newly_unlocked_mandates"] == []
    assert out["grant_eligibility"]["eligible"] is False  # the roof is already done


def test_what_if_rejects_unknown_inputs():
    with pytest.raises(ValueError, match="no golden parcel"):
        mcp_server.what_if_mitigation("1 Nowhere St", [])
    with pytest.raises(ValueError, match="valid ids"):
        mcp_server.what_if_mitigation(S2_APN, ["NOPE"])


def test_explain_score_falls_back_to_peril_split_without_factor_contributions():
    out = mcp_server.explain_score(S2_APN)
    shares = [p["share"] for p in out["peril_split"]]
    assert shares == sorted(shares, reverse=True) and abs(sum(shares) - 1) < 0.01
    assert out["peril_split"][0]["peril"] == "WILDFIRE"
    with pytest.raises(ValueError):
        mcp_server.explain_score("00000000000000")
