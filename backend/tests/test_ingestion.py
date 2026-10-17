"""Ingestion tests: httpx.MockTransport with recorded real responses (tests/fixtures, captured 2026-10-17).

CI never touches the network; only the RS_LIVE=1 test does.
"""

import asyncio
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app import http, pipeline
from app.actuarial.optimizer import simulate
from app.cache import TTLCache
from app.ingestion import geocode, landfire, nfhl, noaa, nri, openfema, rasters, usgs_3dep
from app.ingestion.engine import Caches, SpatialIngestionEngine
from app.main import app

FIXTURES = Path(__file__).parent / "fixtures"
AUSTIN = {"lat": 30.2672, "lng": -97.7431, "county": "48453", "tract": "48453001103", "state": "TX"}
NOLA = (29.984, -90.153)  # S1 golden centroid


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text()


def run(coro):
    return asyncio.run(coro)


class Upstreams:
    """Serves the recorded Austin responses by host; any host can be failed or delayed. Counts calls."""

    def __init__(self, fail: set[str] = frozenset(), delay: dict[str, float] | None = None):
        self.fail, self.delay, self.calls = set(fail), delay or {}, []
        claims = json.loads(fixture("openfema_claims_travis.json"))
        claims["metadata"]["count"] = len(claims["NfipClaims"])
        self.claims = claims

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handle))

    async def handle(self, request: httpx.Request) -> httpx.Response:
        host, path = request.url.host, request.url.path
        self.calls.append((host, path))
        if self.delay.get(host):
            await asyncio.sleep(self.delay[host])
        if host in self.fail:
            return httpx.Response(502, text="bad gateway")
        if host == "geocoding.geo.census.gov":
            return httpx.Response(200, text=fixture("geocode_austin.json"))
        if host == "hazards.fema.gov":
            return httpx.Response(200, text=fixture("nfhl_austin.json"))
        if host == "services.arcgis.com":
            return httpx.Response(200, text=fixture("nri_austin.json"))
        if host == "epqs.nationalmap.gov":
            return httpx.Response(200, text=fixture("epqs_austin.json"))
        if host == "lfps.usgs.gov":
            return httpx.Response(200, text=fixture("landfire_austin.json"))
        if host == "hdsc.nws.noaa.gov":
            return httpx.Response(200, text=fixture("pfds_austin.txt"))
        if host == "www.fema.gov" and path.endswith("NfipClaims"):
            return httpx.Response(200, json=self.claims)
        if host == "www.fema.gov" and path.endswith("NfipPolicies"):
            return httpx.Response(200, text=fixture("openfema_policies_travis.json"))
        if host == "overpass-api.de":
            return httpx.Response(502, text="overpass busy")  # the footprint falls back to DEFAULT
        raise AssertionError(f"unexpected upstream {host}{path}")

    def hosts(self) -> set[str]:
        return {h for h, _ in self.calls}


def fetch(up: Upstreams, caches=None, timeout_s=2.5, lat=AUSTIN["lat"], lng=AUSTIN["lng"]):
    async def go():
        async with up.client() as client:
            engine = SpatialIngestionEngine(client, timeout_s=timeout_s, caches=caches or Caches())
            return await engine.fetch("1100 Congress Ave, Austin, TX 78701", lat, lng, AUSTIN["county"], "TX")

    return run(go())


def status(result) -> dict[str, str]:
    return {p.field: p.value_source for p in result.provenance}


# --- OpenFEMA ---------------------------------------------------------------------------------------------


def claim(paid=1000.0, cover=100000.0, bfe=9.0, diff=2.0):
    return {
        "amountPaidOnBuildingClaim": paid,
        "amountPaidOnContentsClaim": 0,
        "totalBuildingInsuranceCoverage": cover,
        "totalContentsInsuranceCoverage": 0,
        "baseFloodElevation": bfe,
        "elevationDifference": diff,
        "ratedFloodZone": "AE",
    }


