"""NYC data path: recorded real responses (tests/fixtures/nyc, captured 2026-10-17) replayed through httpx.MockTransport.

Test lots, all real residential PLUTO lots with a basement code:
* Red Hook, Brooklyn: 5 Luquer Street, BBL 3005130048 (class A9, built 1920, partial basement)
* Hollis, Queens:     81-52 192 Street, BBL 4072730030 (class A1, built 1940, partial basement)
* Rockaway, Queens:   74-02 Beach Channel Drive, BBL 4160790031 (class A2, built 1920, Sandy-inundated)
The Hollis lot was picked by neighbourhood; whether it was flooded in Ida is not established by these records.
"""

import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar

import httpx
import pytest
from fastapi.testclient import TestClient

from app import http, pipeline
from app.ingestion.nyc import complaints311, dep_stormwater, dob, floodnet, footprints, geosearch, pluto
from app.ingestion.nyc.common import NycCaches, window_start
from app.ingestion.nyc.layer import fetch_nyc, is_nyc_county, resolve
from app.main import app
from app.models.schemas import NycLayer

FIXTURES = Path(__file__).parent / "fixtures"


def load(slug: str) -> dict:
    return json.loads((FIXTURES / "nyc" / f"{slug}.json").read_text())


def run(coro):
    return asyncio.run(coro)


class Replay:
    """Serves one recorded address by host+path. `fail` hosts or path fragments return 503; calls are counted."""

    GENERIC: ClassVar[dict[str, str]] = {
        "services.arcgis.com/XG15cJAlne2vxtgt": "nri_austin.json",
        "lfps.usgs.gov": "landfire_austin.json",
        "hdsc.nws.noaa.gov": "pfds_austin.txt",
    }

    def __init__(self, slug: str, fail: tuple[str, ...] = ()):
        self.data = load(slug)
        self.fail, self.calls = fail, []

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handle))

    def handle(self, request: httpx.Request) -> httpx.Response:
        key = f"{request.url.host}{request.url.path}"
        if "latitude between" in request.url.params.get("$where", ""):
            key += "#units"  # the PLUTO box query shares a path with the single-lot query
        self.calls.append(key)
        if any(f in key for f in self.fail):
            return httpx.Response(503, text="down")
        if key in self.data["responses"]:
            r = self.data["responses"][key]
            return httpx.Response(r["status"], text=r["text"])
        for prefix, name in self.GENERIC.items():
            if key.startswith(prefix):
                return httpx.Response(200, text=(FIXTURES / name).read_text())
        if request.url.host == "www.fema.gov":
            name = "openfema_policies_travis.json" if key.endswith("NfipPolicies") else "openfema_claims_travis.json"
            body = json.loads((FIXTURES / name).read_text())
            body["metadata"]["count"] = len(body.get("NfipClaims", body.get("NfipPolicies", [])))
            return httpx.Response(200, json=body)
        if request.url.host == "overpass-api.de":
            return httpx.Response(502, text="busy")
        raise AssertionError(f"unrecorded upstream {key}")


def fetch(slug: str, **kw):
    rep = Replay(slug, **kw)

    async def go():
        async with rep.client() as c:
            return await fetch_nyc(c, rep.data["address"], caches=NycCaches())

    return run(go()), rep


def status(res) -> dict[str, str]:
    return {p.field: p.value_source for p in res.provenance}


# --- three real addresses -----------------------------------------------------------------------------------


def test_red_hook_basement_home():
    res, _ = fetch("red_hook")
    n = res.layer
    assert (n.bbl, n.bin, n.borough) == ("3005130048", "3008282", "Brooklyn")
    assert (n.bldg_class, n.year_built, n.num_floors) == ("A9", 1920, 2.0)
    assert (n.basement_code, n.basement_type) == ("2", "PARTIAL")
    assert (n.ground_elevation_ft, n.roof_height_ft) == (10.0, pytest.approx(23.4025517))
    assert n.evacuation_zone == "2" and n.sandy_inundated is False
    assert (n.floodnet_events_500m_5y, n.floodnet_max_depth_in) == (3, 2.01)
    assert n.catch_basins_150m == 25 and n.dob_open_violations == 0 and n.dob_cellar_conversion_flag is False
    assert n.sewer_backup_311_500m_5y > 0 and n.street_flooding_311_500m_5y > 0
    assert res.layer.model_dump() == load("red_hook")["expected_layer"]


