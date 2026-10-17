"""Aerial CV inspector (SPEC Prompt 1B, lines 129-137).

Without an image or `ANTHROPIC_API_KEY` it serves the golden scenario for the parcel. With both, it asks a
vision model for strict JSON, validates it, and falls back to golden on any failure or after 2.5 s.
"""

import base64
import json
import os
from pathlib import Path

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from shapely.geometry import Polygon, box, mapping

from app.models.schemas import PrivateVerificationLayer, RoofClass
from app.vision.parcel_rings import FT_TO_M, SQM_TO_SQFT, to_lnglat, to_metres

GOLDEN_PATH = Path(__file__).resolve().parents[3] / "contracts" / "golden_scenarios.json"
# Escondido has two golden variants; the permitted one is the default.
GOLDEN_KEYS = ("SCENARIO_1_LA_FLOOD", "SCENARIO_2_CA_WUI", "SCENARIO_3_ESCONDIDO_HITL")
API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-sonnet-5-5"
TIMEOUT_S = 2.5
CONTEXT_FT = 100  # the live path assumes a north-up image framed on the footprint + 100 ft


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
    segmented_building_sqft: float = Field(gt=0)
    detections: list[_Detection]


PROMPT = (
    "You inspect a north-up aerial image framed on a home plus 100 ft around it. Reply with JSON only: "
    '{"cv_roof_class": "CLASS_A_FORTIFIED|CLASS_A_IMPACT_4|CLASS_A_ASPHALT|WOOD_SHAKE_UNRATED", '
    '"cv_overhang_ft": feet of tree canopy over the 0-5 ft zone, "cv_zone0_clear": no combustible '
    'vegetation or mulch within 5 ft, "cv_zone1_no_shed": no detached combustible structure within 30 ft, '
    '"cv_confidence": 0-1, "segmented_building_sqft": roof area, "detections": [{"kind": '
    '"tree_overhang|shed", "bbox": [x0, y0, x1, y1] as 0-1 image fractions}]}.'
)


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


def _golden_for(apn_uid: str) -> tuple[PrivateVerificationLayer, dict]:
    for key in GOLDEN_KEYS:
        scenario = _load_golden()[key]
        if scenario["parcel_identity"]["apn_uid"] == apn_uid:
            features = [
                f for f in scenario["parcel_identity"]["geometries"]["features"] if f["properties"]["kind"] == "cv_detection"
            ]
            layer = PrivateVerificationLayer.model_validate(scenario["private_verification_layer"])
            return layer, {"type": "FeatureCollection", "features": features}
    raise KeyError(f"no golden scenario for apn_uid {apn_uid}")


def _media_type(image: bytes) -> str:
    return "image/png" if image.startswith(b"\x89PNG") else "image/jpeg"


def _live_inspect(footprint: list[list[float]], image: bytes, api_key: str) -> tuple[PrivateVerificationLayer, dict]:
    response = httpx.post(
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
    out = _VisionOutput.model_validate_json(response.json()["content"][0]["text"])

    footprint_m = to_metres(Polygon(footprint))
    assessor_sqft = footprint_m.area * SQM_TO_SQFT
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
        unpermitted_footprint_delta_sqft=round(out.segmented_building_sqft - assessor_sqft, 1),
    )
    return layer, {"type": "FeatureCollection", "features": features}


class AerialCVInspector:
    def inspect(
        self, apn_uid: str, footprint: list[list[float]], image: bytes | None
    ) -> tuple[PrivateVerificationLayer, dict]:
        """Return (verification layer, cv_detections FeatureCollection); golden when no image or key."""
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if image is None or not api_key:
            return _golden_for(apn_uid)
        try:
            return _live_inspect(footprint, image, api_key)
        except (httpx.HTTPError, ValidationError, KeyError, IndexError, ValueError):
            return _golden_for(apn_uid)
