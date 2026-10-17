"""Shared helpers for the NYC clients: Socrata (SODA2) queries, guarded calls, and the TTL caches."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, TypeVar

import httpx

from app.cache import TTLCache
from app.models.schemas import InputProvenance, ValueSource

log = logging.getLogger(__name__)

T = TypeVar("T")

TIMEOUT_S = 3.0  # every NYC lookup; the NYC path degrades field by field when one source is slow
SODA = "https://data.cityofnewyork.us/resource/"
WINDOW_YEARS = 5
DAY = 86_400.0


def window_start(now: datetime | None = None) -> str:
    """Socrata floating timestamp for the start of the 5-year window."""
    return ((now or datetime.now(UTC)) - timedelta(days=365 * WINDOW_YEARS)).strftime("%Y-%m-%dT00:00:00")


async def soda(client: httpx.AsyncClient, dataset: str, **params: Any) -> list[dict[str, Any]]:
    """GET a SODA2 resource as rows. Socrata returns 4xx JSON errors as an object, which is an error here."""
    resp = await client.get(f"{SODA}{dataset}.json", params=params)
    resp.raise_for_status()
    body = resp.json()
    if not isinstance(body, list):
        raise TypeError(f"Socrata {dataset} returned {type(body).__name__}: {str(body)[:120]}")
    return body


def cell(lat: float, lng: float, places: int = 4) -> tuple[float, float]:
    return (round(lat, places), round(lng, places))


@dataclass
class NycCaches:
    geosearch: TTLCache = field(default_factory=lambda: TTLCache(30 * DAY))
    pluto: TTLCache = field(default_factory=lambda: TTLCache(7 * DAY))
    footprint: TTLCache = field(default_factory=lambda: TTLCache(30 * DAY))
    dep: TTLCache = field(default_factory=lambda: TTLCache(30 * DAY))
    floodnet: TTLCache = field(default_factory=lambda: TTLCache(DAY / 4))
    complaints: TTLCache = field(default_factory=lambda: TTLCache(DAY / 4))
    catch_basins: TTLCache = field(default_factory=lambda: TTLCache(30 * DAY))
    units: TTLCache = field(default_factory=lambda: TTLCache(7 * DAY))
    dob: TTLCache = field(default_factory=lambda: TTLCache(DAY))
    zones: TTLCache = field(default_factory=lambda: TTLCache(30 * DAY))  # evacuation zone and Sandy extent


DEFAULT_CACHES = NycCaches()


async def guarded(name: str, call: Awaitable[T], timeout_s: float = TIMEOUT_S) -> T | None:
    """Run one lookup under its timeout; log any failure and return None so the field is UNAVAILABLE."""
    try:
        return await asyncio.wait_for(call, timeout_s)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 - a failed source degrades one field, never the request
        log.warning("NYC source %s unavailable: %s: %s", name, type(exc).__name__, exc)
        return None


def prov(field_name: str, source: ValueSource, source_name: str, vintage: str | None = None) -> InputProvenance:
    return InputProvenance(field=f"nyc.{field_name}", value_source=source, source_name=source_name, vintage=vintage)
