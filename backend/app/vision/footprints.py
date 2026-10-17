"""Building footprint by point (the parcel proxy: there is no free nationwide parcel API).

Live source is OpenStreetMap via Overpass (`way[building](around:30,lat,lng)`), choosing the polygon that
contains the point, else the nearest. Data (c) OpenStreetMap contributors, ODbL. The public endpoint allows
about 10,000 queries/day and asks for an identifying User-Agent and a pause after HTTP 429/406
(https://wiki.openstreetmap.org/wiki/Overpass_API, read 2026-10-17); `OVERPASS_URL` is the single place to
point at a mirror.

Batch alternative, not wired in: Overture Maps `buildings` GeoParquet (ODbL, release 2026-09-23.1), read by
bounding box with DuckDB's httpfs/parquet readers. It has no point-query API, and Microsoft USBuildingFootprints
was archived on 2026-10-08, so neither suits a request-time lookup. DuckDB is deliberately not a dependency.

With no building found, or on any failure within 2.5 s, the result is a 1,800 sqft square marked DEFAULT.
"""

import logging
from typing import NamedTuple

import httpx
from shapely.geometry import Point, Polygon, box

from app.models.schemas import InputProvenance
from app.vision.parcel_rings import SQM_TO_SQFT, to_lnglat, to_metres

log = logging.getLogger(__name__)

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
USER_AGENT = "SaveMyHome-hackathon/0.1 (underwriting demo)"
TIMEOUT_S = 2.5
SEARCH_RADIUS_M = 30
DEFAULT_AREA_SQFT = 1_800.0
SOURCE_NAME = "OpenStreetMap (Overpass)"
DEFAULT_SOURCE_NAME = "Default 1,800 sqft square"


class Footprint(NamedTuple):
    ring: list[list[float]]  # closed WGS84 [lng, lat] ring
    provenance: InputProvenance


def default_square(lat: float, lng: float, area_sqft: float = DEFAULT_AREA_SQFT) -> list[list[float]]:
    """Closed WGS84 ring for a square of `area_sqft` centred on the point."""
    p = to_metres(Point(lng, lat))
    half = (area_sqft / SQM_TO_SQFT) ** 0.5 / 2
    return [list(c) for c in to_lnglat(box(p.x - half, p.y - half, p.x + half, p.y + half)).exterior.coords]


def parse_overpass(payload: dict, lat: float, lng: float) -> list[list[float]] | None:
    """Ring of the building containing the point, else the nearest; None when the body holds no usable way."""
    point = to_metres(Point(lng, lat))
    best: tuple[float, list[list[float]]] | None = None
    for element in payload.get("elements", []):
        coords = [[n["lon"], n["lat"]] for n in element.get("geometry", [])]
        if len(coords) < 4 or coords[0] != coords[-1]:
            continue  # open way, not a building outline
        poly = Polygon(coords)
        if not poly.is_valid:
            continue
        distance = to_metres(poly).distance(point)  # 0 when the point is inside
        if best is None or distance < best[0]:
            best = (distance, coords)
    return best[1] if best else None


async def fetch_footprint(lat: float, lng: float, client: httpx.AsyncClient | None = None) -> Footprint:
    """Footprint at the point from OSM, else the default square. Never raises on network failure."""
    query = f"[out:json][timeout:2];way[building](around:{SEARCH_RADIUS_M},{lat},{lng});out geom;"
    http = client or httpx.AsyncClient()
    try:
        response = await http.post(
            OVERPASS_URL, data={"data": query}, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT_S
        )
        response.raise_for_status()
        ring = parse_overpass(response.json(), lat, lng)
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("Overpass footprint lookup failed at (%s, %s): %r", lat, lng, exc)
        ring = None
    finally:
        if client is None:
            await http.aclose()  # a caller-supplied shared client stays open
    if ring is None:
        provenance = InputProvenance(
            field="footprint", value_source="DEFAULT", source_name=DEFAULT_SOURCE_NAME, vintage=None
        )
        return Footprint(default_square(lat, lng), provenance)
    provenance = InputProvenance(field="footprint", value_source="LIVE", source_name=SOURCE_NAME, vintage=None)
    return Footprint(ring, provenance)
