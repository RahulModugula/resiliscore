"""NYC Building Footprints (Socrata 5zhs-2jue): the building outline, ground elevation and roof height.

`ground_elevation` is feet above NAVD88 (photogrammetric, per building) and `height_roof` is feet above it.
The outline replaces the OpenStreetMap footprint inside NYC.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.ingestion.nyc.common import soda

DATASET = "5zhs-2jue"
FIELDS = "bin,base_bbl,ground_elevation,height_roof,construction_year,the_geom"
NEARBY_M = 30


@dataclass(frozen=True)
class BuildingFootprint:
    bin: str
    base_bbl: str | None
    ground_elevation_ft: float | None
    roof_height_ft: float | None
    construction_year: int | None
    ring: list[list[float]]  # closed WGS84 [lng, lat] outer ring


def _num(v: object) -> float | None:
    try:
        return None if v in (None, "") else float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def outer_ring(geom: dict) -> list[list[float]]:
    """Largest outer ring of a (Multi)Polygon, as [lng, lat] pairs."""
    kind, coords = geom.get("type"), geom.get("coordinates")
    polygons = [coords] if kind == "Polygon" else coords if kind == "MultiPolygon" else None
    if not polygons:
        raise ValueError(f"unsupported footprint geometry {kind!r}")
    rings = [p[0] for p in polygons if p and p[0]]
    ring = max(rings, key=len)
    return [[float(x), float(y)] for x, y in ring]


def parse_footprints(rows: list[dict], bin_: str | None = None) -> BuildingFootprint:
    """The row for `bin_` when given and present, else the first row (nearest lot building)."""
    if not rows:
        raise LookupError("no building footprint")
    row = next((r for r in rows if bin_ and str(r.get("bin")) == bin_), rows[0])
    year = _num(row.get("construction_year"))
    return BuildingFootprint(
        bin=str(row["bin"]), base_bbl=row.get("base_bbl"),
        ground_elevation_ft=_num(row.get("ground_elevation")), roof_height_ft=_num(row.get("height_roof")),
        construction_year=int(year) if year else None, ring=outer_ring(row["the_geom"]),
    )  # fmt: skip


async def fetch_footprint(
    client: httpx.AsyncClient, bin_: str | None, bbl: str, lat: float, lng: float
) -> BuildingFootprint:
    """By BIN when known, else the buildings on the lot, else the nearest building within 30 m."""
    if bin_ and bin_.isdigit():
        where = f"bin='{bin_}'"
    elif bbl.isdigit():
        where = f"base_bbl='{bbl}'"
    else:
        where = f"within_circle(the_geom,{lat},{lng},{NEARBY_M})"
    rows = await soda(client, DATASET, **{"$where": where, "$select": FIELDS, "$limit": 5})
    return parse_footprints(rows, bin_)
