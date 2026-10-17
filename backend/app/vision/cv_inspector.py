"""Aerial CV inspector (SPEC Prompt 1B, lines 129-137).

Three outcomes, each with provenance: a golden parcel served from its fixture (REFERENCE_PARCEL), a validated
live vision reply (LIVE), or an UNVERIFIED layer (UNAVAILABLE) for any other parcel without a usable image, so
the credibility weight falls honestly. One parcel's result is never lent to another.
"""

import base64
import json
import logging
import os
from pathlib import Path
from typing import NamedTuple

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from shapely.geometry import Polygon, box, mapping

from app.models.schemas import InputProvenance, PrivateVerificationLayer, RoofClass, ValueSource
from app.vision.parcel_rings import FT_TO_M, SQM_TO_SQFT, to_lnglat, to_metres

log = logging.getLogger(__name__)

GOLDEN_PATH = Path(__file__).resolve().parents[3] / "contracts" / "golden_scenarios.json"
# Escondido has two golden variants; the permitted one is the default.
GOLDEN_KEYS = ("SCENARIO_1_LA_FLOOD", "SCENARIO_2_CA_WUI", "SCENARIO_3_ESCONDIDO_HITL")
API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-sonnet-5-5"
TIMEOUT_S = 2.5
CONTEXT_FT = 100  # the live path assumes a north-up image framed on the footprint + 100 ft
CV_FIELDS = (
    "cv_roof_class", "cv_confidence", "cv_overhang_ft", "cv_zone0_clear", "cv_zone1_no_shed",
    "unpermitted_footprint_delta_sqft",
)  # fmt: skip
SOURCES: dict[ValueSource, str] = {
    "REFERENCE_PARCEL": "Golden reference parcel",
    "LIVE": f"Aerial vision model ({MODEL})",
    "UNAVAILABLE": "No aerial image for this parcel",
}


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Detection(_Strict):
    kind: str = Field(pattern="^(tree_overhang|shed)$")
    # Normalised [x0, y0, x1, y1] in the image, origin top-left.
    bbox: tuple[float, float, float, float]


class _VisionOutput(_Strict):
    cv_roof_class: RoofClass
    cv_overhang_ft: float = Field(ge=0)
    cv_zone0_clear: bool
    cv_zone1_no_shed: bool
    cv_confidence: float = Field(ge=0, le=1)
    detections: list[_Detection]


class Inspection(NamedTuple):
    layer: PrivateVerificationLayer
    detections: dict  # cv_detection FeatureCollection
    provenance: list[InputProvenance]


PROMPT = (
    "You inspect a north-up aerial image framed on a home plus 100 ft around it. Reply with JSON only: "
    '{"cv_roof_class": "CLASS_A_FORTIFIED|CLASS_A_IMPACT_4|CLASS_A_ASPHALT|WOOD_SHAKE_UNRATED", '
    '"cv_overhang_ft": feet of tree canopy over the 0-5 ft zone, "cv_zone0_clear": no combustible '
    'vegetation or mulch within 5 ft, "cv_zone1_no_shed": no detached combustible structure within 30 ft, '
    '"cv_confidence": 0-1, "detections": [{"kind": '
    '"tree_overhang|shed", "bbox": [x0, y0, x1, y1] as 0-1 image fractions}]}.'
)


def _provenance(source: ValueSource, fields: tuple[str, ...] = CV_FIELDS) -> list[InputProvenance]:
    return [InputProvenance(field=f, value_source=source, source_name=SOURCES[source], vintage=None) for f in fields]


def _load_golden() -> dict:
    return json.loads(GOLDEN_PATH.read_text())


def classify_zone(footprint_lnglat: list[list[float]], detection_lnglat: list[list[float]]) -> str | None:
    """Return "zone_0_ring_0_5ft" / "zone_1_ring_5_30ft" by nearest distance to the footprint, else None."""
    gap_ft = to_metres(Polygon(detection_lnglat)).distance(to_metres(Polygon(footprint_lnglat))) / FT_TO_M
    if gap_ft <= 5:
        return "zone_0_ring_0_5ft"
    if gap_ft <= 30:
        return "zone_1_ring_5_30ft"
    return None


def _detection_feature(geom_lnglat: Polygon, label: str) -> dict:
    return {
        "type": "Feature",
        "geometry": mapping(geom_lnglat),
        "properties": {"kind": "cv_detection", "label": label},
    }


def _golden_for(apn_uid: str, footprint: list[list[float]]) -> Inspection | None:
    """The golden result only when the APN matches and the footprint is on the golden building."""
    target = Polygon(footprint)
    for key in GOLDEN_KEYS:
        scenario = _load_golden()[key]
        identity = scenario["parcel_identity"]
        if identity["apn_uid"] != apn_uid:
            continue
        features = identity["geometries"]["features"]
        golden_building = next(f for f in features if f["properties"]["kind"] == "building_footprint")
        if not Polygon(golden_building["geometry"]["coordinates"][0]).intersects(target):
            return None
        detections = [f for f in features if f["properties"]["kind"] == "cv_detection"]
        layer = PrivateVerificationLayer.model_validate(scenario["private_verification_layer"])
        return Inspection(layer, {"type": "FeatureCollection", "features": detections}, _provenance("REFERENCE_PARCEL"))
    return None


