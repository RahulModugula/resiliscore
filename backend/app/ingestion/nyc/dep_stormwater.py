"""NYC Stormwater Flood Maps (DEP): flood class at a point for the four official scenarios.

The maps are published by the Department of Environmental Protection (data.cityofnewyork.us 9i7c-xyvv, a zip
download; viewer at nyc.gov/stormwater-map). The Socrata copies are not queryable (403), so the point lookups
use the ArcGIS Online feature services owned by NYC agencies, live-checked 2026-10-17:

* MODERATE_2050: DEP's own organization, `Moderate_Flood_SLR_2050` layer 4 (deep and contiguous, 1 ft and
  greater) and layer 5 (nuisance, 4 in to under 1 ft). https://services.arcgis.com/at3rDjch5X7i9Bag
* EXTREME_2080 and MODERATE_CURRENT: the Mayor's Office of Climate & Environmental Justice organization
  (`mocej.nyc.data`), field `Flooding_C`: 1 nuisance, 2 deep and contiguous, 3 future high tide (tidal, not
  stormwater, so it counts as no stormwater flooding). The code meaning was confirmed by matching total area
  per code with DEP's own layers 5 and 4 (13.99 vs 13.88 and 7.46 vs 7.33 km2). https://services6.arcgis.com/yG5s3afENB5iO9fj
* LIMITED_CURRENT: only a raster tile service (nycem_adminpub, DEP_Stormwater_Flood_Limited_SLR_2020s) exists, which
  cannot be queried by point. It is reported UNAVAILABLE rather than approximated.

A point in no polygon is NONE: the maps list only areas that flood.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

import httpx

log = logging.getLogger(__name__)

DEP = "https://services.arcgis.com/at3rDjch5X7i9Bag/arcgis/rest/services/Moderate_Flood_SLR_2050/FeatureServer"
MOCEJ = "https://services6.arcgis.com/yG5s3afENB5iO9fj/arcgis/rest/services"

CODE_CLASS = {1: "NUISANCE", 2: "DEEP_CONTIGUOUS"}  # 3 is tidal: no stormwater class
RANK = {"NONE": 0, "NUISANCE": 1, "DEEP_CONTIGUOUS": 2}


@dataclass(frozen=True)
class Source:
    scenario: str
    url: str  # layer query endpoint
    fixed_class: str | None  # set when the layer itself is one class; else the Flooding_C code decides
    publisher: str


SOURCES: tuple[Source, ...] = (
    Source("MODERATE_2050", f"{DEP}/4/query", "DEEP_CONTIGUOUS", "NYC DEP (Moderate_Flood_SLR_2050 layer 4)"),
    Source("MODERATE_2050", f"{DEP}/5/query", "NUISANCE", "NYC DEP (Moderate_Flood_SLR_2050 layer 5)"),
    Source(
        "EXTREME_2080",
        f"{MOCEJ}/NYC_Stormwater_Flood_Map___Extreme_Flood_with_2080_Sea_Level_Rise/FeatureServer/0/query",
        None, "NYC Mayor's Office of Climate & Environmental Justice (DEP map)",
    ),
    Source(
        "MODERATE_CURRENT",
        f"{MOCEJ}/Moderate_Flood_Map_Current_Sea_Levels/FeatureServer/0/query",
        None, "NYC Mayor's Office of Climate & Environmental Justice (DEP map)",
    ),
)  # fmt: skip
SCENARIOS = ("LIMITED_CURRENT", "MODERATE_CURRENT", "MODERATE_2050", "EXTREME_2080")


def classify(source: Source, payload: dict) -> str:
    """The flood class one layer reports at the point."""
    if "error" in payload:
        raise ValueError(f"ArcGIS error: {payload['error']}")
    features = payload.get("features")
    if features is None:
        raise ValueError("ArcGIS response has no features key")
    if not features:
        return "NONE"
    if source.fixed_class:
        return source.fixed_class
    classes = [CODE_CLASS.get(f["attributes"].get("Flooding_C"), "NONE") for f in features]
    return max(classes, key=RANK.__getitem__)


async def _query(client: httpx.AsyncClient, source: Source, lat: float, lng: float) -> str:
    resp = await client.get(
        source.url,
        params={
            "geometry": f"{lng},{lat}", "geometryType": "esriGeometryPoint", "inSR": 4326,
            "spatialRel": "esriSpatialRelIntersects", "outFields": "*", "returnGeometry": "false", "f": "json",
        },
    )  # fmt: skip
    resp.raise_for_status()
    return classify(source, resp.json())


async def fetch_stormwater(client: httpx.AsyncClient, lat: float, lng: float) -> list[tuple[str, str]]:
    """(scenario, flood_class) for the four scenarios. A failed layer makes its scenario UNAVAILABLE."""
    results = await asyncio.gather(*(_query(client, s, lat, lng) for s in SOURCES), return_exceptions=True)
    by_scenario: dict[str, list[str | BaseException]] = {}
    for source, result in zip(SOURCES, results, strict=True):
        if isinstance(result, BaseException):
            log.warning("DEP stormwater %s (%s) failed: %s: %s", source.scenario, source.url, type(result).__name__, result)
        by_scenario.setdefault(source.scenario, []).append(result)
    out: list[tuple[str, str]] = []
    for scenario in SCENARIOS:
        got = by_scenario.get(scenario)
        if not got or any(isinstance(g, BaseException) for g in got):
            out.append((scenario, "UNAVAILABLE"))
        else:
            out.append((scenario, max(got, key=RANK.__getitem__)))  # type: ignore[arg-type]
    return out
