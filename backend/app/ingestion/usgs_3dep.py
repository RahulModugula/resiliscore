"""USGS 3DEP Elevation Point Query Service client (SPEC Prompt 1A, item 2)."""

from __future__ import annotations

from dataclasses import dataclass

import httpx

EPQS_URL = "https://epqs.nationalmap.gov/v1/json"
EPQS_NODATA = -1_000_000.0
DEFAULT_FOUNDATION_OFFSET_FT = 2.0  # delta_z_foundation: slab-on-grade default when no elevation certificate


@dataclass(frozen=True)
class Elevations:
    usgs_lag_ft: float
    est_ffe_ft: float
    freeboard_delta_h_ft: float | None  # None when BFE is None


def parse_epqs(payload: dict) -> float:
    """Bare-earth elevation in feet from an EPQS JSON body. Raises ValueError on no-data or a bad body."""
    try:
        value = float(payload["value"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"unparseable EPQS response: {payload!r}") from exc
    if value <= EPQS_NODATA:
        raise ValueError("EPQS has no data at this point")
    return value


def compute_elevations(
    lag_ft: float, bfe_ft: float | None, foundation_offset_ft: float = DEFAULT_FOUNDATION_OFFSET_FT
) -> Elevations:
    """FFE = LAG + foundation offset; freeboard = FFE - BFE (None if BFE is None)."""
    ffe = lag_ft + foundation_offset_ft
    return Elevations(lag_ft, ffe, None if bfe_ft is None else ffe - bfe_ft)


async def fetch_lag_ft(client: httpx.AsyncClient, lat: float, lng: float) -> float:
    resp = await client.get(EPQS_URL, params={"x": lng, "y": lat, "wkid": 4326, "units": "Feet"})
    resp.raise_for_status()
    return parse_epqs(resp.json())