def policy(effective="2020-01-01", months=12, cover=200000.0, count=1):
    start = datetime.fromisoformat(effective).replace(tzinfo=UTC)
    return {
        "policyEffectiveDate": start.isoformat().replace("+00:00", "Z"),
        "policyTerminationDate": (start + timedelta(days=365 * months // 12)).isoformat().replace("+00:00", "Z"),
        "policyCount": count,
        "totalBuildingInsuranceCoverage": cover,
        "totalContentsInsuranceCoverage": 0,
        "asOfDate": "2026-09-08T00:00:00.000Z",
    }


@pytest.mark.parametrize("missing", [None, "absent"])
def test_null_bfe_forces_elevation_difference_none_never_zero(missing):
    raw = claim(bfe=None, diff=3.5)
    if missing == "absent":
        del raw["baseFloodElevation"]
    c = openfema.normalize_claim(raw)
    assert c.bfe_ft is None
    assert c.elevation_difference_ft is None


def test_bfe_present_keeps_elevation_difference_including_real_zero():
    assert openfema.normalize_claim(claim(bfe=9.0, diff=0.0)).elevation_difference_ft == 0.0
    assert openfema.normalize_claim(claim(bfe=9.0, diff=2.0)).elevation_difference_ft == 2.0


def test_claim_params_page_with_skip_and_no_top_1000_cap():
    p = openfema.build_params("22051", skip=3000)
    assert p["$filter"] == "(countyCode eq '22051' and yearOfLoss ge 2010)"
    assert (p["$top"], p["$skip"]) == ("1000", "3000")
    assert "$skip" not in openfema.build_params("22051")


def test_policy_params_select_county_by_geoid_range_without_the_filters_that_503():
    p = openfema.policy_params("48453")
    assert p["$filter"] == "censusGeoid ge '484530000000' and censusGeoid lt '484540000000'"
    assert "$orderby" not in p and "policyEffectiveDate" not in p["$filter"]


def test_gamma_fit_recovers_known_parameters():
    import numpy as np

    x = np.random.default_rng(7).gamma(shape=2.0, scale=1 / 50.0, size=50_000)
    prior = openfema.gamma_mom_fit(list(x))
    assert prior.alpha == pytest.approx(2.0, rel=0.05)
    assert prior.beta == pytest.approx(50.0, rel=0.05)


@pytest.mark.parametrize("values", [[], [0.1], [0.2, 0.2], [0.0, 0.0, 0.3]])
def test_gamma_fit_rejects_degenerate_input(values):
    with pytest.raises(ValueError):
        openfema.gamma_mom_fit(values)


def test_loss_cost_is_paid_over_policy_years_and_coverage_years():
    claims = [claim(paid=1000), claim(paid=3000)]
    policies = [policy(cover=100000, months=12), policy(cover=300000, months=12)]
    agg = openfema.aggregate(claims, policies, claim_total=2)
    assert agg.paid_usd == 4000
    assert agg.policy_years == pytest.approx(2 * 365 / 365)
    assert agg.loss_cost_per_policy_year_usd == pytest.approx(4000 / 2)
    assert agg.mean_lcr == pytest.approx(4000 / (400000 * 365 / 365))
    assert agg.prior is not None and agg.prior.alpha / agg.prior.beta == pytest.approx(agg.mean_lcr)


def test_policy_term_is_clipped_to_the_claims_window_and_the_as_of_date():
    early = policy(effective="2009-07-01", months=12)  # half of it is before the 2010 window
    py, _ = openfema.policy_years_of(early)
    assert py == pytest.approx(0.5, abs=0.02)
    late = policy(effective="2026-03-08", months=12)  # as-of is 2026-09-08: about half a year of exposure
    assert openfema.policy_years_of(late)[0] == pytest.approx(0.5, abs=0.02)


def test_aggregate_without_exposure_keeps_the_claim_count_only():
    agg = openfema.aggregate([claim()], None, claim_total=7)
    assert (agg.claim_count, agg.mean_lcr, agg.policy_years) == (7, None, None)


def test_every_page_of_claims_is_fetched_not_just_the_first_1000():
    skips = []

    def handler(request):
        q = dict(request.url.params)
        if request.url.path.endswith("NfipPolicies"):
            return httpx.Response(200, json={"metadata": {}, "NfipPolicies": [policy()]})
        skip = int(q.get("$skip", 0))
        skips.append(skip)
        rows = [claim(paid=1)] * min(1000, 2500 - skip)
        return httpx.Response(200, json={"metadata": {"count": 2500}, "NfipClaims": rows})

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await openfema.fetch_county_aggregate(c, "48453")

    agg = run(go())
    assert sorted(set(skips)) == [0, 1000, 2000]
    assert agg.claim_count == 2500 and agg.paid_usd == 2500


def test_county_too_big_for_policy_paging_still_returns_claims_without_a_rate():
    def handler(request):
        if request.url.path.endswith("NfipPolicies"):
            return httpx.Response(200, json={"metadata": {}, "NfipPolicies": [policy()] * 1000})  # never a short page
        return httpx.Response(200, json={"metadata": {"count": 3}, "NfipClaims": [claim()] * 3})

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await openfema.fetch_county_aggregate(c, "48453")

    agg = run(go())
    assert agg.claim_count == 3 and agg.mean_lcr is None


def test_bad_county_fips_rejected():
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200))) as c:
            await openfema.fetch_county_aggregate(c, "22051' or 1 eq 1")

    with pytest.raises(ValueError):
        run(go())


