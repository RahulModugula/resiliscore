"""Vision: ring geometry, zone classifier and the inspector (golden fallback + mocked live path)."""

import asyncio
import json
from pathlib import Path

import httpx
import pytest
from shapely.geometry import Polygon, shape

from app.models.schemas import FeatureCollection
from app.vision.cv_inspector import AerialCVInspector, classify_zone
from app.vision.footprints import default_square
from app.vision.parcel_rings import FT_TO_M, SQM_TO_SQFT, build_rings, to_lnglat, to_metres

GOLDEN = json.loads((Path(__file__).resolve().parents[2] / "contracts" / "golden_scenarios.json").read_text())
KEYS = ["SCENARIO_1_LA_FLOOD", "SCENARIO_2_CA_WUI", "SCENARIO_3_ESCONDIDO_HITL"]
S2 = "SCENARIO_2_CA_WUI"


def _features(key: str, kind: str) -> list[dict]:
    return [f for f in GOLDEN[key]["parcel_identity"]["geometries"]["features"] if f["properties"]["kind"] == kind]


def _footprint(key: str) -> list[list[float]]:
    return _features(key, "building_footprint")[0]["geometry"]["coordinates"][0]


def _square_lnglat(side_m: float) -> list[list[float]]:
    x, y = -2_000_000.0, 1_500_000.0  # arbitrary point in EPSG:5070
    sq = Polygon([(x, y), (x + side_m, y), (x + side_m, y + side_m), (x, y + side_m)])
    return [list(c) for c in to_lnglat(sq).exterior.coords]


def _rings_m(footprint):
    return [to_metres(shape(f["geometry"])) for f in build_rings(footprint)["features"]]


def test_ring_areas_match_analytic_values_for_square():
    side = 12.0
    rings = _rings_m(_square_lnglat(side))
    edges = [0, 5 * FT_TO_M, 30 * FT_TO_M, 100 * FT_TO_M]
    for ring, inner, outer in zip(rings, edges, edges[1:]):
        expected = (side + 2 * outer) ** 2 - (side + 2 * inner) ** 2
        assert ring.area == pytest.approx(expected, rel=0.02)


def test_rings_are_disjoint_and_nested():
    footprint = to_metres(Polygon(_square_lnglat(12.0)))
    z0, z1, z2 = _rings_m(_square_lnglat(12.0))
    # Tolerances absorb the 7-decimal coordinate rounding (1e-7 deg ~ 1 cm).
    for a, b in [(z0, z1), (z1, z2), (z0, z2)]:
        assert a.intersection(b).area < 0.5
    assert footprint.intersection(z0).area < 0.5
    assert z0.distance(z1) < 0.05 and z1.distance(z2) < 0.05  # adjacent, so nested outward


def test_rings_serialise_to_contract_featurecollection():
    FeatureCollection.model_validate(build_rings(_square_lnglat(12.0)))


@pytest.mark.parametrize("key", KEYS)
def test_golden_footprints_produce_valid_rings_near_centroid(key):
    lng, lat = GOLDEN[key]["parcel_identity"]["centroid"]
    result = build_rings(_footprint(key))
    assert [f["properties"]["kind"] for f in result["features"]] == [
        "zone_0_ring_0_5ft", "zone_1_ring_5_30ft", "zone_2_ring_30_100ft",
    ]  # fmt: skip
    for feature in result["features"]:
        geom = shape(feature["geometry"])
        assert geom.is_valid and not geom.is_empty
        assert abs(geom.centroid.x - lng) < 5e-4 and abs(geom.centroid.y - lat) < 5e-4
    FeatureCollection.model_validate(result)


@pytest.mark.parametrize("key", KEYS)
def test_rings_match_golden_ring_areas(key):
    built = _rings_m(_footprint(key))
    for ring, kind in zip(built, ["zone_0_ring_0_5ft", "zone_1_ring_5_30ft", "zone_2_ring_30_100ft"]):
        golden = to_metres(shape(_features(key, kind)[0]["geometry"]))
        assert ring.area == pytest.approx(golden.area, rel=0.05)


def test_zone_classifier_puts_s2_shed_in_zone_1_and_canopy_in_zone_0():
    detections = _features(S2, "cv_detection")
    by_label = {f["properties"]["label"]: f["geometry"]["coordinates"][0] for f in detections}
    shed = next(v for k, v in by_label.items() if "shed" in k)
    canopy = next(v for k, v in by_label.items() if "canopy" in k)
    assert classify_zone(_footprint(S2), shed) == "zone_1_ring_5_30ft"
    assert classify_zone(_footprint(S2), canopy) == "zone_0_ring_0_5ft"


def test_zone_classifier_ignores_far_detection():
    far = [[-118.1420, 34.1930], [-118.1419, 34.1930], [-118.1419, 34.1931], [-118.1420, 34.1931], [-118.1420, 34.1930]]
    assert classify_zone(_footprint(S2), far) is None


