"""FloodNet street-flooding sensors: flood events and the deepest flood within 500 m over the last 5 years.

Sensors are Socrata kb2e-tjy3 (`location` point); events are aq7i-eu5q (`sensor_id`, `flood_start_time`,
`max_depth_inches`, no coordinates), so the events are selected through the sensors within 500 m.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.ingestion.nyc.common import soda, window_start

SENSORS = "kb2e-tjy3"
EVENTS = "aq7i-eu5q"
RADIUS_M = 500


@dataclass(frozen=True)
class FloodNetSummary:
    sensors: int
    events: int
    max_depth_in: float | None  # None when no event was recorded


def _sensor_list(ids: list[str]) -> str:
    for i in ids:
        if not all(c.isalnum() or c in "-_" for c in i):
            raise ValueError(f"unexpected sensor id {i!r}")
    return ",".join(f"'{i}'" for i in ids)


def parse_events(sensors: int, rows: list[dict]) -> FloodNetSummary:
    if not sensors:
        return FloodNetSummary(0, 0, None)
    row = rows[0] if rows else {}
    n = int(row.get("n") or 0)
    depth = row.get("max_depth")
    return FloodNetSummary(sensors, n, float(depth) if depth not in (None, "") and n else None)


async def fetch_floodnet(client: httpx.AsyncClient, lat: float, lng: float) -> FloodNetSummary:
    sensors = await soda(
        client, SENSORS, **{"$select": "sensor_id", "$where": f"within_circle(location,{lat},{lng},{RADIUS_M})"}
    )
    ids = [str(s["sensor_id"]) for s in sensors]
    if not ids:
        return FloodNetSummary(0, 0, None)
    rows = await soda(
        client, EVENTS,
        **{
            "$select": "count(*) as n, max(max_depth_inches) as max_depth",
            "$where": f"sensor_id in({_sensor_list(ids)}) AND flood_start_time > '{window_start()}'",
        },
    )  # fmt: skip
    return parse_events(len(ids), rows)
