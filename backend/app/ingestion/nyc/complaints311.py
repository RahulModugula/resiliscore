"""311 sewer complaints within 500 m over the last 5 years (Socrata erm2-nwe9), and DEP catch basins (2w2g-fk3i).

DEP changed the 311 wording: complaint type "Sewer" has "Sewer Backup (Use Comments) (SA)" and "Street
Flooding (SJ)"; the newer type "Sewer Maintenance" has "Backup" and "Flooding on Street". Both are counted.
Live-checked with `within_circle(location, lat, lng, 500)` on 2026-10-17.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.ingestion.nyc.common import soda, window_start

DATASET = "erm2-nwe9"
CATCH_BASINS = "2w2g-fk3i"
RADIUS_M = 500
BASIN_RADIUS_M = 150


@dataclass(frozen=True)
class Complaints:
    sewer_backup: int
    street_flooding: int


def classify_descriptor(descriptor: str) -> str | None:
    d = descriptor.strip().lower()
    if d.startswith("sewer backup") or d == "backup":
        return "backup"
    if d.startswith("street flooding") or d == "flooding on street":
        return "street"
    return None


def parse_complaints(rows: list[dict]) -> Complaints:
    totals = {"backup": 0, "street": 0}
    for r in rows:
        kind = classify_descriptor(r.get("descriptor", ""))
        if kind:
            totals[kind] += int(r.get("n") or 0)
    return Complaints(totals["backup"], totals["street"])


async def fetch_complaints(client: httpx.AsyncClient, lat: float, lng: float) -> Complaints:
    rows = await soda(
        client, DATASET,
        **{
            "$select": "descriptor, count(*) as n",
            "$where": (
                f"within_circle(location,{lat},{lng},{RADIUS_M}) AND created_date > '{window_start()}' "
                "AND complaint_type in('Sewer','Sewer Maintenance')"
            ),
            "$group": "descriptor",
        },
    )  # fmt: skip
    return parse_complaints(rows)


async def fetch_catch_basins(client: httpx.AsyncClient, lat: float, lng: float) -> int:
    rows = await soda(
        client, CATCH_BASINS,
        **{"$select": "count(*) as n", "$where": f"within_circle(the_geom,{lat},{lng},{BASIN_RADIUS_M})"},
    )  # fmt: skip
    return int(rows[0]["n"]) if rows else 0
