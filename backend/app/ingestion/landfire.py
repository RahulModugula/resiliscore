"""LANDFIRE FBFM40 fuel model at a point (USGS LFPS ImageServer identify).

Source: https://lfps.usgs.gov/arcgis/rest/services/Landfire_LF2025/LF2025_FBFM40_CONUS/ImageServer, live-checked
2026-10-17. The geometry must be JSON with a spatialReference; plain x,y returns NoData.
"""

from __future__ import annotations

import json

import httpx

LANDFIRE_URL = (
    "https://lfps.usgs.gov/arcgis/rest/services/Landfire_LF2025/LF2025_FBFM40_CONUS/ImageServer/identify"
)
VINTAGE = "LF2025_FBFM40"

# Scott & Burgan 40 fuel models: raster value -> code.
_FAMILIES = {10: "GR", 12: "GS", 14: "SH", 16: "TU", 18: "TL", 20: "SB"}
_NON_BURNABLE = {91: "NB1", 92: "NB2", 93: "NB3", 98: "NB8", 99: "NB9"}


class NoFuelData(ValueError):
    """A valid answer: the raster has no fuel model here (water, some urban cells), so the default applies."""


def fuel_code(value: int) -> str:
    if value in _NON_BURNABLE:
        return _NON_BURNABLE[value]
    fam = _FAMILIES.get(value // 10)
    if fam is None or not 1 <= value % 10 <= 9:
        raise ValueError(f"unknown FBFM40 raster value {value}")
    return f"{fam}{value % 10}"


def parse_landfire(payload: dict) -> str:
    raw = payload.get("value")
    if raw is None or str(raw).lower() == "nodata":
        raise NoFuelData("LANDFIRE has no fuel model at this point")
    return fuel_code(int(float(raw)))


async def fetch_fuel_model(client: httpx.AsyncClient, lat: float, lng: float) -> str:
    resp = await client.get(
        LANDFIRE_URL,
        params={
            "geometry": json.dumps({"x": lng, "y": lat, "spatialReference": {"wkid": 4326}}),
            "geometryType": "esriGeometryPoint",
            "returnGeometry": "false",
            "returnCatalogItems": "false",
            "f": "json",
        },
    )
    resp.raise_for_status()
    return parse_landfire(resp.json())
