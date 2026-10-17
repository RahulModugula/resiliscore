"""Census Geocoder: one-line address to lat/lng and state/county/tract FIPS.

Source: https://geocoding.geo.census.gov/geocoder/geographies/onelineaddress
(benchmark Public_AR_Current, vintage Current_Current), live-checked 2026-10-17.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

log = logging.getLogger(__name__)

GEOCODER_URL = "https://geocoding.geo.census.gov/geocoder/geographies/onelineaddress"
BENCHMARK = "Public_AR_Current"
VINTAGE = "Current_Current"

STATE_FIPS_TO_USPS = {
    "01": "AL", "02": "AK", "04": "AZ", "05": "AR", "06": "CA", "08": "CO", "09": "CT", "10": "DE",
    "11": "DC", "12": "FL", "13": "GA", "15": "HI", "16": "ID", "17": "IL", "18": "IN", "19": "IA",
    "20": "KS", "21": "KY", "22": "LA", "23": "ME", "24": "MD", "25": "MA", "26": "MI", "27": "MN",
    "28": "MS", "29": "MO", "30": "MT", "31": "NE", "32": "NV", "33": "NH", "34": "NJ", "35": "NM",
    "36": "NY", "37": "NC", "38": "ND", "39": "OH", "40": "OK", "41": "OR", "42": "PA", "44": "RI",
    "45": "SC", "46": "SD", "47": "TN", "48": "TX", "49": "UT", "50": "VT", "51": "VA", "53": "WA",
    "54": "WV", "55": "WI", "56": "WY",
}  # fmt: skip


class GeocodeError(Exception):
    """No usable match (unknown address or unparseable response)."""


@dataclass(frozen=True)
class Geocode:
    matched_address: str
    lat: float
    lng: float
    state: str  # USPS code
    county_fips: str  # 5 digits: state + county
    tract_fips: str  # 11 digits: state + county + tract


def parse_geocode(payload: dict) -> Geocode:
    try:
        matches = payload["result"]["addressMatches"]
        if not matches:
            raise GeocodeError("no address match")
        m = matches[0]
        geos = m["geographies"]
        county = geos["Counties"][0]["GEOID"]
        tract = geos["Census Tracts"][0]["GEOID"]
        state = STATE_FIPS_TO_USPS[geos["States"][0]["GEOID"]]
        return Geocode(
            matched_address=m["matchedAddress"],
            lat=float(m["coordinates"]["y"]),
            lng=float(m["coordinates"]["x"]),
            state=state,
            county_fips=county,
            tract_fips=tract,
        )
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise GeocodeError(f"unparseable geocoder response: {exc!r}") from exc


async def geocode(client: httpx.AsyncClient, address: str) -> Geocode:
    resp = await client.get(
        GEOCODER_URL,
        params={"address": address, "benchmark": BENCHMARK, "vintage": VINTAGE, "format": "json"},
    )
    resp.raise_for_status()
    return parse_geocode(resp.json())
