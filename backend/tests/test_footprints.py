"""Footprint lookup: recorded Overpass responses (OSM, ODbL, recorded 2026-10-17), fallbacks and ring geometry."""

import asyncio
import json
from pathlib import Path

import httpx
import pytest
from shapely.geometry import Point, Polygon, shape

from app.models.schemas import FeatureCollection
from app.vision import footprints
from app.vision.footprints import default_square, fetch_footprint, parse_overpass
from app.vision.parcel_rings import SQM_TO_SQFT, build_rings, to_metres

FIXTURES = Path(__file__).parent / "fixtures"
# (fixture, lat, lng): Altadena is the S2 golden point; Escondido is a real house near the S3 address.
ALTADENA = ("overpass_altadena.json", 34.192, -118.1432)
ESCONDIDO = ("overpass_escondido.json", 33.129753, -117.0867045)


def _payload(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def _sqft(ring: list[list[float]]) -> float:
    return to_metres(Polygon(ring)).area * SQM_TO_SQFT


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.parametrize("fixture", [ALTADENA, ESCONDIDO])
def test_parse_overpass_picks_the_nearest_real_building(fixture):
    name, lat, lng = fixture
    payload = _payload(name)
    ring = parse_overpass(payload, lat, lng)
    assert ring is not None
    point = to_metres(Point(lng, lat))
    distances = {
        e["id"]: to_metres(Polygon([[n["lon"], n["lat"]] for n in e["geometry"]])).distance(point)
        for e in payload["elements"]
    }
    chosen = next(e["id"] for e in payload["elements"] if [[n["lon"], n["lat"]] for n in e["geometry"]] == ring)
    assert distances[chosen] == min(distances.values())
    assert 300 < _sqft(ring) < 50_000  # a real outline (Escondido's is ~10,900 sqft), not the 40x30 default
    assert _sqft(ring) != pytest.approx(1_800, rel=0.01)


def test_parse_overpass_prefers_the_building_containing_the_point():
    payload = _payload(ALTADENA[0])
    inside = next(
        e for e in payload["elements"] if len(e["geometry"]) > 5
    )  # a house with a non-trivial outline
    poly = Polygon([[n["lon"], n["lat"]] for n in inside["geometry"]])
    centre = poly.representative_point()
    assert parse_overpass(payload, centre.y, centre.x) == [[n["lon"], n["lat"]] for n in inside["geometry"]]


def test_parse_overpass_ignores_empty_and_open_ways():
    assert parse_overpass({"elements": []}, 34.0, -118.0) is None
    open_way = {"elements": [{"geometry": [{"lat": 0, "lon": 0}, {"lat": 0, "lon": 1}, {"lat": 1, "lon": 1}]}]}
    assert parse_overpass(open_way, 0, 0) is None


@pytest.mark.parametrize("fixture", [ALTADENA, ESCONDIDO])
def test_fetch_footprint_live_from_recorded_response(fixture):
    name, lat, lng = fixture
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.content.decode()
        seen["agent"] = request.headers["user-agent"]
        return httpx.Response(200, json=_payload(name))

    result = asyncio.run(fetch_footprint(lat, lng, client=_client(handler)))
    assert result.provenance.value_source == "LIVE" and result.provenance.field == "footprint"
    assert f"around%3A30%2C{lat}%2C{lng}" in seen["body"] and "way%5Bbuilding%5D" in seen["body"]
    assert seen["agent"] == footprints.USER_AGENT
    assert result.ring == parse_overpass(_payload(name), lat, lng)


@pytest.mark.parametrize(
    "handler",
    [
        lambda r: httpx.Response(200, json={"elements": []}),
        lambda r: httpx.Response(502, text="bad gateway"),
        lambda r: httpx.Response(200, text="<html>rate limited</html>"),
        lambda r: (_ for _ in ()).throw(httpx.ReadTimeout("slow", request=r)),
    ],
    ids=["no-building", "http-error", "non-json", "timeout"],
)
def test_fetch_footprint_falls_back_to_default_square(handler):
    result = asyncio.run(fetch_footprint(33.9, -118.3, client=_client(handler)))
    assert result.provenance.value_source == "DEFAULT"
    assert _sqft(result.ring) == pytest.approx(1_800, rel=0.01)
    assert Polygon(result.ring).contains(Point(-118.3, 33.9))


def test_fetch_footprint_leaves_a_shared_client_open():
    client = _client(lambda r: httpx.Response(200, json={"elements": []}))
    asyncio.run(fetch_footprint(33.9, -118.3, client=client))
    assert not client.is_closed


def test_default_square_area():
    assert _sqft(default_square(33.9, -118.3)) == pytest.approx(1_800, rel=0.01)


@pytest.mark.parametrize("fixture", [ALTADENA, ESCONDIDO])
def test_rings_on_a_real_polygon_are_correct(fixture):
    name, lat, lng = fixture
    ring = parse_overpass(_payload(name), lat, lng)
    result = build_rings(ring)
    FeatureCollection.model_validate(result)
    footprint = to_metres(Polygon(ring))
    z0, z1, z2 = (to_metres(shape(f["geometry"])) for f in result["features"])
    # Zones tile the 100 ft buffer exactly once, outward from the footprint (tolerance: 7-decimal rounding).
    whole = footprint.buffer(100 * 0.3048, join_style="mitre")
    union = footprint.union(z0).union(z1).union(z2)
    assert union.symmetric_difference(whole).area < 0.01 * whole.area
    for a, b in [(z0, z1), (z1, z2), (z0, z2)]:
        assert a.intersection(b).area < 1.0
    assert footprint.intersection(z0).area < 1.0
    assert z0.area < z1.area < z2.area
