import time
import uuid

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, model_validator

from app.fixtures import by_address, by_apn, by_scenario
from app.models.schemas import HitlStatus, ParcelScoreResponse, UnderwritingTier

app = FastAPI(title="ResiliScore API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ScoreRequest(BaseModel):
    scenario_id: str | None = None
    address: str | None = None

    @model_validator(mode="after")
    def _needs_one_key(self) -> "ScoreRequest":
        if self.scenario_id is None and self.address is None:
            raise ValueError("one of scenario_id or address is required")
        return self


class SimulateRequest(BaseModel):
    apn_uid: str
    action_ids: list[str]


class VerifyOverrideRequest(BaseModel):
    apn_uid: str


def _tier(score: int) -> UnderwritingTier:
    """Tier bands from docs/SPEC.md:156. 720-850 auto-bind, 580-719 conditional, 300-579 decline."""
    if score >= 720:
        return "TIER_1_AUTO_BIND"
    if score >= 580:
        return "TIER_2_CONDITIONAL"
    return "TIER_3_DECLINE_ESCALATE"


def _fresh(resp: ParcelScoreResponse, started: float) -> ParcelScoreResponse:
    """A per-request copy with a new request_id and the real elapsed time."""
    elapsed_ms = (time.perf_counter() - started) * 1000
    return resp.model_copy(update={"request_id": str(uuid.uuid4()), "processing_time_ms": elapsed_ms})


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/parcel/score", response_model=ParcelScoreResponse)
def score_parcel(body: ScoreRequest) -> ParcelScoreResponse:
    started = time.perf_counter()
    if body.scenario_id is not None:
        found = by_scenario(body.scenario_id)
    else:
        found = by_address(body.address or "")
    if found is None:
        raise HTTPException(status_code=404, detail="no golden scenario matches")
    return _fresh(found, started)


@app.post("/v1/parcel/simulate-mitigation", response_model=ParcelScoreResponse)
def simulate_mitigation(body: SimulateRequest) -> ParcelScoreResponse:
    """Stub until the actuarial lane lands. See docs/SPEC.md:169.

    Base score is the golden score with its currently-applied mitigations removed. Each selected
    action then adds its score_delta_pts. With no actions selected, the result is the unmitigated base.
    """
    started = time.perf_counter()
    base = by_apn(body.apn_uid)
    if base is None:
        raise HTTPException(status_code=404, detail="unknown apn_uid")
    known = {m.action_id: m for m in base.prescriptive_mitigations}
    unknown = sorted(set(body.action_ids) - known.keys())
    if unknown:
        raise HTTPException(status_code=422, detail=f"unknown action_ids: {unknown}")

    selected = set(body.action_ids)
    applied_pts = sum(m.score_delta_pts for m in base.prescriptive_mitigations if m.currently_applied)
    score = (
        base.actuarial_breakdown.resili_score - applied_pts + sum(known[a].score_delta_pts for a in selected)
    )

    breakdown = base.actuarial_breakdown.model_copy(
        update={"resili_score": score, "underwriting_tier": _tier(score)}
    )
    mitigations = [
        m.model_copy(update={"currently_applied": m.action_id in selected})
        for m in base.prescriptive_mitigations
    ]
    resp = base.model_copy(update={"actuarial_breakdown": breakdown, "prescriptive_mitigations": mitigations})
    return _fresh(resp, started)


@app.post("/v1/hitl/verify-override", response_model=ParcelScoreResponse)
def verify_override(body: VerifyOverrideRequest) -> ParcelScoreResponse:
    """Clears the HITL escalation after mobile or underwriter verification. Stateless stub; see docs/SPEC.md:170.

    The __UNPERMITTED variant shares its parcel's apn_uid, so this returns the base S3 response with HITL cleared.
    """
    started = time.perf_counter()
    base = by_apn(body.apn_uid)
    if base is None:
        raise HTTPException(status_code=404, detail="unknown apn_uid")
    verification = base.private_verification_layer.model_copy(update={"cv_confidence": 0.99})
    cleared = HitlStatus(
        escalated=False,
        trigger_code="NONE",
        trigger_reason=None,
        recommended_underwriter_action=None,
    )
    resp = base.model_copy(update={"private_verification_layer": verification, "hitl_status": cleared})
    return _fresh(resp, started)
