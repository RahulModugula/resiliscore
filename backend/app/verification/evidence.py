"""Evidence loop: each verified evidence channel raises a parcel's credibility, and the score is recomputed.

A channel's weight is the inverse-variance precision in `app.actuarial.credibility`. Recording evidence sets
the matching verification-layer field, then `optimizer.simulate` rescores the parcel (the only scoring path),
so the before/after Z and score in the log come straight from the engine.
"""

from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.actuarial.credibility import credibility
from app.actuarial.optimizer import simulate
from app.fixtures import by_apn
from app.models.schemas import ParcelScoreResponse, PrivateVerificationLayer

Channel = Literal["LIDAR", "ELEVATION_CERT", "IBHS_CERT", "PHOTO_SELF_INSPECT", "IOT"]

SELF_INSPECT_CV_CONFIDENCE = 0.99  # same level the HITL override uses
FORTIFIED_TIERS = ("ROOF", "SILVER", "GOLD")
WPH_TIERS = ("BASE", "PLUS")

router = APIRouter(prefix="/v1/verification")


class EvidenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    apn_uid: str = Field(pattern=r"^[0-9]{14}$")
    channel: Channel
    payload_meta: dict[str, Any] = {}


class EvidenceEntry(BaseModel):
    seq: int
    channel: Channel
    recorded_at: str
    payload_meta: dict[str, Any]
    weight_added: float
    z_before: float
    z_after: float
    score_before: int
    score_after: int
    tier_before: str
    tier_after: str
    note: str = ""


class EvidenceResponse(BaseModel):
    """The rescored parcel plus its evidence log. The log moves into the parcel when contract v2 lands."""

    parcel: ParcelScoreResponse
    evidence_log: list[EvidenceEntry]


class EvidenceStore(Protocol):
    def current(self, apn_uid: str) -> ParcelScoreResponse | None: ...
    def log(self, apn_uid: str) -> list[EvidenceEntry]: ...
    def record(self, apn_uid: str, parcel: ParcelScoreResponse, entry: EvidenceEntry) -> None: ...


class InMemoryEvidenceStore:
    def __init__(self) -> None:
        self._parcels: dict[str, ParcelScoreResponse] = {}
        self._logs: dict[str, list[EvidenceEntry]] = {}

    def current(self, apn_uid: str) -> ParcelScoreResponse | None:
        return self._parcels.get(apn_uid)

    def log(self, apn_uid: str) -> list[EvidenceEntry]:
        return list(self._logs.get(apn_uid, []))

    def record(self, apn_uid: str, parcel: ParcelScoreResponse, entry: EvidenceEntry) -> None:
        self._parcels[apn_uid] = parcel
        self._logs.setdefault(apn_uid, []).append(entry)


store: EvidenceStore = InMemoryEvidenceStore()


def _updates(channel: Channel, meta: dict[str, Any], v: PrivateVerificationLayer) -> tuple[dict[str, Any], str]:
    """Verification-layer fields a channel sets, and a note when it changes nothing."""
    if channel == "LIDAR":
        return {}, "1 m LiDAR is already counted for every parcel; no new weight."
    if channel == "ELEVATION_CERT":
        return {"elev_cert_verified": True}, ""
    if channel == "IOT":
        return {"iot_shutoff_active": True}, ""
    if channel == "PHOTO_SELF_INSPECT":
        return {"cv_confidence": max(v.cv_confidence, SELF_INSPECT_CV_CONFIDENCE)}, ""
    fortified, wph = meta.get("fortified_tier"), meta.get("wph_tier")
    if (fortified is None) == (wph is None):
        raise ValueError("IBHS_CERT needs exactly one of payload_meta.fortified_tier or payload_meta.wph_tier")
    if fortified is not None:
        if fortified not in FORTIFIED_TIERS:
            raise ValueError(f"fortified_tier must be one of {FORTIFIED_TIERS}")
        return {"ibhs_fortified_tier": fortified}, ""
    if wph not in WPH_TIERS:
        raise ValueError(f"wph_tier must be one of {WPH_TIERS}")
    return {"ibhs_wph_tier": wph}, ""


def record_evidence(apn_uid: str, channel: Channel, payload_meta: dict[str, Any]) -> EvidenceResponse:
    base = store.current(apn_uid) or by_apn(apn_uid)
    if base is None:
        raise KeyError(apn_uid)
    before = simulate(base, [])
    fields, note = _updates(channel, payload_meta, base.private_verification_layer)
    verified = base.private_verification_layer.model_copy(update=fields)
    after = simulate(base.model_copy(update={"private_verification_layer": verified}), [])
    w_before = credibility(before.private_verification_layer).w
    w_after = credibility(after.private_verification_layer).w
    ab, aa = before.actuarial_breakdown, after.actuarial_breakdown
    entry = EvidenceEntry(
        seq=len(store.log(apn_uid)) + 1,
        channel=channel,
        recorded_at=datetime.now(UTC).isoformat(timespec="seconds"),
        payload_meta=payload_meta,
        weight_added=round(w_after - w_before, 4),
        z_before=ab.credibility_weight_z,
        z_after=aa.credibility_weight_z,
        score_before=ab.resili_score,
        score_after=aa.resili_score,
        tier_before=ab.underwriting_tier,
        tier_after=aa.underwriting_tier,
        note=note,
    )
    store.record(apn_uid, after, entry)
    return EvidenceResponse(parcel=after, evidence_log=store.log(apn_uid))


@router.post("/evidence", response_model=EvidenceResponse)
def post_evidence(body: EvidenceRequest) -> EvidenceResponse:
    try:
        return record_evidence(body.apn_uid, body.channel, body.payload_meta)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="unknown apn_uid") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
