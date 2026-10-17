"""Guidewire PolicyCenter / IDM simulator (SPEC Prompt 1D, item 2).

Serves the golden scenarios as a PolicyCenter-style quote and issue flow. No network calls, so the
2.5 s timeout fallback is the default path.
"""

import hashlib
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, model_validator

from app.actuarial.optimizer import simulate
from app.fixtures import by_apn, by_scenario
from app.models.schemas import ParcelScoreResponse

CONDITIONAL_BIND_DAYS = 60

router = APIRouter(prefix="/v1/guidewire")

# submission_id -> quoted parcel, filled by /quote and read by /issue.
_submissions: dict[str, ParcelScoreResponse] = {}


class QuoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str | None = None
    apn_uid: str | None = None
    action_ids: list[str] = []  # mitigations assumed completed, priced by the same engine

    @model_validator(mode="after")
    def _exactly_one(self) -> "QuoteRequest":
        if (self.scenario_id is None) == (self.apn_uid is None):
            raise ValueError("provide exactly one of scenario_id or apn_uid")
        return self


def applied_rules(score: ParcelScoreResponse) -> list[str]:
    """Gosu rule ids that fire for the parcel's state and verified features."""
    pvl = score.private_verification_layer
    state = score.parcel_identity.state
    rules: list[str] = []
    if state == "CA":
        ca = score.regulatory_compliance.ca_2644_9_factors.model_dump()
        if any(v for k, v in ca.items() if k.startswith("cat_a")):
            rules.append("CA_CCR_2644_9_CAT_A")
        if any(v for k, v in ca.items() if k.startswith(("cat_b1", "cat_b2"))):
            rules.append("CA_CCR_2644_9_CAT_B1_B2")
    if state == "LA" and pvl.ibhs_fortified_tier != "NONE":
        rules.append("LA_FORTIFIED_ROOF_CREDIT")
    if state == "FL" and pvl.ibhs_fortified_tier != "NONE":
        rules.append("FL_FORTIFIED_HOME_CREDIT")
    if pvl.ibhs_wph_tier != "NONE":
        rules.append(f"IBHS_WPH_{pvl.ibhs_wph_tier}_CREDIT")
    return rules


def _digest(submission_id: str, salt: str) -> str:
    return hashlib.sha256(f"{salt}:{submission_id}".encode()).hexdigest()


def policy_number(submission_id: str, state: str) -> str:
    """Deterministic `RS-<state>-<8 digits>` number for a submission."""
    return f"RS-{state}-{int(_digest(submission_id, 'policy'), 16) % 10**8:08d}"


def _quote_payload(submission_id: str, score: ParcelScoreResponse) -> dict[str, Any]:
    ab = score.actuarial_breakdown
    return {
        "submissionId": submission_id,
        "apnUid": score.parcel_identity.apn_uid,
        "status": "Quoted",
        "ResiliScore_Ext": {
            "score": ab.resili_score,
            "tier": ab.underwriting_tier,
            "credibilityZ": ab.credibility_weight_z,
            "posteriorLcr": ab.posterior_lcr,
            "aalUsd": ab.expected_annual_loss_usd,
        },
        "idmDocumentId": f"IDM-{_digest(submission_id, 'idm')[:12].upper()}",
        "appliedRules": applied_rules(score),
        "premium": {
            "currency": "USD",
            "basePremium": ab.annual_base_premium_usd,
            "statutoryDiscountPct": ab.statutory_discount_pct,
            "totalPremium": ab.annual_discounted_premium_usd,
        },
    }


@router.post("/submissions/{submission_id}/quote")
def quote(submission_id: str, body: QuoteRequest) -> dict[str, Any]:
    """PricingCenter BYOM quote for a golden parcel, scored by `optimizer.simulate`."""
    parcel = by_scenario(body.scenario_id) if body.scenario_id is not None else by_apn(body.apn_uid or "")
    if parcel is None:
        raise HTTPException(status_code=404, detail="no golden scenario matches")
    try:
        score = simulate(parcel, body.action_ids)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _submissions[submission_id] = score
    return _quote_payload(submission_id, score)


def issue_decision(score: ParcelScoreResponse, submission_id: str) -> tuple[int, dict[str, Any]]:
    """Bind decision by tier: auto-bind, conditional bind with an action plan, or referral.

    An escalated HITL parcel is referred whatever its tier.
    """
    ab = score.actuarial_breakdown
    hitl = score.hitl_status
    if ab.underwriting_tier == "TIER_3_DECLINE_ESCALATE" or hitl.escalated:
        reason = hitl.trigger_reason if hitl.escalated else f"ResiliScore {ab.resili_score} is below 580"
        return 409, {
            "status": "ReferredToUnderwriting",
            "referral": {
                "queue": "UNDERWRITING_REFERRAL",
                "reason": reason,
                "recommendedAction": hitl.recommended_underwriter_action
                or "Underwriter review; a mitigation plan may lift the parcel to Tier 2.",
            },
        }
    number = policy_number(submission_id, score.parcel_identity.state)
    if ab.underwriting_tier == "TIER_1_AUTO_BIND":
        return 200, {"status": "Bound", "bindType": "AUTO_BIND", "policyNumber": number}
    plan = [
        {"actionId": m.action_id, "title": m.title, "dueInDays": CONDITIONAL_BIND_DAYS}
        for m in score.prescriptive_mitigations
        if not m.currently_applied
    ]
    return 200, {
        "status": "Bound",
        "bindType": "CONDITIONAL",
        "policyNumber": number,
        "actionPlan": {"deadlineDays": CONDITIONAL_BIND_DAYS, "actions": plan},
    }


@router.post("/submissions/{submission_id}/issue")
def issue(submission_id: str) -> dict[str, Any]:
    """Issue the quoted submission. Tier 3 and HITL-escalated parcels return 409 with a referral."""
    score = _submissions.get(submission_id)
    if score is None:
        raise HTTPException(status_code=404, detail=f"submission {submission_id!r} has no quote")
    status, payload = issue_decision(score, submission_id)
    payload = {"submissionId": submission_id, "apnUid": score.parcel_identity.apn_uid, **payload}
    if status == 409:
        raise HTTPException(status_code=409, detail=payload)
    return payload
