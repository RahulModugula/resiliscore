"""SaveMyHome MCP server (SPEC Prompt 1D, item 3, "FastMCP"): four deterministic tools backed by the golden scenarios.

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
from app.rules.applicability import applied_rule_ids, grant_ids
from app.rules.registry import Rule, get

mcp = MCPServer("resiliscore")  # `FastMCP` was renamed `MCPServer` in mcp 2.x (locked at 2.3.0)

MAX_MATCH_DEG = 0.01  # about 1 km; the golden parcels are far apart


def _parcel(apn_uid: str) -> ParcelScoreResponse:
    parcel = by_apn(apn_uid)
    if parcel is None:
        raise ValueError(f"unknown apn_uid {apn_uid!r}")
    return parcel


@mcp.tool()
def get_parcel_resiliscore(address: str) -> dict[str, Any]:
    """Get the SaveMyHome (300-850) and underwriting tier for a property address.

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


def _citation(rule: Rule) -> dict[str, Any]:
    return {
        "id": rule.id, "type": rule.type, "summary": rule.summary, "amount_or_range": rule.amount_or_range,
        "effective_date": rule.effective_date, "source_url": rule.source_url,
        "source_date": rule.source_date, "verified": rule.verified,
    }


@mcp.tool()
def what_if_mitigation(address_or_apn: str, action_ids: list[str]) -> dict[str, Any]:
    """Broker what-if: what happens to the score, premium, discounts and grants if the owner does these upgrades.

    `address_or_apn` is a demo parcel's full address or its 14-digit apn_uid; `action_ids` come from the
    parcel's prescriptive_mitigations. Returns the score and premium change, the discount mandates that apply
    after the work (with the ones the work newly unlocks), grant eligibility with the grant dollars, and every
    cited rule from the registry with its source URL, source date and `verified` flag.
    """
    base = by_apn(address_or_apn) if address_or_apn.isdigit() else by_address(address_or_apn)
    if base is None:
        raise ValueError(f"no golden parcel matches {address_or_apn!r}")
    before = simulate(base, [])
    try:
        after = simulate(base, action_ids)
    except ValueError as exc:
        raise ValueError(f"{exc}; valid ids: {[m.action_id for m in before.prescriptive_mitigations]}") from exc
    b, a = before.actuarial_breakdown, after.actuarial_breakdown
    rules_before, rules_after = applied_rule_ids(before), applied_rule_ids(after)
    grants = grant_ids(before, action_ids)
    chosen = set(action_ids)
    grant_usd = sum(
        m.grant_subsidy_usd for m in before.prescriptive_mitigations if m.action_id in chosen and not m.currently_applied
    )
    cited = list(dict.fromkeys(rules_after + grants))
    return {
        "apn_uid": base.parcel_identity.apn_uid,
        "action_ids": action_ids,
        "score_before": b.resili_score,
        "score_after": a.resili_score,
        "score_delta": a.resili_score - b.resili_score,
        "tier_before": b.underwriting_tier,
        "tier_after": a.underwriting_tier,
        "premium_before_usd": b.annual_discounted_premium_usd,
        "premium_after_usd": a.annual_discounted_premium_usd,
        "premium_delta_usd": round(a.annual_discounted_premium_usd - b.annual_discounted_premium_usd, 2),
        "discount_mandates": rules_after,
        "newly_unlocked_mandates": [r for r in rules_after if r not in rules_before],
        "grant_eligibility": {"eligible": bool(grants), "grant_ids": grants, "grant_usd": grant_usd},
        "cited_rules": [_citation(get(i)) for i in cited],
    }


@mcp.tool()
def explain_score(apn_uid: str) -> dict[str, Any]:
    """Explain a parcel's SaveMyHome: which perils drive the expected annual loss, largest first.

    Returns the contract v2 factor_contributions when the model fills them; always includes the peril split (each peril's
    share of the annual loss) and gives the credibility weight Z, which says how far the score rests on the
    parcel's own verified evidence rather than the census-tract prior.
    """
    parcel = simulate(_parcel(apn_uid), [])
    ab = parcel.actuarial_breakdown
    total = sum(p.peril_aal_usd for p in ab.peril_split)
    perils = sorted(ab.peril_split, key=lambda p: p.peril_aal_usd, reverse=True)
    factors = sorted(parcel.factor_contributions, key=lambda f: abs(f.score_points), reverse=True)
    return {
        "apn_uid": apn_uid,
        "resili_score": ab.resili_score,
        "credibility_weight_z": ab.credibility_weight_z,
        "factor_contributions": [f.model_dump(mode="json") for f in factors]
        or "none yet: the model does not populate factor_contributions, so see peril_split",
        "peril_split": [
            {"peril": p.peril, "aal_usd": p.peril_aal_usd, "share": round(p.peril_aal_usd / total, 4) if total else 0.0}
            for p in perils
        ],
    }


if __name__ == "__main__":
    mcp.run()
