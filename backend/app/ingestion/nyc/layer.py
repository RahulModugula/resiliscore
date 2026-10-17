"""The NYC path: GeoSearch plus eleven city and federal-adjacent sources, assembled into the contract's NycLayer.

Every lookup runs in parallel under a 3 s timeout with a TTL cache. A failed source leaves its fields null (or
UNAVAILABLE for the stormwater scenarios) and marks them UNAVAILABLE in the provenance; nothing is guessed.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import httpx

from app.ingestion.nyc import (
    complaints311,
    dep_stormwater,
    dob,
    floodnet,
    footprints,
    geosearch,
    pluto,
    zones,
)
from app.ingestion.nyc.common import DEFAULT_CACHES, NycCaches, cell, guarded, prov
from app.ingestion.rasters import distance_m
from app.models.schemas import InputProvenance, NycLayer

log = logging.getLogger(__name__)

MAX_TEXT_POINT_GAP_M = 200.0  # a text match this far from the caller's point is a different place

SRC_GEOSEARCH = "NYC GeoSearch (DCP PAD)"
SRC_PLUTO = "NYC MapPLUTO (64uk-42ks)"
SRC_FOOTPRINTS = "NYC Building Footprints (5zhs-2jue)"
SRC_DEP = "NYC DEP Stormwater Flood Maps"
SRC_FLOODNET = "FloodNet NYC (aq7i-eu5q, kb2e-tjy3)"
SRC_311 = "NYC 311 (erm2-nwe9)"
SRC_BASINS = "NYC DEP catch basins (2w2g-fk3i)"
SRC_DOB = "NYC DOB (3h2n-5cm9 violations, w9ak-ipjd DOB NOW)"
SRC_EVAC = "NYC Hurricane Evacuation Zones (epne-qv9x)"
SRC_SANDY = "NYC Sandy Inundation Zone (5xsi-dfpx)"


@dataclass(frozen=True)
class NycResult:
    layer: NycLayer
    provenance: list[InputProvenance]
    address: geosearch.NycAddress
    footprint: footprints.BuildingFootprint | None
    pluto: pluto.Pluto | None


def is_nyc_county(county_fips: str | None) -> bool:
    return county_fips in geosearch.NYC_COUNTY_FIPS


async def resolve(
    client: httpx.AsyncClient, address: str | None, lat: float | None, lng: float | None, caches: NycCaches
) -> geosearch.NycAddress | None:
    """The PAD address for the text, else for the point. None when GeoSearch has no NYC match."""
    attempts: list[tuple[str, Callable[[], Awaitable[geosearch.NycAddress]]]] = []
    if address:
        key = " ".join(address.casefold().split())
        attempts.append(("search", lambda: caches.geosearch.get_or_set(key, lambda: geosearch.search(client, address))))
    if lat is not None and lng is not None:
        attempts.append(
            ("reverse", lambda: caches.geosearch.get_or_set(("r", *cell(lat, lng)), lambda: geosearch.reverse(client, lat, lng)))
        )
    for name, call in attempts:  # lazy: the reverse lookup is never started when the text already matched
        found = await guarded(f"geosearch.{name}", call())
        if found is None:
            continue
        if lat is not None and lng is not None and distance_m(lat, lng, found.lat, found.lng) > MAX_TEXT_POINT_GAP_M:
            log.warning("GeoSearch %s hit %r is %.0f m from the supplied point: ignored", name, found.label,
                        distance_m(lat, lng, found.lat, found.lng))  # fmt: skip
            continue
        return found
    return None


async def fetch_nyc(
    client: httpx.AsyncClient,
    address: str | None,
    lat: float | None = None,
    lng: float | None = None,
    caches: NycCaches | None = None,
) -> NycResult | None:
    caches = caches or DEFAULT_CACHES
    geo = await resolve(client, address, lat, lng, caches)
    if geo is None:
        return None
    c, pt = caches, cell(geo.lat, geo.lng)
    px, fp, dep, fn, cm, cb, db, ev, sy, un = await asyncio.gather(
        guarded("pluto", c.pluto.get_or_set(geo.bbl, lambda: pluto.fetch_pluto(client, geo.bbl))),
        guarded(
            "footprints",
            c.footprint.get_or_set(
                geo.bin or geo.bbl, lambda: footprints.fetch_footprint(client, geo.bin, geo.bbl, geo.lat, geo.lng)
            ),
        ),
        guarded("dep_stormwater", _stormwater(c, client, pt, geo)),
        guarded("floodnet", c.floodnet.get_or_set(pt, lambda: floodnet.fetch_floodnet(client, geo.lat, geo.lng))),
        guarded("311", c.complaints.get_or_set(pt, lambda: complaints311.fetch_complaints(client, geo.lat, geo.lng))),
        guarded("catch_basins", c.catch_basins.get_or_set(pt, lambda: complaints311.fetch_catch_basins(client, geo.lat, geo.lng))),
        guarded("dob", c.dob.get_or_set(geo.bin, lambda: dob.fetch_dob(client, geo.bin))) if geo.bin else _none(),
        guarded("evacuation", c.zones.get_or_set(("e", *pt), lambda: _evac(client, geo.lat, geo.lng))),
        guarded("sandy", c.zones.get_or_set(("s", *pt), lambda: zones.fetch_sandy_inundated(client, geo.lat, geo.lng))),
        guarded("pluto_units", c.units.get_or_set(pt, lambda: pluto.fetch_units_nearby(client, geo.lat, geo.lng))),
    )  # fmt: skip
    return _assemble(geo, px, fp, dep, fn, cm, cb, db, ev, sy, un)


def _stormwater_complete(dep: list[tuple[str, str]]) -> bool:
    """LIMITED_CURRENT is always UNAVAILABLE; any other UNAVAILABLE scenario is a failed layer."""
    return all(cls != "UNAVAILABLE" for s, cls in dep if s != "LIMITED_CURRENT")


async def _stormwater(
    c: NycCaches, client: httpx.AsyncClient, pt: tuple[float, float], geo: geosearch.NycAddress
) -> list[tuple[str, str]]:
    """Cached for 30 days, but only when every queryable scenario answered: a partial failure is retried."""
    hit = c.dep.get(pt)
    if hit is not None:
        return hit
    result = await dep_stormwater.fetch_stormwater(client, geo.lat, geo.lng)
    if _stormwater_complete(result):
        c.dep.put(pt, result)
    return result


async def _none() -> None:
    return None


async def _evac(client: httpx.AsyncClient, lat: float, lng: float) -> str:
    """Cacheable evacuation zone: "" means the point is outside every zone."""
    return await zones.fetch_evacuation_zone(client, lat, lng) or ""


def _assemble(
    geo: geosearch.NycAddress,
    px: pluto.Pluto | None,
    fp: footprints.BuildingFootprint | None,
    dep: list[tuple[str, str]] | None,
    fn: floodnet.FloodNetSummary | None,
    cm: complaints311.Complaints | None,
    cb: int | None,
    db: dob.DobRecord | None,
    ev: str | None,
    sy: bool | None,
    un: int | None = None,
) -> NycResult:
    p: list[InputProvenance] = [prov(f, "LIVE", SRC_GEOSEARCH) for f in ("bbl", "borough")]
    p.append(prov("bin", "LIVE" if (geo.bin or fp) else "UNAVAILABLE", SRC_GEOSEARCH))

    def mark(names: tuple[str, ...], ok: bool, source: str) -> None:
        p.extend(prov(n, "LIVE" if ok else "UNAVAILABLE", source) for n in names)

    mark(("bldg_class", "num_floors", "basement_code", "basement_type"), px is not None, SRC_PLUTO)
    year = px.year_built if px and px.year_built else (fp.construction_year if fp else None)
    p.append(prov("year_built", "LIVE" if year else "UNAVAILABLE", SRC_PLUTO if px and px.year_built else SRC_FOOTPRINTS))
    mark(("ground_elevation_ft", "roof_height_ft"), fp is not None, SRC_FOOTPRINTS)
    # LIMITED_CURRENT has no queryable official layer, so it is always UNAVAILABLE; the other three must answer.
    dep_ok = dep is not None and _stormwater_complete(dep)
    mark(("dep_stormwater",), dep_ok, SRC_DEP + " (LIMITED_CURRENT: no queryable layer)")

    sensors_nearby = bool(fn and fn.sensors)
    p.append(prov("floodnet_events_500m_5y", "LIVE" if sensors_nearby else "UNAVAILABLE",
                  SRC_FLOODNET if fn is None or sensors_nearby else "FloodNet NYC (no sensor within 500 m)"))  # fmt: skip
    p.append(prov("floodnet_max_depth_in", "LIVE" if sensors_nearby else "UNAVAILABLE", SRC_FLOODNET))
    mark(("sewer_backup_311_500m_5y", "street_flooding_311_500m_5y"), cm is not None, SRC_311)
    mark(("residential_units_500m",), un is not None, SRC_PLUTO)
    mark(("catch_basins_150m",), cb is not None, SRC_BASINS)
    mark(("dob_open_violations", "dob_cellar_conversion_flag"), db is not None, SRC_DOB)
    mark(("evacuation_zone",), ev is not None, SRC_EVAC)
    mark(("sandy_inundated",), sy is not None, SRC_SANDY)

    layer = NycLayer(
        bbl=geo.bbl,
        bin=geo.bin or (fp.bin if fp else None),
        borough=geo.borough,
        bldg_class=px.bldg_class if px else None,
        year_built=year,
        num_floors=px.num_floors if px else None,
        basement_code=px.basement_code if px else None,
        basement_type=px.basement_type if px else "UNKNOWN",  # type: ignore[arg-type]
        ground_elevation_ft=fp.ground_elevation_ft if fp else None,
        roof_height_ft=fp.roof_height_ft if fp else None,
        dep_stormwater=[
            {"scenario": s, "flood_class": cls}
            for s, cls in (dep or [(s, "UNAVAILABLE") for s in dep_stormwater.SCENARIOS])
        ],  # type: ignore[arg-type]
        floodnet_events_500m_5y=fn.events if sensors_nearby and fn else None,
        floodnet_max_depth_in=fn.max_depth_in if sensors_nearby and fn else None,
        sewer_backup_311_500m_5y=cm.sewer_backup if cm else None,
        street_flooding_311_500m_5y=cm.street_flooding if cm else None,
        residential_units_500m=un,
        catch_basins_150m=cb,
        dob_open_violations=db.open_violations if db else None,
        dob_cellar_conversion_flag=db.cellar_conversion if db else None,
        sandy_inundated=sy,
        evacuation_zone=(ev or None) if ev is not None else None,
    )
    return NycResult(layer, p, geo, fp, px)