def _apn(key: str) -> str:
    return GOLDEN[key]["parcel_identity"]["apn_uid"]


@pytest.mark.parametrize("key", KEYS)
def test_golden_parcel_without_image_serves_fixture_as_reference_parcel(key, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "set-but-unused")
    result = asyncio.run(AerialCVInspector().ainspect(_apn(key), _footprint(key), None))
    assert result.layer.model_dump() == GOLDEN[key]["private_verification_layer"]
    assert result.detections["features"] == _features(key, "cv_detection")
    assert {p.value_source for p in result.provenance} == {"REFERENCE_PARCEL"}
    layer, detections = AerialCVInspector().inspect(_apn(key), _footprint(key))
    assert layer == result.layer and detections == result.detections


def test_off_demo_parcel_without_image_is_unverified_not_borrowed():
    # The golden APN with a footprint elsewhere is an off-demo parcel: it must not get S2's result.
    elsewhere = default_square(33.9, -118.3)
    result = asyncio.run(AerialCVInspector().ainspect(_apn(S2), elsewhere, None))
    layer = result.layer
    assert layer.cv_confidence == 0 and layer.cv_roof_class == "WOOD_SHAKE_UNRATED"
    assert not (layer.cv_zone0_clear or layer.cv_zone1_no_shed or layer.cv_enclosed_eaves or layer.cv_ember_vents)
    assert result.detections["features"] == []
    assert {p.value_source for p in result.provenance} == {"UNAVAILABLE"}
    assert AerialCVInspector().inspect("00000000000000", elsewhere)[0] == layer


def test_no_api_key_with_image_is_unverified_for_off_demo_parcel(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    result = asyncio.run(AerialCVInspector().ainspect("00000000000000", default_square(33.9, -118.3), b"img"))
    assert result.layer.cv_confidence == 0


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _reply(text: str):
    return lambda _request: httpx.Response(200, json={"content": [{"text": text}]})


def _live(monkeypatch, handler, footprint=None, assessor_sqft=None):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    return asyncio.run(
        AerialCVInspector().ainspect(
            _apn(S2), footprint or _footprint(S2), b"\x89PNGx", assessor_sqft=assessor_sqft, client=_client(handler)
        )
    )


VISION_REPLY = {
    "cv_roof_class": "CLASS_A_ASPHALT", "cv_overhang_ft": 2.0, "cv_zone0_clear": True,
    "cv_zone1_no_shed": False, "cv_confidence": 0.8, "detections": [{"kind": "shed", "bbox": [0.7, 0.4, 0.8, 0.5]}],
}  # fmt: skip


def test_live_path_computes_footprint_delta_from_assessor_sqft(monkeypatch):
    footprint = _footprint(S2)
    footprint_sqft = to_metres(Polygon(footprint)).area * SQM_TO_SQFT
    result = _live(monkeypatch, _reply(json.dumps(VISION_REPLY)), assessor_sqft=footprint_sqft - 240)
    assert result.layer.unpermitted_footprint_delta_sqft == pytest.approx(240, abs=0.1)
    assert result.layer.cv_roof_class == "CLASS_A_ASPHALT"
    assert {p.value_source for p in result.provenance} == {"LIVE"}
    FeatureCollection.model_validate(result.detections)


def test_live_path_without_assessor_sqft_marks_delta_unavailable(monkeypatch):
    result = _live(monkeypatch, _reply(json.dumps(VISION_REPLY)))
    by_field = {p.field: p.value_source for p in result.provenance}
    assert by_field["unpermitted_footprint_delta_sqft"] == "UNAVAILABLE"
    assert by_field["cv_roof_class"] == "LIVE"


@pytest.mark.parametrize("wrap", ["```json\n{}\n```", "Here is the JSON:\n{}\nDone."])
def test_live_path_strips_code_fences_and_prose(monkeypatch, wrap):
    result = _live(monkeypatch, _reply(wrap.format(json.dumps(VISION_REPLY))))
    assert result.layer.cv_confidence == 0.8


@pytest.mark.parametrize("bad", ['{"cv_roof_class": "TILE"}', "not json"])
def test_live_path_invalid_output_falls_back_and_logs(monkeypatch, caplog, bad):
    result = _live(monkeypatch, _reply(bad))
    assert result.layer.model_dump() == GOLDEN[S2]["private_verification_layer"]
    assert "vision call failed" in caplog.text


def test_live_path_timeout_falls_back_and_logs(monkeypatch, caplog):
    def slow(request):
        raise httpx.ReadTimeout("slow", request=request)

    result = _live(monkeypatch, slow)
    assert result.layer.model_dump() == GOLDEN[S2]["private_verification_layer"]
    assert "vision call failed" in caplog.text


def test_live_failure_for_off_demo_parcel_is_unverified(monkeypatch):
    def slow(request):
        raise httpx.ReadTimeout("slow", request=request)

    result = _live(monkeypatch, slow, footprint=default_square(33.9, -118.3))
    assert result.layer.cv_confidence == 0


