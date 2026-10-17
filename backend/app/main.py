import time
import uuid

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, model_validator

from app import pipeline
from app.actuarial.optimizer import simulate
from app.fixtures import by_address, by_apn, by_scenario
from app.integrations.guidewire_mock import router as guidewire_router
from app.models.schemas import ParcelScoreResponse, State

app = FastAPI(title="ResiliScore API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(guidewire_router)

OVERRIDE_CV_CONFIDENCE = 0.99  # SPEC Prompt 1D: mobile self-inspection or underwriter approval


class ScoreRequest(BaseModel):
    """A golden `scenario_id`, or an `address`. An address that is not a golden one needs a point
    (`lat`, `lng`, `county_fips`, `state`) so the ingestion pipeline can run; the rest are optional."""

    scenario_id: str | None = None
    address: str | None = None
    lat: float | None = None
    lng: float | None = None
    county_fips: str | None = None
    state: State | None = None
    footprint: list[list[float]] | None = None
    rcv_usd: float | None = None
    year_built: int | None = None

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


def _fresh(resp: ParcelScoreResponse, started: float) -> ParcelScoreResponse:
    """A per-request copy with a new request_id and the real elapsed time."""
    elapsed_ms = (time.perf_counter() - started) * 1000
    return resp.model_copy(update={"request_id": str(uuid.uuid4()), "processing_time_ms": elapsed_ms})


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/parcel/score", response_model=ParcelScoreResponse)
async def score_parcel(body: ScoreRequest) -> ParcelScoreResponse:
    started = time.perf_counter()
    if body.scenario_id is not None:
        found = by_scenario(body.scenario_id)
    else:
        found = by_address(body.address or "")
        if found is None and None not in (body.lat, body.lng, body.county_fips, body.state):
            found = await pipeline.build_parcel(
                body.address or "", body.lat, body.lng, body.county_fips, body.state,  # type: ignore[arg-type]
                footprint=body.footprint, rcv_usd=body.rcv_usd, year_built=body.year_built,
            )  # fmt: skip
    if found is None:
        raise HTTPException(status_code=404, detail="no golden scenario matches and no coordinates to resolve")
    return _fresh(simulate(found, []), started)


@app.post("/v1/parcel/simulate-mitigation", response_model=ParcelScoreResponse)
def simulate_mitigation(body: SimulateRequest) -> ParcelScoreResponse:
    """Re-score the parcel with the toggled actions applied on top of its verified state (SPEC 1D)."""
    started = time.perf_counter()
    base = by_apn(body.apn_uid)
    if base is None:
        raise HTTPException(status_code=404, detail="unknown apn_uid")
    try:
        resp = simulate(base, body.action_ids)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _fresh(resp, started)


@app.post("/v1/hitl/verify-override", response_model=ParcelScoreResponse)
def verify_override(body: VerifyOverrideRequest) -> ParcelScoreResponse:
    """Set cv_confidence to 0.99 after verification and recompute Z, score, tier and HITL through the engine.

    The __UNPERMITTED variant shares its parcel's apn_uid, so this verifies the base S3 parcel.
    """
    started = time.perf_counter()
    base = by_apn(body.apn_uid)
    if base is None:
        raise HTTPException(status_code=404, detail="unknown apn_uid")
    verified = base.private_verification_layer.model_copy(update={"cv_confidence": OVERRIDE_CV_CONFIDENCE})
    return _fresh(simulate(base.model_copy(update={"private_verification_layer": verified}), []), started)