def test_hollis_has_no_floodnet_sensor_and_says_so():
    res, _ = fetch("hollis")
    n = res.layer
    assert (n.bbl, n.borough, n.basement_type, n.year_built) == ("4072730030", "Queens", "PARTIAL", 1940)
    assert n.evacuation_zone == "X" and n.ground_elevation_ft == 94.0
    assert n.floodnet_events_500m_5y is None and n.floodnet_max_depth_in is None  # no sensor, not "zero floods"
    s = {p.field: p for p in res.provenance}
    assert s["nyc.floodnet_events_500m_5y"].value_source == "UNAVAILABLE"
    assert "no sensor" in s["nyc.floodnet_events_500m_5y"].source_name
    assert n.sewer_backup_311_500m_5y == 20 and n.street_flooding_311_500m_5y == 2


def test_rockaway_surge_zone_house():
    res, _ = fetch("rockaway")
    n = res.layer
    assert (n.bbl, n.bin, n.ground_elevation_ft) == ("4160790031", "4303278", 7.0)
    assert n.sandy_inundated is True and n.evacuation_zone == "1"
    assert (n.floodnet_events_500m_5y, n.floodnet_max_depth_in) == (3, 9.21)


def test_every_recorded_layer_validates_against_the_contract_model():
    for slug in ("red_hook", "hollis", "rockaway"):
        NycLayer.model_validate(load(slug)["expected_layer"])


def test_limited_scenario_is_unavailable_never_guessed_and_the_rest_are_live():
    res, _ = fetch("rockaway")
    got = {d.scenario: d.flood_class for d in res.layer.dep_stormwater}
    assert got["LIMITED_CURRENT"] == "UNAVAILABLE"
    assert set(got) == set(dep_stormwater.SCENARIOS) and "UNAVAILABLE" not in {
        v for k, v in got.items() if k != "LIMITED_CURRENT"
    }
    assert status(res)["nyc.dep_stormwater"] == "LIVE"


def test_every_nyc_field_has_provenance():
    res, _ = fetch("red_hook")
    expected = {f"nyc.{f}" for f in NycLayer.model_fields}
    assert expected <= set(status(res))
    assert set(status(res).values()) == {"LIVE"}


# --- failures degrade one field at a time ------------------------------------------------------------------------


def test_one_failing_source_nulls_its_fields_only(caplog):
    with caplog.at_level("WARNING"):
        res, _ = fetch("red_hook", fail=("3h2n-5cm9", "w9ak-ipjd"))
    n, s = res.layer, status(res)
    assert n.dob_open_violations is None and n.dob_cellar_conversion_flag is None
    assert s["nyc.dob_open_violations"] == s["nyc.dob_cellar_conversion_flag"] == "UNAVAILABLE"
    assert n.bbl == "3005130048" and n.catch_basins_150m == 25 and s["nyc.catch_basins_150m"] == "LIVE"
    assert any("dob" in r.getMessage() for r in caplog.records)


def test_stormwater_scenario_failure_is_that_scenario_only():
    res, _ = fetch("red_hook", fail=("Moderate_Flood_Map_Current_Sea_Levels",))
    got = {d.scenario: d.flood_class for d in res.layer.dep_stormwater}
    assert got["MODERATE_CURRENT"] == "UNAVAILABLE" and got["EXTREME_2080"] == "NONE"
    assert status(res)["nyc.dep_stormwater"] == "UNAVAILABLE"


def test_geosearch_down_means_no_nyc_layer_not_an_error():
    res, _ = fetch("red_hook", fail=("geosearch.planninglabs.nyc",))
    assert res is None


def test_second_request_is_served_from_the_caches():
    rep = Replay("rockaway")
    caches = NycCaches()

    async def go():
        async with rep.client() as c:
            await fetch_nyc(c, rep.data["address"], caches=caches)
            first = len(rep.calls)
            await fetch_nyc(c, rep.data["address"], caches=caches)
            return first

    first = run(go())
    assert first >= 12 and len(rep.calls) == first


# --- parsers ----------------------------------------------------------------------------------------------------


def test_geosearch_parses_bbl_bin_and_point():
    d = geosearch.parse_geosearch(json.loads(load("red_hook")["responses"]["geosearch.planninglabs.nyc/v2/search"]["text"]))
    assert (d.bbl, d.bin, d.borough) == ("3005130048", "3008282", "Brooklyn")
    assert d.lat == pytest.approx(40.679, abs=0.01) and d.lng == pytest.approx(-74.005, abs=0.01)
    with pytest.raises(geosearch.GeoSearchNoMatch):
        geosearch.parse_geosearch({"features": []})