def test_openfema_retries_a_503_then_succeeds():
    n = {"calls": 0}

    def handler(request):
        n["calls"] += 1
        if n["calls"] == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"ok": 1})

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await openfema._get_json(c, openfema.POLICIES_URL, {})

    assert run(go()) == {"ok": 1}
    assert n["calls"] == 2


# --- USGS EPQS --------------------------------------------------------------------------------------------


def test_parse_epqs_value_and_nodata():
    assert usgs_3dep.parse_epqs({"value": 7.2, "resolution": 1}) == 7.2
    assert usgs_3dep.parse_epqs({"value": -1.97}) == -1.97  # below sea level is valid
    for bad in ({"value": -1000000}, {}, {"value": "n/a"}):
        with pytest.raises(ValueError):
            usgs_3dep.parse_epqs(bad)


def test_ffe_and_freeboard_match_scenario_1():
    e = usgs_3dep.compute_elevations(7.2, 9.0, foundation_offset_ft=6.0)
    assert (e.usgs_lag_ft, e.est_ffe_ft) == (7.2, 13.2)
    assert e.freeboard_delta_h_ft == pytest.approx(4.2)


def test_freeboard_none_without_bfe():
    assert usgs_3dep.compute_elevations(1342.0, None).freeboard_delta_h_ft is None


# --- Census geocoder, NFHL, NRI, LANDFIRE, NOAA -------------------------------------------------------------


def test_geocoder_recorded_austin_response():
    g = geocode.parse_geocode(json.loads(fixture("geocode_austin.json")))
    assert (g.state, g.county_fips, g.tract_fips) == ("TX", "48453", "48453000700")
    assert (g.lat, g.lng) == pytest.approx((30.2672, -97.7431), abs=0.01)


def test_geocoder_no_match_and_garbage_raise():
    with pytest.raises(geocode.GeocodeError):
        geocode.parse_geocode({"result": {"addressMatches": []}})
    with pytest.raises(geocode.GeocodeError):
        geocode.parse_geocode({"unexpected": 1})


def test_nfhl_no_bfe_sentinel_becomes_none():
    z = nfhl.parse_nfhl(json.loads(fixture("nfhl_austin.json")))
    assert (z.zone, z.sfha, z.bfe_ft) == ("X", False, None)


def test_nfhl_real_bfe_and_unmapped_point():
    body = {"features": [{"attributes": {"FLD_ZONE": "AE", "SFHA_TF": "T", "STATIC_BFE": 9.0, "ZONE_SUBTY": None}}]}
    assert nfhl.parse_nfhl(body).bfe_ft == 9.0
    with pytest.raises(nfhl.NfhlNoCoverage):
        nfhl.parse_nfhl({"features": []})


def test_nri_rates_are_building_eal_over_building_value():
    t = nri.parse_nri(json.loads(fixture("nri_austin.json")))
    a = json.loads(fixture("nri_austin.json"))["features"][0]["attributes"]
    assert t.tract_fips == AUSTIN["tract"] and t.version == "December 2025"
    assert t.rates["IFLD"] == pytest.approx(a["IFLD_EALB"] / a["BUILDVALUE"])
    assert t.rates["CFLD"] == 0.0  # null EAL means the peril is absent
    assert t.total_rate == pytest.approx(sum(t.rates.values())) and 0 < t.total_rate < 0.01


