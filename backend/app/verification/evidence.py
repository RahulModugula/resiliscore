"""Evidence loop: each verified evidence channel raises a parcel's credibility, and the score is recomputed.

A channel's weight is the inverse-variance precision in `app.actuarial.credibility`. Recording evidence sets
the matching verification-layer field, then `optimizer.simulate` rescores the parcel (the only scoring path),
so the before/after Z and score in the log come straight from the engine. The log lives on the parcel as
`evidence_log` (contract v2).
"""

from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.actuarial.credibility import credibility
from app.actuarial.optimizer import simulate
from app.fixtures import by_apn
from app.models.schemas import EvidenceLogEntry, ParcelScoreResponse, PrivateVerificationLayer

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


class EvidenceStore(Protocol):
    def current(self, apn_uid: str) -> ParcelScoreResponse | None: ...
    def save(self, apn_uid: str, parcel: ParcelScoreResponse) -> None: ...


class InMemoryEvidenceStore:
    # TODO: persistence (see README); this store forgets everything on restart.
    def __init__(self) -> None:
        self._parcels: dict[str, ParcelScoreResponse] = {}

    def current(self, apn_uid: str) -> ParcelScoreResponse | None:
        return self._parcels.get(apn_uid)

    def save(self, apn_uid: str, parcel: ParcelScoreResponse) -> None:
        self._parcels[apn_uid] = parcel


store: EvidenceStore = InMemoryEvidenceStore()


def _updates(channel: Channel, meta: dict[str, Any], v: PrivateVerificationLayer) -> dict[str, Any]:
    """Verification-layer fields a channel sets. LIDAR sets none: 1 m LiDAR is counted for every parcel."""
    if channel == "LIDAR":
        return {}
    if channel == "ELEVATION_CERT":
        return {"elev_cert_verified": True}
    if channel == "IOT":
        return {"iot_shutoff_active": True}
    if channel == "PHOTO_SELF_INSPECT":
        return {"cv_confidence": max(v.cv_confidence, SELF_INSPECT_CV_CONFIDENCE)}
    fortified, wph = meta.get("fortified_tier"), meta.get("wph_tier")
    if (fortified is None) == (wph is None):
        raise ValueError("IBHS_CERT needs exactly one of payload_meta.fortified_tier or payload_meta.wph_tier")
    if fortified is not None:
        if fortified not in FORTIFIED_TIERS:
            raise ValueError(f"fortified_tier must be one of {FORTIFIED_TIERS}")
        return {"ibhs_fortified_tier": fortified}
    if wph not in WPH_TIERS:
        raise ValueError(f"wph_tier must be one of {WPH_TIERS}")
    return {"ibhs_wph_tier": wph}


def record_evidence(apn_uid: str, channel: Channel, payload_meta: dict[str, Any]) -> ParcelScoreResponse:
    """Apply one evidence channel and return the rescored parcel with the new `evidence_log` entry."""
    base = store.current(apn_uid) or by_apn(apn_uid)
    if base is None:
        raise KeyError(apn_uid)
    before = simulate(base, [])
    fields = _updates(channel, payload_meta, base.private_verification_layer)
    verified = base.private_verification_layer.model_copy(update=fields)
    after = simulate(base.model_copy(update={"private_verification_layer": verified}), [])
    ab, aa = before.actuarial_breakdown, after.actuarial_breakdown
    entry = EvidenceLogEntry(
        evidence_id=f"EV-{apn_uid}-{len(base.evidence_log) + 1:03d}",
        channel=channel,
        submitted_at=datetime.now(UTC),
        weight_added=round(
            credibility(after.private_verification_layer).w - credibility(before.private_verification_layer).w, 4
        ),
        z_before=ab.credibility_weight_z,
        z_after=aa.credibility_weight_z,
        score_before=ab.resili_score,
        score_after=aa.resili_score,
    )
    out = after.model_copy(update={"evidence_log": [*base.evidence_log, entry]})
    store.save(apn_uid, out)
    return out


@router.post("/evidence", response_model=ParcelScoreResponse)
def post_evidence(body: EvidenceRequest) -> ParcelScoreResponse:
    try:
        return record_evidence(body.apn_uid, body.channel, body.payload_meta)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="unknown apn_uid") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
