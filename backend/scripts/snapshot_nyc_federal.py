"""Snapshot the federal hazard layers (NFHL, EPQS, NRI tract, LANDFIRE, NOAA) for the three NYC golden addresses.

Live (needs the network; the federal services time out intermittently, so each address retries). Writes
tests/fixtures/nyc/golden_federal.json, which scripts/build_nyc_golden.py reads. Run from backend/:
    uv run python scripts/snapshot_nyc_federal.py
"""

import asyncio
import dataclasses
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from test_nyc import Replay

from app import http, pipeline
from app.ingestion.engine import Caches, SpatialIngestionEngine
from app.ingestion.nyc.common import NycCaches

OUT = {}
for slug in ("red_hook", "hollis", "rockaway"):
    rep = Replay(slug)
    http._client = rep.client()
    pipeline.NYC_CACHES = NycCaches()
    built = asyncio.run(pipeline.build_parcel_for_address(rep.data["address"]))
    p = built.parcel.parcel_identity
    lng, lat = p.centroid
    http._client = None  # live from here
    for attempt in range(6):  # the federal services time out intermittently: keep the first complete answer
        result = asyncio.run(SpatialIngestionEngine(timeout_s=20.0, caches=Caches()).fetch(rep.data["address"], lat, lng, p.county_fips, p.state))
        live = {x.field for x in result.provenance if x.value_source == "LIVE"}
        if {"fema_flood_zone", "usgs_lag_ft", "tract_prior_lcr"} <= live:
            break
        print("retry", slug, attempt, file=sys.stderr)
    t = result.nri_tract
    OUT[slug] = {
        "point": [lng, lat], "county_fips": p.county_fips, "state": p.state,
        "layer": result.layer.model_dump(), "vintages": result.vintages,
        "provenance": [x.model_dump() for x in result.provenance], "tract_prior_lcr": result.tract_prior_lcr,
        "nri_tract": dataclasses.asdict(t) if t else None, "captured": "2026-10-17",
    }
    h = result.layer
    print(slug, (lat, lng), p.county_fips, "zone", h.fema_flood_zone, "bfe", h.bfe_ft_navd88, "lag", h.usgs_lag_ft,
          "ffe", h.est_ffe_ft, "fb", h.freeboard_delta_h_ft, "rain", h.noaa_atlas15_p24h_100yr_in, "fuel", h.landfire_fbfm40_code,
          "| nri", t.tract_fips if t else None, "prior bps", round(result.tract_prior_lcr * 1e4, 2),
          "| indicative", result.indicative_only)
(ROOT / "tests" / "fixtures" / "nyc" / "golden_federal.json").write_text(json.dumps(OUT, indent=1) + "\n")
