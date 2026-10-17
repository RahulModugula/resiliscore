"""Hurricane evacuation zone (Socrata epne-qv9x, field `hurricane_`) and Sandy inundation extent (5xsi-dfpx).

Both are polygon datasets queried with `intersects(the_geom, 'POINT(lng lat)')`, live-checked 2026-10-17.
A point in no evacuation polygon returns None with LIVE provenance: it is outside every zone.
"""

from __future__ import annotations

import httpx

from app.ingestion.nyc.common import soda

EVACUATION = "epne-qv9x"
SANDY = "5xsi-dfpx"


def _point(lat: float, lng: float) -> str:
    return f"intersects(the_geom,'POINT({lng:.7f} {lat:.7f})')"


async def fetch_evacuation_zone(client: httpx.AsyncClient, lat: float, lng: float) -> str | None:
    rows = await soda(client, EVACUATION, **{"$select": "hurricane_", "$where": _point(lat, lng), "$limit": 1})
    return str(rows[0]["hurricane_"]) if rows and rows[0].get("hurricane_") not in (None, "") else None


async def fetch_sandy_inundated(client: httpx.AsyncClient, lat: float, lng: float) -> bool:
    rows = await soda(client, SANDY, **{"$select": "id", "$where": _point(lat, lng), "$limit": 1})
    return bool(rows)