def test_geosearch_fuzzy_match_for_a_non_nyc_address_is_rejected():
    """Recorded live: "10001 Main St, Dallas, TX" fuzzy-matched "190C MAIN STREET, Bronx" at confidence 0.8."""
    dallas = json.loads((FIXTURES / "nyc" / "geosearch_dallas.json").read_text())
    assert geosearch.parse_geosearch(dallas).borough == "Bronx"  # the parse alone would accept it
    assert not geosearch.agrees_with_text("10001 Main St, Dallas, TX", dallas)

    def handler(request):
        return httpx.Response(200, json=dallas)

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            await geosearch.search(c, "10001 Main St, Dallas, TX")

    with pytest.raises(geosearch.GeoSearchNoMatch):
        run(go())
    for slug in ("red_hook", "hollis", "rockaway"):  # the real NYC matches still agree
        d = load(slug)
        assert geosearch.agrees_with_text(d["address"], json.loads(d["responses"]["geosearch.planninglabs.nyc/v2/search"]["text"]))


def test_a_text_match_far_from_the_supplied_point_is_ignored(caplog):
    rep = Replay("red_hook")

    async def go():
        async with rep.client() as c:  # Red Hook text, but the caller says the point is in Rockaway: ~15 km away
            return await resolve(c, rep.data["address"], 40.5910, -73.8025, NycCaches())

    with caplog.at_level("WARNING"):
        got = run(go())
    assert got is None  # the reverse lookup is not recorded as a hit either: both attempts fail or disagree
    assert any("ignored" in r.getMessage() for r in caplog.records)


def test_partial_stormwater_failure_is_not_cached_and_is_retried():
    rep = Replay("red_hook", fail=("Moderate_Flood_Map_Current_Sea_Levels",))
    caches = NycCaches()

    async def go():
        async with rep.client() as c:
            first = await fetch_nyc(c, rep.data["address"], caches=caches)
            rep.fail = ()  # the layer recovers
            second = await fetch_nyc(c, rep.data["address"], caches=caches)
            return first, second

    first, second = run(go())
    assert {d.scenario: d.flood_class for d in first.layer.dep_stormwater}["MODERATE_CURRENT"] == "UNAVAILABLE"
    assert {d.scenario: d.flood_class for d in second.layer.dep_stormwater}["MODERATE_CURRENT"] == "NONE"


def test_pluto_bbl_form_and_basement_codes():
    assert pluto.pluto_bbl("1008350041") == "1008350041.00000000"
    for bad in ("123", "100835004x", "1008350041' or 1=1"):
        with pytest.raises(ValueError):
            pluto.pluto_bbl(bad)
    assert [pluto.basement_type(c) for c in ("0", "1", "2", "3", "4", "5", None, "9")] == [
        "NONE", "FULL", "PARTIAL", "FULL", "PARTIAL", "UNKNOWN", "UNKNOWN", "UNKNOWN",
    ]  # fmt: skip
    row = {"bbl": "1008350041.00000000", "yearbuilt": "0", "numfloors": "0", "bsmtcode": None}
    p = pluto.parse_pluto([row])
    assert (p.bbl, p.year_built, p.num_floors, p.basement_type) == ("1008350041", None, None, "UNKNOWN")


def test_residential_units_sum_only_lots_inside_the_radius():
    centre = (40.5910, -73.8025)
    rows = [
        {"latitude": "40.5910", "longitude": "-73.8025", "unitsres": "2"},  # on the point
        {"latitude": "40.5940", "longitude": "-73.8025", "unitsres": "10"},  # about 334 m north
        {"latitude": "40.5960", "longitude": "-73.8025", "unitsres": "100"},  # about 556 m north: outside the circle
        {"latitude": "40.5911", "longitude": "-73.8026", "unitsres": "0"},
        {"latitude": None, "longitude": "-73.8", "unitsres": "7"},
        {"latitude": "40.5912", "longitude": "-73.8024", "unitsres": None},
    ]
    assert pluto.sum_units(rows, *centre) == 12