def test_nri_missing_building_value_is_an_error_not_a_zero_division():
    with pytest.raises(ValueError):
        nri.parse_nri({"features": [{"attributes": {"TRACTFIPS": "1", "BUILDVALUE": 0}}]})


def test_landfire_codes_and_nodata():
    assert [landfire.fuel_code(v) for v in (91, 99, 101, 122, 147, 165, 189, 204)] == [
        "NB1", "NB9", "GR1", "GS2", "SH7", "TU5", "TL9", "SB4",
    ]  # fmt: skip
    with pytest.raises(ValueError):
        landfire.parse_landfire(json.loads(fixture("landfire_austin.json")))  # recorded NoData
    with pytest.raises(ValueError):
        landfire.fuel_code(55)


def test_noaa_pfds_24h_100yr_from_recorded_austin_table():
    assert noaa.parse_pfds(fixture("pfds_austin.txt")) == 12.7
    with pytest.raises(ValueError):
        noaa.parse_pfds("nothing here")


# --- cache ------------------------------------------------------------------------------------------------


def test_ttl_cache_expires_and_never_stores_failures():
    now = [0.0]
    cache: TTLCache[int] = TTLCache(ttl_s=10, clock=lambda: now[0])
    n = {"calls": 0}

    async def factory():
        n["calls"] += 1
        if n["calls"] == 1:
            raise RuntimeError("upstream down")
        return n["calls"]

    async def go():
        with pytest.raises(RuntimeError):
            await cache.get_or_set("k", factory)
        assert await cache.get_or_set("k", factory) == 2  # the failure was not cached
        assert await cache.get_or_set("k", factory) == 2  # hit
        now[0] = 11.0
        assert await cache.get_or_set("k", factory) == 3  # expired

    run(go())
    assert n["calls"] == 3


# --- engine -----------------------------------------------------------------------------------------------


def test_golden_centroid_is_served_exactly_without_network_as_reference_parcel():
    up = Upstreams()
    result = fetch(up, lat=NOLA[0], lng=NOLA[1])
    assert up.calls == []
    assert result.layer == rasters.golden_sites()[0].response.public_hazard_layer
    assert {p.value_source for p in result.provenance} == {"REFERENCE_PARCEL"}
    assert result.indicative_only is False


def test_austin_all_live_uses_real_data_and_marks_what_is_not_live():
    up = Upstreams()
    r = fetch(up)
    s, layer = status(r), r.layer
    assert (layer.fema_flood_zone, layer.bfe_ft_navd88) == ("X", None)
    assert layer.usgs_lag_ft == pytest.approx(487.0965, abs=1e-3)
    assert layer.freeboard_delta_h_ft == 0.0  # contract float for "no BFE"
    assert layer.noaa_atlas15_p24h_100yr_in == 12.7
    assert layer.openfema_tract_claim_count == len(up.claims["NfipClaims"])
    assert r.tract_prior_lcr == pytest.approx(nri.parse_nri(json.loads(fixture("nri_austin.json"))).total_rate)
    assert s["fema_flood_zone"] == s["usgs_lag_ft"] == s["tract_prior_lcr"] == "LIVE"
    assert s["noaa_atlas15_p24h_100yr_in"] == "LIVE" and s["openfema_tract_claim_count"] == "LIVE"
    # LANDFIRE returned NoData at this urban point, and these layers have no live source.
    assert s["landfire_fbfm40_code"] == "DEFAULT" and layer.landfire_fbfm40_code == "NB1"
    assert {s[f] for f in ("hand_rel_elev_ft", "twi_index", "slope_deg", "wui_class", "atlas15_cmip6_mult")} == {
        "DEFAULT"
    }
    assert s["wrc_burn_probability"] == "UNAVAILABLE" and layer.wrc_burn_probability is None
    assert s["est_ffe_ft"] == "DEFAULT"
    assert r.indicative_only is False  # every key input is LIVE
    assert r.vintages["NOAA_PFDS"] == "Atlas14"


