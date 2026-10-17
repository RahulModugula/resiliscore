"""Golden reference sites, dataset vintages and the documented national defaults (SPEC Prompt 1A, item 3).

The golden scenarios (contracts/golden_scenarios.json) are served only for the demo parcels themselves.
No other parcel ever borrows a value from them: a layer with no live source gets a NATIONAL_DEFAULT below,
and the response marks it DEFAULT.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from math import asin, cos, radians, sin, sqrt
from pathlib import Path

from app.models.schemas import ParcelScoreResponse

GOLDEN_PATH = Path(__file__).resolve().parents[3] / "contracts" / "golden_scenarios.json"

# SPEC line 116: the vintages stamped on the golden scenarios (app.fixtures regenerates them from this dict).
VINTAGES: dict[str, str] = {
    "USGS_3DEP": "2025-05-01",
    "NOAA_PFDS": "Atlas15_Vol1_Prelim_2026",
    "OpenFEMA": "NfipClaims_v3",
    "LANDFIRE": "LF2024_FBFM40",
    "USGS_HAND": "NHDPlusHR_2024",
    "FEMA_NFHL": "2026-03",
}

# Vintages of what the live path actually queries. NOAA is Atlas 14: Atlas 15 has no API, so the golden
# files' "Atlas15" label does not apply to live data.
LIVE_VINTAGES: dict[str, str] = {
    "USGS_3DEP": "EPQS_current",
    "NOAA_PFDS": "Atlas14",
    "OpenFEMA": "NfipClaims_NfipPolicies_v3",
    "LANDFIRE": "LF2025_FBFM40",
    "FEMA_NFHL": "live",
    "FEMA_NRI": "December 2025",
    "CENSUS_GEOCODER": "Public_AR_Current",
}

# Documented national defaults for layers with no live source. Each is a neutral mid-range value, not a
# regional one, and every use is marked DEFAULT in input_provenance.
NATIONAL_DEFAULTS: dict[str, float | str] = {
    "fema_flood_zone": "D",  # FEMA: "possible but undetermined flood hazard"
    "hand_rel_elev_ft": 5.0,  # USGS HAND needs a raster; none is served live
    "twi_index": 8.0,
    "slope_deg": 5.0,
    "noaa_atlas15_p24h_100yr_in": 8.0,
    "atlas15_cmip6_mult": 1.1,  # assumed climate multiplier on Atlas 14 (golden range 1.08 to 1.12)
    "landfire_fbfm40_code": "NB1",
    "wui_class": "NON_WUI",  # no WUI source is served live
    "tract_prior_lcr": 0.01,
    "foundation_offset_ft": 2.0,
}


@dataclass(frozen=True)
class GoldenSite:
    key: str
    county_fips: str
    lng: float
    lat: float
    response: ParcelScoreResponse


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
