"""FEMA National Flood Hazard Layer: flood zone and base flood elevation at a point.

Source: https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28 (S_FLD_HAZ_AR), live-checked
2026-10-17. STATIC_BFE of -9999 means "no BFE" and becomes None.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

NFHL_URL = "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28/query"
NFHL_TIMEOUT_S = 3.0  # the service is slow at times
NO_DATA = -9999.0


@dataclass(frozen=True)
class FloodZone:
    zone: str
    sfha: bool
    bfe_ft: float | None
    subtype: str | None


class NfhlNoCoverage(Exception):
    """The point is outside the mapped NFHL (no polygon), which is not the same as zone X."""


def parse_nfhl(payload: dict) -> FloodZone:
    if "error" in payload:
        raise ValueError(f"NFHL error: {payload['error']}")
    features = payload.get("features")
    if features is None:
        raise ValueError("NFHL response has no features key")
    if not features:
        raise NfhlNoCoverage("no NFHL polygon at this point")
    a = features[0]["attributes"]
    bfe = a.get("STATIC_BFE")
    return FloodZone(
        zone=str(a["FLD_ZONE"]),
        sfha=a.get("SFHA_TF") == "T",
        bfe_ft=None if bfe is None or float(bfe) <= NO_DATA else float(bfe),
        subtype=a.get("ZONE_SUBTY"),
    )


async def fetch_flood_zone(client: httpx.AsyncClient, lat: float, lng: float) -> FloodZone:
    resp = await client.get(
        NFHL_URL,
        params={
            "geometry": f"{lng},{lat}",
            "geometryType": "esriGeometryPoint",
            "inSR": 4326,
            "spatialRel": "esriSpatialRelIntersects",
            "outFields": "FLD_ZONE,SFHA_TF,STATIC_BFE,ZONE_SUBTY,DEPTH",
            "returnGeometry": "false",
            "f": "json",
        },
        timeout=NFHL_TIMEOUT_S,
    )
    resp.raise_for_status()
    return parse_nfhl(resp.json())