def _unverified() -> Inspection:
    """Zero-confidence layer on the most conservative enums, with every mitigation flag false."""
    layer = PrivateVerificationLayer(
        cv_roof_class="WOOD_SHAKE_UNRATED",
        cv_confidence=0.0,
        cv_overhang_ft=0.0,
        cv_zone0_clear=False,
        cv_zone1_no_shed=False,
        cv_enclosed_eaves=False,
        cv_ember_vents=False,
        elev_cert_verified=False,
        ibhs_fortified_tier="NONE",
        ibhs_wph_tier="NONE",
        iot_shutoff_active=False,
        unpermitted_footprint_delta_sqft=0.0,
    )
    return Inspection(layer, {"type": "FeatureCollection", "features": []}, _provenance("UNAVAILABLE"))


def _offline(apn_uid: str, footprint: list[list[float]]) -> Inspection:
    return _golden_for(apn_uid, footprint) or _unverified()


def _media_type(image: bytes) -> str:
    return "image/png" if image.startswith(b"\x89PNG") else "image/jpeg"


def _parse_reply(text: str) -> _VisionOutput:
    """Validate the model's JSON, tolerating code fences and prose around the object."""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("no JSON object in vision reply")
    return _VisionOutput.model_validate_json(text[start : end + 1])


def _build_live(out: _VisionOutput, footprint: list[list[float]], assessor_sqft: float | None) -> Inspection:
    footprint_m = to_metres(Polygon(footprint))
    min_x, min_y, max_x, max_y = footprint_m.buffer(CONTEXT_FT * FT_TO_M).bounds
    features = []
    for d in out.detections:
        x0, y0, x1, y1 = d.bbox
        # Image y runs down; map y grows up.
        cell = box(
            min_x + x0 * (max_x - min_x), max_y - y1 * (max_y - min_y),
            min_x + x1 * (max_x - min_x), max_y - y0 * (max_y - min_y),
        )  # fmt: skip
        label = "Overhanging canopy (Zone 0)" if d.kind == "tree_overhang" else "Detached shed (Zone 1)"
        features.append(_detection_feature(to_lnglat(cell), label))
    # Footprint area minus the assessor's sqft; without the assessor figure there is nothing to compare.
    delta = round(footprint_m.area * SQM_TO_SQFT - assessor_sqft, 1) if assessor_sqft is not None else 0.0
    layer = PrivateVerificationLayer(
        cv_roof_class=out.cv_roof_class,
        cv_confidence=out.cv_confidence,
        cv_overhang_ft=out.cv_overhang_ft,
        cv_zone0_clear=out.cv_zone0_clear,
        cv_zone1_no_shed=out.cv_zone1_no_shed,
        # Not observable from a single orthophoto; stay conservative until verified elsewhere.
        cv_enclosed_eaves=False,
        cv_ember_vents=False,
        elev_cert_verified=False,
        ibhs_fortified_tier="NONE",
        ibhs_wph_tier="NONE",
        iot_shutoff_active=False,
        unpermitted_footprint_delta_sqft=delta,
    )
    provenance = _provenance("LIVE", CV_FIELDS[:-1])
    provenance.append(
        InputProvenance(
            field="unpermitted_footprint_delta_sqft",
            value_source="LIVE" if assessor_sqft is not None else "UNAVAILABLE",
            source_name=SOURCES["LIVE"] if assessor_sqft is not None else "No assessor sqft supplied",
            vintage=None,
        )
    )
    return Inspection(layer, {"type": "FeatureCollection", "features": features}, provenance)


async def _live_inspect(
    footprint: list[list[float]], image: bytes, api_key: str, assessor_sqft: float | None, client: httpx.AsyncClient
) -> Inspection:
    response = await client.post(
        API_URL,
        timeout=TIMEOUT_S,
        headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
        json={
            "model": MODEL,
            "max_tokens": 600,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": _media_type(image),
                                "data": base64.b64encode(image).decode(),
                            },
                        },
                        {"type": "text", "text": PROMPT},
                    ],
                }
            ],
        },
    )
    response.raise_for_status()
    return _build_live(_parse_reply(response.json()["content"][0]["text"]), footprint, assessor_sqft)


class AerialCVInspector:
    def inspect(
        self, apn_uid: str, footprint: list[list[float]], image: None = None
    ) -> tuple[PrivateVerificationLayer, dict]:
        """No-image result, synchronous: the golden parcel, else UNVERIFIED. Use `ainspect` with an image."""
        result = _offline(apn_uid, footprint)
        return result.layer, result.detections

    async def ainspect(
        self,
        apn_uid: str,
        footprint: list[list[float]],
        image: bytes | None,
        assessor_sqft: float | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> Inspection:
        """Live vision result when an image and `ANTHROPIC_API_KEY` exist; otherwise the no-image result."""
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if image is None or not api_key:
            return _offline(apn_uid, footprint)
        http = client or httpx.AsyncClient()
        try:
            return await _live_inspect(footprint, image, api_key, assessor_sqft, http)
        except (httpx.HTTPError, ValidationError, KeyError, IndexError, ValueError) as exc:
            log.warning("vision call failed for apn %s: %r", apn_uid, exc)
            return _offline(apn_uid, footprint)
        finally:
            if client is None:
                await http.aclose()  # a caller-supplied shared client stays open
