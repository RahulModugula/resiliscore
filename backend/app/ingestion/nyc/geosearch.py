"""NYC GeoSearch (Pelias over the Department of City Planning PAD): address to BBL, BIN and a point.

Source: https://geosearch.planninglabs.nyc/v2/search and /v2/reverse, live-checked 2026-10-17. The BBL and BIN
are in `properties.addendum.pad`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import httpx

SEARCH_URL = "https://geosearch.planninglabs.nyc/v2/search"
REVERSE_URL = "https://geosearch.planninglabs.nyc/v2/reverse"
NYC_COUNTY_FIPS = {"36005": "Bronx", "36047": "Brooklyn", "36061": "Manhattan", "36081": "Queens", "36085": "Staten Island"}
BOROUGH_COUNTY = {"Manhattan": "36061", "Bronx": "36005", "Brooklyn": "36047", "Queens": "36081", "Staten Island": "36085"}
BOROUGH_CODES = {"1": "Manhattan", "2": "Bronx", "3": "Brooklyn", "4": "Queens", "5": "Staten Island"}


class GeoSearchNoMatch(Exception):
    """GeoSearch found no PAD address (not a NYC address, or not a known one)."""


@dataclass(frozen=True)
class NycAddress:
    label: str
    lat: float
    lng: float
    bbl: str  # 10 digits
    bin: str | None
    borough: str
    confidence: float | None


def parse_geosearch(payload: dict) -> NycAddress:
    for feat in payload.get("features", []):
        props = feat.get("properties", {})
        pad = props.get("addendum", {}).get("pad", {})
        bbl = pad.get("bbl")
        if not bbl:
            continue
        lng, lat = feat["geometry"]["coordinates"]
        borough = props.get("borough") or BOROUGH_CODES.get(str(bbl)[:1], "")
        return NycAddress(
            label=props.get("label", ""), lat=float(lat), lng=float(lng), bbl=str(bbl),
            bin=str(pad["bin"]) if pad.get("bin") else None, borough=borough, confidence=props.get("confidence"),
        )  # fmt: skip
    raise GeoSearchNoMatch("no PAD address in the GeoSearch response")


def agrees_with_text(text: str, payload: dict) -> bool:
    """Pelias fuzzy-matches any text to some NYC street ("10001 Main St, Dallas" gave "190C MAIN STREET, Bronx").
    Accept a hit only when its house number equals the one typed and the typed street's first word is in its street."""
    props = payload["features"][0]["properties"] if payload.get("features") else {}
    head = text.split(",")[0].strip().lower()
    m = re.match(r"^(\S+)\s+(.+)$", head)
    if not m:
        return False
    number, street_text = m.group(1), m.group(2)
    words = re.findall(r"[a-z0-9]+", street_text)
    street = str(props.get("street", "")).lower()
    return (
        str(props.get("housenumber", "")).lower() == number
        and bool(words)
        and words[0] in re.findall(r"[a-z0-9]+", street)
    )


async def search(client: httpx.AsyncClient, address: str) -> NycAddress:
    resp = await client.get(SEARCH_URL, params={"text": address, "size": 1})
    resp.raise_for_status()
    payload = resp.json()
    found = parse_geosearch(payload)
    if not agrees_with_text(address, payload):
        raise GeoSearchNoMatch(f"GeoSearch matched {found.label!r}, which does not agree with the typed address")
    return found


async def reverse(client: httpx.AsyncClient, lat: float, lng: float) -> NycAddress:
    resp = await client.get(REVERSE_URL, params={"point.lat": lat, "point.lon": lng, "size": 1})
    resp.raise_for_status()
    return parse_geosearch(resp.json())
