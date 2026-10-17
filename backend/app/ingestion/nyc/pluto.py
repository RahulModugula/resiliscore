"""MapPLUTO lot facts (Socrata 64uk-42ks): building class, year built, floors and basement.

PLUTO stores `bbl` as a string like "1008350041.00000000". `bsmtcode` follows the DCP data dictionary
(0 none; 1 and 3 full; 2 and 4 partial; 5 basement of unknown extent). That list is from the dictionary as
remembered, not re-read: the 2023 PDF is encrypted and the Socrata column description has no code list.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import cos, radians

import httpx

from app.ingestion.nyc.common import soda
from app.ingestion.rasters import distance_m

DATASET = "64uk-42ks"
FIELDS = "bbl,address,borough,bldgclass,yearbuilt,numfloors,bsmtcode,unitsres,latitude,longitude"
_FULL, _PARTIAL = {"1", "3"}, {"2", "4"}


@dataclass(frozen=True)
class Pluto:
    bbl: str
    address: str | None
    bldg_class: str | None
    year_built: int | None
    num_floors: float | None
    basement_code: str | None
    basement_type: str  # NONE / FULL / PARTIAL / UNKNOWN


def pluto_bbl(bbl: str) -> str:
    """The 10-digit BBL in PLUTO's string form."""
    if not (bbl.isdigit() and len(bbl) == 10):
        raise ValueError(f"BBL must be 10 digits: {bbl!r}")
    return f"{bbl}.00000000"


def basement_type(code: str | None) -> str:
    if code is None:
        return "UNKNOWN"
    code = str(code).strip()
    if code == "0":
        return "NONE"
    if code in _FULL:
        return "FULL"
    if code in _PARTIAL:
        return "PARTIAL"
    return "UNKNOWN"


def _float(v: object) -> float | None:
    try:
        return None if v in (None, "") else float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def parse_pluto(rows: list[dict]) -> Pluto:
    if not rows:
        raise LookupError("no PLUTO lot for this BBL")
    r = rows[0]
    year = _float(r.get("yearbuilt"))
    floors = _float(r.get("numfloors"))
    code = r.get("bsmtcode")
    return Pluto(
        bbl=str(r["bbl"]).split(".")[0],
        address=r.get("address"),
        bldg_class=r.get("bldgclass"),
        year_built=int(year) if year else None,  # PLUTO: null or 0 means unknown
        num_floors=floors if floors else None,
        basement_code=None if code in (None, "") else str(code),
        basement_type=basement_type(code),
    )


UNITS_RADIUS_M = 500
UNITS_MAX_ROWS = 20_000  # a dense Manhattan box holds a few thousand lots; refuse rather than undercount


def sum_units(rows: list[dict], lat: float, lng: float, radius_m: float = UNITS_RADIUS_M) -> int:
    """Residential units on lots whose PLUTO point is within the radius (PLUTO has no geometry column to query)."""
    total = 0
    for r in rows:
        la, lo, units = _float(r.get("latitude")), _float(r.get("longitude")), _float(r.get("unitsres"))
        if la is None or lo is None or not units:
            continue
        if distance_m(lat, lng, la, lo) <= radius_m:
            total += int(units)
    return total


async def fetch_units_nearby(client: httpx.AsyncClient, lat: float, lng: float) -> int:
    """Sum of `unitsres` within 500 m: the denominator that turns a 311 count into a density."""
    dlat = UNITS_RADIUS_M / 111_320
    dlng = UNITS_RADIUS_M / (111_320 * cos(radians(lat)))
    rows = await soda(
        client, DATASET,
        **{
            "$select": "latitude,longitude,unitsres",
            "$where": (
                f"latitude between {lat - dlat:.6f} and {lat + dlat:.6f} "
                f"AND longitude between {lng - dlng:.6f} and {lng + dlng:.6f}"
            ),
            "$limit": UNITS_MAX_ROWS,
        },
    )  # fmt: skip
    if len(rows) >= UNITS_MAX_ROWS:
        raise ValueError("PLUTO box exceeds the row cap: refusing to undercount residential units")
    return sum_units(rows, lat, lng)


async def fetch_pluto(client: httpx.AsyncClient, bbl: str) -> Pluto:
    rows = await soda(client, DATASET, **{"$where": f"bbl='{pluto_bbl(bbl)}'", "$select": FIELDS, "$limit": 1})
    return parse_pluto(rows)
