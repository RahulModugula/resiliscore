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

from app.actuarial.optimizer import simulate
from app.fixtures import by_address, by_apn, load_golden
from app.models.schemas import ParcelScoreResponse

mcp = MCPServer("resiliscore")  # `FastMCP` was renamed `MCPServer` in mcp 2.x (locked at 2.3.0)

MAX_MATCH_DEG = 0.01  # about 1 km; the golden parcels are far apart


def _parcel(apn_uid: str) -> ParcelScoreResponse:
    parcel = by_apn(apn_uid)
    if parcel is None:
        raise ValueError(f"unknown apn_uid {apn_uid!r}")
    return parcel


@mcp.tool()
def get_parcel_resiliscore(address: str) -> dict[str, Any]:
    """Get the ResiliScore (300-850) and underwriting tier for a property address.

    Returns the full ParcelScoreResponse: score, tier (TIER_1_AUTO_BIND 720+, TIER_2_CONDITIONAL 580-719,
    TIER_3_DECLINE_ESCALATE below 580), credibility weight, annual loss, premium, ranked mitigations and
    any human-review flag. Use this first; pass the returned apn_uid to the other tools. The address must
    match a known demo parcel exactly, ignoring case (for example "412 Bayou Rd, Jefferson Parish, LA");
    otherwise the call errors.
    """
    parcel = by_address(address)
    if parcel is None:
        raise ValueError(f"no golden parcel matches address {address!r}")
    return simulate(parcel, []).model_dump(mode="json")


@mcp.tool()
def verify_zone0_clearance(apn_uid: str) -> dict[str, Any]:
    """Check whether the 0-5 ft ring around the building (Zone 0) is verified clear of combustibles.

    Takes the 14-digit apn_uid from get_parcel_resiliscore. Returns zone0_clear (bool), the computer-vision
    confidence, the Zone 1 shed check, and `needs_human_review`, true when confidence is below 0.85 or the
    parcel is escalated, in which case ask for a mobile self-inspection instead of trusting the result.
    """
    scenario = _parcel(apn_uid)
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
    for scenario in load_golden().values():
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
    "CA_ZONE0_1_CLEARANCE"). Already-applied actions add nothing; unknown ids error. Scored by the same
    engine as every other path: returns the new score and tier, net capex, annual premium savings and
    simple payback in years.
    """
    scenario = _parcel(apn_uid)
    before, after = simulate(scenario, []), simulate(scenario, actions)
    was_applied = {m.action_id for m in before.prescriptive_mitigations if m.currently_applied}
    chosen = [m for m in after.prescriptive_mitigations if m.currently_applied and m.action_id not in was_applied]
    b, a = before.actuarial_breakdown, after.actuarial_breakdown
    capex = sum(m.net_capex_usd for m in chosen)
    savings = round(b.annual_discounted_premium_usd - a.annual_discounted_premium_usd, 2)
    return {
        "apn_uid": apn_uid,
        "applied_actions": [m.action_id for m in chosen],
        "baseline_score": b.resili_score,
        "new_score": a.resili_score,
        "score_delta_pts": a.resili_score - b.resili_score,
        "baseline_tier": b.underwriting_tier,
        "new_tier": a.underwriting_tier,
        "net_capex_usd": capex,
        "annual_premium_savings_usd": savings,
        "payback_years": round(capex / savings, 1) if savings > 0 else None,
    }


if __name__ == "__main__":
    mcp.run()