def test_austin_has_nothing_borrowed_from_a_golden_parcel_when_every_source_fails():
    up = Upstreams(fail={"hazards.fema.gov", "services.arcgis.com", "epqs.nationalmap.gov", "lfps.usgs.gov",
                         "hdsc.nws.noaa.gov", "www.fema.gov"})  # fmt: skip
    r = fetch(up)
    d = rasters.NATIONAL_DEFAULTS
    assert r.layer.fema_flood_zone == d["fema_flood_zone"] and r.layer.wui_class == "NON_WUI"
    assert r.layer.landfire_fbfm40_code == d["landfire_fbfm40_code"]
    assert r.layer.noaa_atlas15_p24h_100yr_in == d["noaa_atlas15_p24h_100yr_in"]
    assert r.tract_prior_lcr == d["tract_prior_lcr"]
    s = status(r)
    assert s["usgs_lag_ft"] == s["bfe_ft_navd88"] == s["openfema_tract_claim_count"] == "UNAVAILABLE"
    assert s["fema_flood_zone"] == s["tract_prior_lcr"] == "DEFAULT"
    assert "REFERENCE_PARCEL" not in s.values()
    assert r.indicative_only is True
    for site in rasters.golden_sites():  # no golden value leaks in
        g = site.response.public_hazard_layer
        assert r.layer.landfire_fbfm40_code != g.landfire_fbfm40_code or g.landfire_fbfm40_code == "NB1"
        assert r.layer.hand_rel_elev_ft != g.hand_rel_elev_ft


def test_one_failing_source_leaves_the_others_live_and_flags_indicative():
    r = fetch(Upstreams(fail={"epqs.nationalmap.gov"}))
    s = status(r)
    assert s["usgs_lag_ft"] == "UNAVAILABLE" and s["fema_flood_zone"] == "LIVE"
    assert r.indicative_only is True


def test_slow_source_times_out_to_unavailable_and_failures_are_logged(caplog):
    with caplog.at_level("WARNING", logger="app.ingestion.engine"):
        r = fetch(Upstreams(delay={"hdsc.nws.noaa.gov": 0.5}), timeout_s=0.1)
    assert status(r)["noaa_atlas15_p24h_100yr_in"] == "DEFAULT"
    assert any("noaa" in rec.getMessage() for rec in caplog.records)


def test_second_request_for_the_same_place_hits_the_caches():
    caches, up = Caches(), Upstreams()
    fetch(up, caches=caches)
    first = len(up.calls)
    fetch(up, caches=caches)
    assert first >= 6 and len(up.calls) == first  # every source is cached; no new upstream call


def test_slow_county_aggregate_does_not_block_and_lands_in_the_cache():
    caches, up = Caches(), Upstreams(delay={"www.fema.gov": 0.3})

    async def go():
        async with up.client() as client:
            engine = SpatialIngestionEngine(client, timeout_s=0.1, caches=caches)
            first = await engine.fetch("a", AUSTIN["lat"], AUSTIN["lng"], AUSTIN["county"], "TX")
            await asyncio.sleep(0.8)  # the background load finishes
            second = await engine.fetch("a", AUSTIN["lat"], AUSTIN["lng"], AUSTIN["county"], "TX")
            return first, second

    first, second = run(go())
    assert status(first)["openfema_tract_claim_count"] == "UNAVAILABLE"
    assert status(second)["openfema_tract_claim_count"] == "LIVE"


def test_engine_geocodes_an_address_alone():
    async def go():
        async with Upstreams().client() as client:
            return await SpatialIngestionEngine(client, caches=Caches()).geocode("1100 Congress Ave Austin TX 78701")

    g = run(go())
    assert g.county_fips == "48453" and g.state == "TX"


# --- end to end: an Austin TX address, no CA data ----------------------------------------------------------


