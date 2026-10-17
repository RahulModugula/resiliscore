"""Ingestion tests: httpx.MockTransport only, so CI never touches the network (except the RS_LIVE test)."""

import asyncio
import os

import httpx
import pytest

from app.ingestion import openfema, rasters, usgs_3dep
from app.ingestion.engine import SpatialIngestionEngine

# 1 km from the S1 centroid, same county: not pinned, so the live/fallback paths run.
OFF_LAT, OFF_LNG, PARISH = 29.9747, -90.1032, "22051"


def claims_body(rows, count=None):
    return {"metadata": {"count": count if count is not None else len(rows)}, "NfipClaims": rows}


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


def mock_client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def run(coro):
    return asyncio.run(coro)


def api_handler(lag=3.0, rows=None, delay=0.0):
    rows = rows if rows is not None else [claim(paid=p) for p in (500, 1500, 4000, 9000)]

    async def handler(request: httpx.Request) -> httpx.Response:
        if delay:
            await asyncio.sleep(delay)
        if "epqs" in request.url.host:
            return httpx.Response(200, json={"value": lag})
        return httpx.Response(200, json=claims_body(rows, count=1432))

    return handler


# --- OpenFEMA -------------------------------------------------------------------------------------------


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


def test_params_use_odata_filter_top_select():
    p = openfema.build_params("22051")
    assert p["$filter"] == "(countyCode eq '22051' and yearOfLoss ge 2010)"
    assert p["$top"] == "1000"
    assert "elevationDifference" in p["$select"]


def test_gamma_fit_recovers_known_parameters():
    import numpy as np

    x = np.random.default_rng(7).gamma(shape=2.0, scale=1 / 50.0, size=50_000)
    prior = openfema.gamma_mom_fit(list(x))
    assert prior.alpha == pytest.approx(2.0, rel=0.05)
    assert prior.beta == pytest.approx(50.0, rel=0.05)
    assert prior.alpha / prior.beta == pytest.approx(float(np.mean(x)))


@pytest.mark.parametrize("values", [[], [0.1], [0.2, 0.2], [0.0, 0.0, 0.3]])
def test_gamma_fit_rejects_degenerate_input(values):
    with pytest.raises(ValueError):
        openfema.gamma_mom_fit(values)


def test_fetch_county_prior_end_to_end():
    async def go():
        async with mock_client(api_handler()) as c:
            return await openfema.fetch_county_prior(c, "22051")

    out = run(go())
    assert out.claim_count == 1432
    assert out.prior is not None and out.prior.alpha > 0 and out.prior.beta > 0
    assert out.mean_lcr == pytest.approx((5 + 15 + 40 + 90) / 4 / 1000)


def test_bad_county_fips_rejected():
    async def go():
        async with mock_client(api_handler()) as c:
            await openfema.fetch_county_claims(c, "22051' or 1 eq 1")

    with pytest.raises(ValueError):
        run(go())


# --- USGS EPQS ------------------------------------------------------------------------------------------


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


def test_epqs_request_shape():
    seen = {}

    def handler(request):
        seen.update(request.url.params)
        return httpx.Response(200, json={"value": 5.0})

    async def go():
        async with mock_client(handler) as c:
            return await usgs_3dep.fetch_lag_ft(c, 29.9657, -90.1032)

    assert run(go()) == 5.0
    assert seen == {"x": "-90.1032", "y": "29.9657", "wkid": "4326", "units": "Feet"}


# --- rasters --------------------------------------------------------------------------------------------


def test_raster_lookup_exact_and_nearest_neighbour():
    s2 = rasters.lookup_rasters(34.192, -118.1432)
    assert (s2.landfire_fbfm40_code, s2.slope_deg) == ("SH7", 28.0)
    assert rasters.lookup_rasters(34.25, -118.2).landfire_fbfm40_code == "SH7"
    assert rasters.lookup_rasters(33.2, -117.1).landfire_fbfm40_code == "GS2"


def test_vintages_agree_with_golden_files():
    for site in rasters.golden_sites():
        golden = site.response.regulatory_compliance.dataset_vintages
        mine = rasters.vintages_for(site.response.parcel_identity.state)
        assert {k: v for k, v in mine.items() if k != "OpenFEMA"}.items() <= golden.items()


# --- engine ---------------------------------------------------------------------------------------------


def fetch(client, lat=OFF_LAT, lng=OFF_LNG, county=PARISH, state="LA", **kw):
    async def go():
        async with client:
            return await SpatialIngestionEngine(client, **kw).fetch("addr", lat, lng, county, state)

    return run(go())


def test_live_overrides_cacheable_fields_and_flags_live():
    layer, vintages, flags = fetch(mock_client(api_handler(lag=3.0)))
    assert flags == {"openfema": "live", "usgs_3dep": "live", "rasters": "cache"}
    assert layer.usgs_lag_ft == 3.0
    assert layer.est_ffe_ft == 5.0
    assert layer.freeboard_delta_h_ft == pytest.approx(5.0 - 9.0)  # S1 BFE is 9.0
    assert layer.openfema_tract_claim_count == 1432
    assert "LA_FORTIFY_HOMES" in vintages and "USGS_3DEP" in vintages


def test_timeout_falls_back_to_cache_per_source():
    layer, _, flags = fetch(mock_client(api_handler(delay=0.5)), timeout_s=0.05)
    gold = rasters.nearest_site(OFF_LAT, OFF_LNG, PARISH).response.public_hazard_layer
    assert flags == {"openfema": "cache", "usgs_3dep": "cache", "rasters": "cache"}
    assert layer == gold


def test_one_source_failing_leaves_the_other_live():
    def handler(request):
        if "epqs" in request.url.host:
            return httpx.Response(503)
        return httpx.Response(200, json=claims_body([claim(paid=1), claim(paid=9)]))

    layer, _, flags = fetch(mock_client(handler))
    assert flags["openfema"] == "live" and flags["usgs_3dep"] == "cache"
    assert layer.usgs_lag_ft == 7.2


def test_garbage_json_falls_back():
    layer, _, flags = fetch(mock_client(lambda r: httpx.Response(200, text="<html>")))
    assert flags["openfema"] == flags["usgs_3dep"] == "cache"
    assert layer.fema_flood_zone == "AE"


def test_golden_centroid_is_served_exactly_without_network():
    def boom(request):
        raise AssertionError("pinned demo parcel must not touch the network")

    layer, _, flags = fetch(mock_client(boom), lat=29.9657, lng=-90.1032)
    s1 = rasters.golden_sites()[0].response.public_hazard_layer
    assert layer == s1 and set(flags.values()) == {"cache"}


def test_no_bfe_parcel_gets_zero_contract_freeboard_not_none():
    layer, _, _ = fetch(
        mock_client(api_handler(lag=1300.0)), lat=34.2, lng=-118.15, county="06037", state="CA"
    )
    assert layer.bfe_ft_navd88 is None
    assert layer.freeboard_delta_h_ft == 0.0


# --- live (RS_LIVE=1) -----------------------------------------------------------------------------------


@pytest.mark.live
def test_live_apis_reachable():
    assert os.environ.get("RS_LIVE") == "1"

    async def go():
        async with httpx.AsyncClient(timeout=15) as c:
            return await asyncio.gather(
                openfema.fetch_county_prior(c, "22051"), usgs_3dep.fetch_lag_ft(c, 29.9657, -90.1032)
            )

    prior, lag = run(go())
    assert prior.claim_count > 1000 and prior.prior is not None
    assert -50 < lag < 50
