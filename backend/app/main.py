import logging
import os
import time
import uuid
from collections.abc import Mapping

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, model_validator

from app import http, pipeline
from app.actuarial.optimizer import simulate
from app.fixtures import by_address, by_apn, by_scenario
from app.ingestion.geocode import GeocodeError
from app.ingestion.openfema import OPENFEMA_URL
from app.ingestion.usgs_3dep import EPQS_URL
from app.integrations.guidewire_mock import router as guidewire_router
from app.models.schemas import ParcelScoreResponse, State
from app.observability import RequestContextMiddleware, configure_logging, current_request_id
from app.verification.consortium import router as consortium_router
from app.verification.evidence import router as evidence_router

DEFAULT_CORS_ORIGINS = "http://localhost:3000"
UPSTREAMS = {"openfema": OPENFEMA_URL, "usgs_3dep": EPQS_URL}


def cors_origins(env: Mapping[str, str]) -> list[str]:
    """Comma-separated RS_CORS_ORIGINS, or the local frontend when unset or blank."""
    origins = [origin.strip() for origin in env.get("RS_CORS_ORIGINS", "").split(",") if origin.strip()]
    return origins or [DEFAULT_CORS_ORIGINS]


configure_logging()
log = logging.getLogger(__name__)
app = FastAPI(title="ResiliScore API", version="0.1.0", lifespan=http.lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins(os.environ),
    allow_methods=["*"],
    allow_headers=["*"],
)
# Added last so it is outermost: every response, preflight included, carries the request id.
app.add_middleware(RequestContextMiddleware)
app.include_router(guidewire_router)
app.include_router(evidence_router)
app.include_router(consortium_router)

OVERRIDE_CV_CONFIDENCE = 0.99  # SPEC Prompt 1D: mobile self-inspection or underwriter approval


class ScoreRequest(BaseModel):
    """A golden `scenario_id`, or an `address`. An address that is not a golden one needs a point
    (`lat`, `lng`, `county_fips`, `state`) so the ingestion pipeline can run; the rest are optional."""

    scenario_id: str | None = None
    address: str | None = None
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)
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
    request_id = current_request_id() or str(uuid.uuid4())
    return resp.model_copy(update={"request_id": request_id, "processing_time_ms": elapsed_ms})


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz")
def readyz() -> dict[str, object]:
    """Which upstreams are configured. Reads settings only and makes no network calls."""
    return {
        "status": "ready",
        "upstreams": {name: {"configured": bool(url), "url": url} for name, url in UPSTREAMS.items()},
    }


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
        elif found is None:
            try:
                found = await pipeline.build_parcel_for_address(
                    body.address or "", footprint=body.footprint, rcv_usd=body.rcv_usd, year_built=body.year_built
                )
            except GeocodeError as exc:
                raise HTTPException(status_code=404, detail=f"address not found by the Census Geocoder: {exc}") from exc
            except (TimeoutError, httpx.HTTPError) as exc:
                log.warning("Census Geocoder unavailable for address lookup: %s: %s", type(exc).__name__, exc)
                raise HTTPException(
                    status_code=502, detail="Census Geocoder unavailable; send lat, lng, county_fips and state"
                ) from exc
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