def test_residential_units_in_the_recorded_layers_and_box_query_shape():
    for slug, units in (("red_hook", 5257), ("hollis", 593), ("rockaway", 2852)):
        assert load(slug)["expected_layer"]["residential_units_500m"] == units
    seen = {}

    def handler(request):
        seen.update(request.url.params)
        return httpx.Response(200, json=[{"latitude": "40.6", "longitude": "-73.8", "unitsres": "3"}])

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await pluto.fetch_units_nearby(c, 40.6, -73.8)

    assert run(go()) == 3
    assert "latitude between" in seen["$where"] and "longitude between" in seen["$where"]

    def capped(request):
        return httpx.Response(200, json=[{"latitude": "40.6", "longitude": "-73.8", "unitsres": "1"}] * pluto.UNITS_MAX_ROWS)

    async def go_capped():
        async with httpx.AsyncClient(transport=httpx.MockTransport(capped)) as c:
            await pluto.fetch_units_nearby(c, 40.6, -73.8)

    with pytest.raises(ValueError):  # a truncated box would undercount silently
        run(go_capped())


def test_footprint_ring_is_the_largest_outer_ring_and_closed():
    row = json.loads(load("rockaway")["responses"]["data.cityofnewyork.us/resource/5zhs-2jue.json"]["text"])[0]
    ring = footprints.outer_ring(row["the_geom"])
    assert ring[0] == ring[-1] and len(ring) >= 4
    with pytest.raises(ValueError):
        footprints.outer_ring({"type": "Point", "coordinates": [0, 0]})


def test_dep_classifier_on_recorded_hits_at_flooded_points():
    for rec in json.loads((FIXTURES / "nyc" / "dep_points.json").read_text()):
        src = next(s for s in dep_stormwater.SOURCES if s.url == rec["url"] and s.fixed_class == rec["fixed_class"])
        got = dep_stormwater.classify(src, rec["response"])
        if rec["fixed_class"]:
            assert got == rec["fixed_class"]
        else:  # Flooding_C 1 nuisance, 2 deep and contiguous, 3 future high tide (not stormwater)
            assert got == {1: "NUISANCE", 2: "DEEP_CONTIGUOUS", 3: "NONE"}[rec["code"]]


def test_dep_classifier_edges():
    src = next(s for s in dep_stormwater.SOURCES if s.fixed_class is None)
    assert dep_stormwater.classify(src, {"features": []}) == "NONE"
    both = {"features": [{"attributes": {"Flooding_C": 1}}, {"attributes": {"Flooding_C": 2}}]}
    assert dep_stormwater.classify(src, both) == "DEEP_CONTIGUOUS"
    for bad in ({"error": {"code": 400}}, {}):
        with pytest.raises(ValueError):
            dep_stormwater.classify(src, bad)


def test_311_counts_both_descriptor_eras():
    rows = [
        {"descriptor": "Sewer Backup (Use Comments) (SA)", "n": "73"},
        {"descriptor": "Backup", "n": "8"},
        {"descriptor": "Street Flooding (SJ)", "n": "55"},
        {"descriptor": "Flooding on Street", "n": "2"},
        {"descriptor": "Catch Basin Clogged", "n": "5"},  # catch basin clogging is not a flood report
        {"descriptor": "Sewer Odor (SA2)", "n": "9"},
    ]
    assert complaints311.parse_complaints(rows) == complaints311.Complaints(sewer_backup=81, street_flooding=57)


def test_five_year_window_and_311_query_shape():
    assert window_start(datetime(2026, 10, 17, tzinfo=UTC)) == "2021-10-18T00:00:00"
    seen = {}

    def handler(request):
        seen.update(request.url.params)
        return httpx.Response(200, json=[])

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            await complaints311.fetch_complaints(c, 40.6, -73.8)

    run(go())
    assert "within_circle(location,40.6,-73.8,500)" in seen["$where"]
    assert "complaint_type in('Sewer','Sewer Maintenance')" in seen["$where"]


def test_dob_cellar_conversion_needs_cellar_work_and_more_units():
    cellar = {"work_on_floor": "Basement/Sub-basement, Cellar, Floor Number(s) 1", "existing_dwelling_units": "1", "proposed_dwelling_units": "2"}
    assert dob.cellar_conversion([cellar]) is True
    assert dob.cellar_conversion([{**cellar, "proposed_dwelling_units": "1"}]) is False
    assert dob.cellar_conversion([{**cellar, "work_on_floor": "Floor Number(s) 2"}]) is False
    assert dob.cellar_conversion([{"work_on_floor": "Cellar", "existing_dwelling_units": None}]) is False
    for bad in ("12", "30082828282", "3008282' or 1=1"):
        with pytest.raises(ValueError):
            dob.check_bin(bad)


