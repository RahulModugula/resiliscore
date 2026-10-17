"""Raster lookup tables and dataset vintages (SPEC Prompt 1A, item 3).

The values are keyed by the golden scenario centroids (contracts/golden_scenarios.json) and any other point
resolves to the nearest centroid, preferring a scenario in the same county.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from math import asin, cos, radians, sin, sqrt
from pathlib import Path

from app.models.schemas import ParcelScoreResponse

GOLDEN_PATH = Path(__file__).resolve().parents[3] / "contracts" / "golden_scenarios.json"

# SPEC line 116: stamp every response with exact dataset vintages. State layers are added per state.
VINTAGES: dict[str, str] = {
    "USGS_3DEP": "2025-05-01",
    "NOAA_PFDS": "Atlas15_Vol1_Prelim_2026",
    "OpenFEMA": "NfipClaims_v3",
    "LANDFIRE": "LF2024_FBFM40",
    "USGS_HAND": "NHDPlusHR_2024",
    "FEMA_NFHL": "2026-03",
}
STATE_VINTAGES: dict[str, dict[str, str]] = {
    "LA": {"LA_FORTIFY_HOMES": "2026-Q2"},
    "CA": {"CAL_FIRE_FHSZ": "2025"},
}


@dataclass(frozen=True)
class RasterValues:
    noaa_atlas15_p24h_100yr_in: float
    atlas15_cmip6_mult: float
    landfire_fbfm40_code: str
    slope_deg: float
    hand_rel_elev_ft: float
    twi_index: float


@dataclass(frozen=True)
class GoldenSite:
    key: str
    county_fips: str
    lng: float
    lat: float
    response: ParcelScoreResponse


def vintages_for(state: str) -> dict[str, str]:
    return {**VINTAGES, **STATE_VINTAGES.get(state, {})}


@lru_cache(maxsize=1)
def golden_sites() -> tuple[GoldenSite, ...]:
    """One site per golden scenario; the `__UNPERMITTED` variant shares its base scenario's location."""
    raw = json.loads(GOLDEN_PATH.read_text())
    sites = []
    for key, body in raw.items():
        if "__" in key:
            continue
        resp = ParcelScoreResponse.model_validate(body)
        ident = resp.parcel_identity
        sites.append(GoldenSite(key, ident.county_fips, ident.centroid[0], ident.centroid[1], resp))
    return tuple(sites)


def distance_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Haversine distance in metres."""
    dlat, dlng = radians(lat2 - lat1), radians(lng2 - lng1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng / 2) ** 2
    return 2 * 6_371_000 * asin(sqrt(a))


def nearest_site(lat: float, lng: float, county_fips: str | None = None) -> GoldenSite:
    """Nearest golden site, restricted to the same county when one exists there."""
    sites = golden_sites()
    pool = [s for s in sites if s.county_fips == county_fips] or list(sites)
    return min(pool, key=lambda s: distance_m(lat, lng, s.lat, s.lng))


def lookup_rasters(lat: float, lng: float, county_fips: str | None = None) -> RasterValues:
    h = nearest_site(lat, lng, county_fips).response.public_hazard_layer
    return RasterValues(
        noaa_atlas15_p24h_100yr_in=h.noaa_atlas15_p24h_100yr_in,
        atlas15_cmip6_mult=h.atlas15_cmip6_mult,
        landfire_fbfm40_code=h.landfire_fbfm40_code,
        slope_deg=h.slope_deg,
        hand_rel_elev_ft=h.hand_rel_elev_ft,
        twi_index=h.twi_index,
    )