def test_austin_address_scores_end_to_end_with_provenance_and_no_ca_data(monkeypatch):
    up = Upstreams()
    monkeypatch.setattr(http, "new_client", up.client)
    with TestClient(app) as client:
        resp = client.post("/v1/parcel/score", json={"address": "1100 Congress Ave, Austin, TX 78701"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    ident = body["parcel_identity"]
    assert (ident["state"], ident["county_fips"]) == ("TX", "48453")
    assert ident["centroid"] == pytest.approx([-97.7431, 30.2672], abs=0.01)
    assert body["indicative_only"] is True
    by_field = {p["field"]: p for p in body["input_provenance"]}
    assert by_field["footprint"]["value_source"] == "DEFAULT"  # Overpass 502 in the recording
    assert by_field["cv_confidence"]["value_source"] != "LIVE"
    assert body["private_verification_layer"]["cv_confidence"] == 0
    assert by_field["fema_flood_zone"]["value_source"] == "LIVE"
    assert by_field["rcv_usd"]["value_source"] == "DEFAULT"
    hazard = body["public_hazard_layer"]
    assert hazard["wui_class"] == "NON_WUI" and hazard["landfire_fbfm40_code"] == "NB1"
    assert "CAL_FIRE_FHSZ" not in body["regulatory_compliance"]["dataset_vintages"]
    assert {"geocoding.geo.census.gov", "hazards.fema.gov", "overpass-api.de"} <= up.hosts()
    dumped = json.dumps(body)
    assert "Escondido" not in dumped and "Altadena" not in dumped and "SCENARIO_" not in dumped
    assert 300 <= body["actuarial_breakdown"]["resili_score"] <= 850


def test_unknown_address_is_404_not_a_golden_fallback(monkeypatch):
    def handler(request):
        return httpx.Response(200, json={"result": {"addressMatches": []}})

    monkeypatch.setattr(http, "new_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    with TestClient(app) as client:
        resp = client.post("/v1/parcel/score", json={"address": "nowhere at all"})
    assert resp.status_code == 404


def test_simulate_keeps_provenance_and_indicative_flag(monkeypatch):
    up = Upstreams()
    monkeypatch.setattr(http, "_client", up.client())
    built = run(pipeline.build_parcel_for_address("1100 Congress Ave Austin TX 78701"))
    out = simulate(built, [])
    assert out.indicative_only is True and len(out.input_provenance) >= 15


def test_geocoder_outage_is_502_not_500(monkeypatch):
    monkeypatch.setattr(
        http, "new_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    )
    with TestClient(app) as client:
        resp = client.post("/v1/parcel/score", json={"address": "1100 Congress Ave, Austin, TX"})
    assert resp.status_code == 502


def test_failed_background_county_load_is_logged(caplog):
    up = Upstreams(fail={"www.fema.gov"})
    with caplog.at_level("WARNING", logger="app.ingestion.engine"):

        async def go():
            async with up.client() as client:
                engine = SpatialIngestionEngine(client, timeout_s=1.0, caches=Caches())
                return await engine.fetch("a", AUSTIN["lat"], AUSTIN["lng"], AUSTIN["county"], "TX")

        run(go())
    assert any("county aggregate" in r.getMessage() or "openfema" in r.getMessage() for r in caplog.records)


def test_duplicate_policy_rows_across_pages_are_refused():
    rows = [dict(policy(), id=f"p{i % 1500}") for i in range(2000)]  # ids repeat across pages

    def handler(request):
        skip = int(request.url.params.get("$skip", 0))
        return httpx.Response(200, json={"metadata": {}, "NfipPolicies": rows[skip : skip + 1000]})

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await openfema._page_pages(
                c, openfema.POLICIES_URL, "NfipPolicies", lambda skip: openfema.policy_params("48453", skip=skip)
            )

    with pytest.raises(openfema.ExposureUnavailable):
        run(go())


# --- live (RS_LIVE=1) ---------------------------------------------------------------------------------------


@pytest.mark.live
def test_live_apis_reachable():
    assert os.environ.get("RS_LIVE") == "1"

    async def go():
        async with http.new_client() as c:
            g = await geocode.geocode(c, "1100 Congress Ave Austin TX 78701")
            flood, prior, lag, rain, agg = await asyncio.gather(
                nfhl.fetch_flood_zone(c, g.lat, g.lng),
                nri.fetch_tract_prior(c, g.lat, g.lng),
                usgs_3dep.fetch_lag_ft(c, g.lat, g.lng),
                noaa.fetch_p24h_100yr_in(c, g.lat, g.lng),
                openfema.fetch_county_aggregate(c, g.county_fips),
            )
            return g, flood, prior, lag, rain, agg

    g, flood, prior, lag, rain, agg = run(go())
    assert (g.state, g.county_fips) == ("TX", "48453")
    assert flood.zone
    assert 0 < prior.total_rate < 0.1
    assert 300 < lag < 1000
    assert 8 < rain < 20
    assert agg.claim_count > 500