def test_floodnet_no_sensors_is_not_zero_events():
    assert floodnet.parse_events(0, []) == floodnet.FloodNetSummary(0, 0, None)
    assert floodnet.parse_events(2, [{"n": "0", "max_depth": None}]) == floodnet.FloodNetSummary(2, 0, None)
    assert floodnet.parse_events(2, [{"n": "4", "max_depth": "9.21"}]).max_depth_in == 9.21
    with pytest.raises(ValueError):
        floodnet._sensor_list(["ok-1", "bad'id"])


# --- routing into the pipeline ------------------------------------------------------------------------------------


def test_nyc_county_routing_and_address_hint():
    assert all(is_nyc_county(f) for f in ("36005", "36047", "36061", "36081", "36085"))
    assert not is_nyc_county("48453") and not is_nyc_county(None)
    for yes in ("5 Luquer Street, Brooklyn, NY", "123 Main St, Queens", "1 Broadway, New York, NY 10004", "9 X St 11231"):
        assert pipeline.NYC_HINT.search(yes), yes
    for no in (
        "1100 Congress Ave, Austin, TX 78701",
        "412 Bayou Rd, Jefferson Parish, LA 70072",
        "10001 Main St, Dallas, TX",  # a street number that looks like a ZIP
        "200 Franklin Ave, Garden City, NY 11530",  # Nassau ZIP, not NYC
    ):
        assert not pipeline.NYC_HINT.search(no), no


def test_non_nyc_point_never_calls_the_nyc_path():
    async def go():
        return await pipeline._nyc("1100 Congress Ave, Austin, TX", 30.2672, -97.7431, "48453")

    assert run(go()) is None


def test_red_hook_address_builds_a_full_response_with_the_nyc_layer(monkeypatch):
    rep = Replay("red_hook")
    monkeypatch.setattr(http, "_client", rep.client())
    monkeypatch.setattr(pipeline, "NYC_CACHES", NycCaches())
    built = run(pipeline.build_parcel_for_address("5 Luquer Street, Brooklyn, NY"))
    r = built.parcel
    assert (r.parcel_identity.state, r.parcel_identity.county_fips) == ("NY", "36047")
    assert r.nyc is not None and r.nyc.bbl == "3005130048" and r.nyc.basement_type == "PARTIAL"
    assert r.parcel_identity.year_built == 1920
    prov = {p.field: p for p in r.input_provenance}
    assert prov["footprint"].value_source == "LIVE" and "Building Footprints" in prov["footprint"].source_name
    assert prov["year_built"].value_source == "LIVE" and "PLUTO" in prov["year_built"].source_name
    assert prov["nyc.bbl"].value_source == "LIVE"
    ring = r.parcel_identity.geometries.features[0].geometry.coordinates[0]
    row = json.loads(rep.data["responses"]["data.cityofnewyork.us/resource/5zhs-2jue.json"]["text"])[0]
    assert [list(p) for p in ring] == footprints.outer_ring(row["the_geom"])
    assert "overpass-api.de/api/interpreter" not in rep.calls  # OSM is not asked when the city has the outline


def test_address_only_post_returns_the_nyc_layer(monkeypatch):
    rep = Replay("rockaway")
    monkeypatch.setattr(http, "new_client", rep.client)
    monkeypatch.setattr(pipeline, "NYC_CACHES", NycCaches())
    with TestClient(app) as client:
        resp = client.post("/v1/parcel/score", json={"address": rep.data["address"]})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["nyc"]["bbl"] == "4160790031" and body["nyc"]["sandy_inundated"] is True
    assert body["parcel_identity"]["state"] == "NY" and 300 <= body["actuarial_breakdown"]["resili_score"] <= 850


# --- live (RS_LIVE=1) -----------------------------------------------------------------------------------------------


@pytest.mark.live
def test_live_nyc_sources_for_the_rockaway_house():
    assert os.environ.get("RS_LIVE") == "1"

    async def go():
        async with http.new_client() as c:
            return await fetch_nyc(c, "74-02 Beach Channel Drive, Queens, NY", caches=NycCaches())

    res = run(go())
    assert res is not None
    n, s = res.layer, status(res)
    assert (n.bbl, n.borough) == ("4160790031", "Queens")
    assert n.basement_type in {"NONE", "FULL", "PARTIAL", "UNKNOWN"} and n.year_built == 1920
    assert n.sandy_inundated is True and n.evacuation_zone == "1"
    assert n.ground_elevation_ft is not None and n.catch_basins_150m > 0
    assert n.sewer_backup_311_500m_5y > 0
    live = [f for f, v in s.items() if v == "LIVE"]
    assert len(live) >= len(s) - 2, {f: v for f, v in s.items() if v != "LIVE"}
