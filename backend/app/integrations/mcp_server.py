"""ResiliScore MCP server (SPEC Prompt 1D, item 3, "FastMCP"): four deterministic tools backed by the golden scenarios.

Run over stdio:  python -m app.integrations.mcp_server   (from the `backend/` directory)

Claude Desktop config (`claude_desktop_config.json`):

    {
      "mcpServers": {
        "resiliscore": {
          "command": "uv",
          "args": ["run", "--project", "/path/to/resiliscore/backend", "python", "-m",
                   "app.integrations.mcp_server"],
          "cwd": "/path/to/resiliscore/backend"
        }
      }
    }
"""

from typing import Any

from mcp.server.mcpserver import MCPServer

from app.integrations.guidewire_mock import find_scenario, load_scenarios
from app.models.schemas import ParcelScoreResponse, UnderwritingTier

mcp = MCPServer("resiliscore")  # `FastMCP` was renamed `MCPServer` in mcp 2.x (locked at 2.3.0)

TIER_1_MIN = 720
TIER_2_MIN = 580
MAX_MATCH_DEG = 0.01  # about 1 km; the golden parcels are far apart


def band(score: int) -> UnderwritingTier:
    """Re-band a ResiliScore: 720+ Tier 1, 580-719 Tier 2, below 580 Tier 3 (SPEC Prompt 1B, item 2)."""
    if score >= TIER_1_MIN:
        return "TIER_1_AUTO_BIND"
    if score >= TIER_2_MIN:
        return "TIER_2_CONDITIONAL"
    return "TIER_3_DECLINE_ESCALATE"


def _normalise(address: str) -> str:
    return " ".join(address.lower().replace(",", " ").split())


def _by_address(address: str) -> ParcelScoreResponse:
    wanted = _normalise(address)
    for scenario in load_scenarios().values():
        if wanted and wanted in _normalise(scenario.parcel_identity.address):
            return scenario
    raise ValueError(f"no golden parcel matches address {address!r}")


@mcp.tool()
def get_parcel_resiliscore(address: str) -> dict[str, Any]:
    """Get the ResiliScore (300-850) and underwriting tier for a property address.

    Returns the full ParcelScoreResponse: score, tier (TIER_1_AUTO_BIND 720+, TIER_2_CONDITIONAL 580-719,
    TIER_3_DECLINE_ESCALATE below 580), credibility weight, annual loss, premium, ranked mitigations and
    any human-review flag. Use this first; pass the returned apn_uid to the other tools. The address must
    match a known demo parcel (for example "412 Bayou Rd"); otherwise the call errors.
    """
    return _by_address(address).model_dump(mode="json")


@mcp.tool()
def verify_zone0_clearance(apn_uid: str) -> dict[str, Any]:
    """Check whether the 0-5 ft ring around the building (Zone 0) is verified clear of combustibles.

    Takes the 14-digit apn_uid from get_parcel_resiliscore. Returns zone0_clear (bool), the computer-vision
    confidence, the Zone 1 shed check, and `needs_human_review`, true when confidence is below 0.85 or the
    parcel is escalated, in which case ask for a mobile self-inspection instead of trusting the result.
    """
    _, scenario = find_scenario(apn_uid=apn_uid)
    pvl = scenario.private_verification_layer
    return {
        "apn_uid": apn_uid,
        "zone0_clear": pvl.cv_zone0_clear,
        "zone1_no_shed": pvl.cv_zone1_no_shed,
        "cv_confidence": pvl.cv_confidence,
        "needs_human_review": pvl.cv_confidence < 0.85 or scenario.hitl_status.escalated,
    }


@mcp.tool()
def query_usgs_freeboard(lat: float, lng: float) -> dict[str, Any]:
    """Look up flood elevation data for a coordinate: FEMA zone, base flood elevation and freeboard.

    Freeboard is estimated first-floor elevation minus base flood elevation, in feet (NAVD88); positive
    means the floor sits above the 100-year flood. Only coordinates within about 1 km of a demo parcel
    resolve; others error. Returns the matched apn_uid so it can be passed to other tools.
    """
    best: tuple[float, ParcelScoreResponse] | None = None
    for scenario in load_scenarios().values():
        lng0, lat0 = scenario.parcel_identity.centroid
        dist = max(abs(lat - lat0), abs(lng - lng0))
        if dist <= MAX_MATCH_DEG and (best is None or dist < best[0]):
            best = (dist, scenario)
    if best is None:
        raise ValueError(f"no golden parcel within {MAX_MATCH_DEG} degrees of ({lat}, {lng})")
    parcel = best[1]
    hazard = parcel.public_hazard_layer
    return {
        "apn_uid": parcel.parcel_identity.apn_uid,
        "fema_flood_zone": hazard.fema_flood_zone,
        "bfe_ft_navd88": hazard.bfe_ft_navd88,
        "usgs_lag_ft": hazard.usgs_lag_ft,
        "est_ffe_ft": hazard.est_ffe_ft,
        "freeboard_ft": hazard.freeboard_delta_h_ft,
    }


@mcp.tool()
def simulate_mitigation_roi(apn_uid: str, actions: list[str]) -> dict[str, Any]:
    """Simulate the score, tier and payback if the homeowner completes the listed mitigations.

    `actions` are action_id values from the parcel's prescriptive_mitigations (for example
    "CA_ZONE0_1_CLEARANCE"). Already-applied actions add nothing; unknown ids error. Returns the new
    score (capped 300-850) and tier, net capex, annual premium savings and simple payback in years.
    """
    _, scenario = find_scenario(apn_uid=apn_uid)
    catalog = {m.action_id: m for m in scenario.prescriptive_mitigations}
    unknown = sorted(set(actions) - catalog.keys())
    if unknown:
        raise ValueError(f"unknown action_ids {unknown}; valid: {sorted(catalog)}")
    chosen = [catalog[a] for a in dict.fromkeys(actions) if not catalog[a].currently_applied]
    base = scenario.actuarial_breakdown.resili_score
    new_score = min(850, max(300, base + sum(m.score_delta_pts for m in chosen)))
    capex = sum(m.net_capex_usd for m in chosen)
    savings = sum(m.annual_premium_savings_usd for m in chosen)
    return {
        "apn_uid": apn_uid,
        "applied_actions": [m.action_id for m in chosen],
        "baseline_score": base,
        "new_score": new_score,
        "score_delta_pts": new_score - base,
        "baseline_tier": scenario.actuarial_breakdown.underwriting_tier,
        "new_tier": band(new_score),
        "net_capex_usd": capex,
        "annual_premium_savings_usd": savings,
        "payback_years": round(capex / savings, 1) if savings else None,
    }


if __name__ == "__main__":
    mcp.run()
