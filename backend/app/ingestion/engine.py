"""SpatialIngestionEngine: parallel federal fetches, a 2.5 s budget per call, and honest provenance.

Every hazard field of a non-demo parcel comes from a live source or from a documented national default
(rasters.NATIONAL_DEFAULTS), and `input_provenance` says which. Nothing is borrowed from a golden parcel
unless the request is within PIN_RADIUS_M of that parcel's centroid, in which case the golden layer is served
exactly and every field is REFERENCE_PARCEL.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TypeVar

import httpx

from app import http
from app.cache import TTLCache
from app.ingestion import geocode as geocoder
from app.ingestion import landfire, nfhl, noaa, nri, openfema, rasters, usgs_3dep
from app.models.schemas import InputProvenance, PublicHazardLayer, ValueSource

log = logging.getLogger(__name__)

TIMEOUT_S = 2.5
GEOCODE_TIMEOUT_S = 5.0
COUNTY_LOAD_TIMEOUT_S = 120.0  # background budget for the paged county aggregate
PIN_RADIUS_M = 100.0  # a request this close to a golden centroid is the demo parcel and is served exactly

T = TypeVar("T")

DAY, MONTH = 86_400.0, 30 * 86_400.0

# Field -> (source name, vintage) for the live sources.
SRC_NFHL = ("FEMA NFHL S_FLD_HAZ_AR", rasters.LIVE_VINTAGES["FEMA_NFHL"])
SRC_EPQS = ("USGS 3DEP EPQS", rasters.LIVE_VINTAGES["USGS_3DEP"])
SRC_NRI = ("FEMA National Risk Index", rasters.LIVE_VINTAGES["FEMA_NRI"])
SRC_LANDFIRE = ("LANDFIRE FBFM40", rasters.LIVE_VINTAGES["LANDFIRE"])
SRC_NOAA = ("NOAA PFDS Atlas 14", rasters.LIVE_VINTAGES["NOAA_PFDS"])
SRC_OPENFEMA = ("OpenFEMA NfipClaims + NfipPolicies", rasters.LIVE_VINTAGES["OpenFEMA"])
SRC_WRC = ("USFS Wildfire Risk to Communities burn probability (no usable scale)", "RDS-2020-0016-2")
SRC_DEFAULT ="National default (no live source)"
KEY_INPUTS = ("fema_flood_zone", "usgs_lag_ft", "tract_prior_lcr")


@dataclass
class Caches:
    """TTL caches shared across requests (module default) or isolated per test."""

    geocode: TTLCache = field(default_factory=lambda: TTLCache(DAY))
    county: TTLCache = field(default_factory=lambda: TTLCache(DAY))  # per county aggregate
    nri: TTLCache = field(default_factory=lambda: TTLCache(7 * DAY))  # per tract
    nfhl: TTLCache = field(default_factory=lambda: TTLCache(DAY))  # per ~11 m cell
    epqs: TTLCache = field(default_factory=lambda: TTLCache(MONTH))  # per ~11 m tile
    raster: TTLCache = field(default_factory=lambda: TTLCache(MONTH))  # LANDFIRE and NOAA, per ~110 m cell
    inflight: dict[str, asyncio.Task] = field(default_factory=dict)


DEFAULT_CACHES = Caches()


@dataclass(frozen=True)
class HazardResult:
    layer: PublicHazardLayer
    vintages: dict[str, str]
    provenance: list[InputProvenance]
    indicative_only: bool
    tract_prior_lcr: float | None  # None: keep the response's own prior (golden parcels)
    nri_rates: dict[str, float] = field(default_factory=dict)  # per-peril tract EAL rates, when live


def _prov(name: str, source: ValueSource, src: tuple[str, str] | str, vintage: str | None = None) -> InputProvenance:
    source_name, vint = (src, vintage) if isinstance(src, str) else src
    return InputProvenance(field=name, value_source=source, source_name=source_name, vintage=vint)


class SpatialIngestionEngine:
    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        timeout_s: float = TIMEOUT_S,
        caches: Caches | None = None,
    ):
        self._client = client
        self._timeout_s = timeout_s
        self._caches = caches or DEFAULT_CACHES

    async def geocode(self, address: str) -> geocoder.Geocode:
        """Resolve an address alone to a point and FIPS codes. Raises if it cannot (nothing to fall back to)."""
        key = " ".join(address.casefold().split())

        async def go(client: httpx.AsyncClient) -> geocoder.Geocode:
            return await self._caches.geocode.get_or_set(key, lambda: geocoder.geocode(client, address))

        return await self._with_client(lambda c: asyncio.wait_for(go(c), GEOCODE_TIMEOUT_S))

    async def fetch(
        self, address: str, lat: float, lng: float, county_fips: str, state: str, tract_fips: str | None = None
    ) -> HazardResult:
        pinned = rasters.nearest_site(lat, lng, county_fips)
        if rasters.distance_m(lat, lng, pinned.lat, pinned.lng) <= PIN_RADIUS_M:
            return self._reference(pinned)
        return await self._with_client(lambda c: self._live(c, lat, lng, county_fips, tract_fips))

    async def _with_client(self, run: Callable[[httpx.AsyncClient], Awaitable[T]]) -> T:
        client = self._client or http.get_client()
        if client is not None:
            return await run(client)
        async with http.new_client() as own:
            return await run(own)

    # ------------------------------------------------------------------------------------------------

    @staticmethod
    def _reference(site: rasters.GoldenSite) -> HazardResult:
        r = site.response
        name = f"Golden scenario {site.key}"
        fields = [*PublicHazardLayer.model_fields, "tract_prior_lcr"]
        return HazardResult(
            layer=r.public_hazard_layer.model_copy(),
            vintages=dict(r.regulatory_compliance.dataset_vintages),
            provenance=[_prov(f, "REFERENCE_PARCEL", name, "contracts/golden_scenarios.json") for f in fields],
            indicative_only=False,
            tract_prior_lcr=None,
        )

    async def _live(
        self, client: httpx.AsyncClient, lat: float, lng: float, county_fips: str, tract_fips: str | None
    ) -> HazardResult:
        c = self._caches
        cell4, cell3 = (round(lat, 4), round(lng, 4)), (round(lat, 3), round(lng, 3))
        tract_key = tract_fips or f"pt:{cell3}"
        county, tract, flood, lag, fuel, rain = await asyncio.gather(
            self._guarded("openfema", self._county(client, county_fips)),
            self._guarded("nri", c.nri.get_or_set(tract_key, lambda: nri.fetch_tract_prior(client, lat, lng))),
            self._guarded(
                "nfhl",
                c.nfhl.get_or_set(cell4, lambda: nfhl.fetch_flood_zone(client, lat, lng)),
                timeout_s=self._timeout_s + (nfhl.NFHL_TIMEOUT_S - TIMEOUT_S),  # NFHL is slow: +0.5 s
            ),
            self._guarded("epqs", c.epqs.get_or_set(cell4, lambda: usgs_3dep.fetch_lag_ft(client, lat, lng))),
            self._guarded("landfire", c.raster.get_or_set(("lf", cell3), lambda: self._fuel(client, lat, lng))),
            self._guarded(
                "noaa",
                c.raster.get_or_set(("pf", cell3), lambda: noaa.fetch_p24h_100yr_in(client, lat, lng)),
            ),
        )
        return self._assemble(county, tract, flood, lag, fuel, rain)

    @staticmethod
    async def _fuel(client: httpx.AsyncClient, lat: float, lng: float) -> str:
        """Fuel model code, or "" for a cacheable "no data here" (the default then applies)."""
        try:
            return await landfire.fetch_fuel_model(client, lat, lng)
        except landfire.NoFuelData:
            return ""

    async def _county(self, client: httpx.AsyncClient, fips: str) -> openfema.CountyAggregate:
        """The county aggregate loads in the background: this request waits for it only within its budget."""
        c = self._caches
        hit = c.county.get(fips)
        if hit is not None:
            return hit
        loop = asyncio.get_running_loop()
        task = c.inflight.get(fips)
        if task is None or task.get_loop() is not loop or task.done():

            async def load() -> openfema.CountyAggregate:
                try:
                    agg = await asyncio.wait_for(openfema.fetch_county_aggregate(client, fips), COUNTY_LOAD_TIMEOUT_S)
                    c.county.put(fips, agg)
                    return agg
                except Exception as exc:
                    # Nobody awaits this task once the request times out, so log here or the failure is invisible.
                    log.warning("county aggregate for %s failed: %s: %s", fips, type(exc).__name__, exc)
                    raise
                finally:
                    c.inflight.pop(fips, None)

            task = c.inflight[fips] = loop.create_task(load())
            # A load nobody awaits any more (the request timed out) must not warn about an unread exception.
            task.add_done_callback(lambda t: t.cancelled() or t.exception())
        return await asyncio.shield(task)

    async def _guarded(self, name: str, call: Awaitable[T], timeout_s: float | None = None) -> T | None:
        """Run one lookup under its timeout. On any failure log it and return None so the caller uses a default."""
        try:
            return await asyncio.wait_for(call, timeout_s or self._timeout_s)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - spec: a failed source never fails the request
            log.warning("ingestion source %s unavailable: %s: %s", name, type(exc).__name__, exc)
            return None

    @staticmethod
    def _assemble(
        county: openfema.CountyAggregate | None,
        tract: nri.TractPrior | None,
        flood: nfhl.FloodZone | None,
        lag: float | None,
        fuel: str | None,
        rain: float | None,
    ) -> HazardResult:
        d = rasters.NATIONAL_DEFAULTS
        values: dict = {}
        prov: list[InputProvenance] = []

        def put(name: str, value: object, live: bool, src: tuple[str, str], *, unavailable: bool = False) -> None:
            values[name] = value
            if live:
                prov.append(_prov(name, "LIVE", src))
            elif unavailable:
                prov.append(_prov(name, "UNAVAILABLE", src))
            else:
                prov.append(_prov(name, "DEFAULT", SRC_DEFAULT))

        put("fema_flood_zone", flood.zone if flood else d["fema_flood_zone"], flood is not None, SRC_NFHL)
        # No BFE is a legitimate answer in zone X, but with no NFHL answer at all it is unavailable.
        values["bfe_ft_navd88"] = flood.bfe_ft if flood else None
        prov.append(_prov("bfe_ft_navd88", "LIVE" if flood else "UNAVAILABLE", SRC_NFHL))

        offset = float(d["foundation_offset_ft"])
        bfe = values["bfe_ft_navd88"]
        if lag is not None:
            elev = usgs_3dep.compute_elevations(lag, bfe, offset)
            values["usgs_lag_ft"], values["est_ffe_ft"] = elev.usgs_lag_ft, elev.est_ffe_ft
            # The contract field is a non-null float, so "no BFE" is carried as 0.0, as in the golden parcels.
            values["freeboard_delta_h_ft"] = elev.freeboard_delta_h_ft or 0.0
            prov.append(_prov("usgs_lag_ft", "LIVE", SRC_EPQS))
            prov.append(_prov("est_ffe_ft", "DEFAULT", "LAG + assumed 2.0 ft slab-on-grade foundation offset"))
            prov.append(_prov("freeboard_delta_h_ft", "DEFAULT" if bfe is not None else "UNAVAILABLE", SRC_NFHL))
        else:
            values.update(usgs_lag_ft=0.0, est_ffe_ft=0.0, freeboard_delta_h_ft=0.0)
            for f in ("usgs_lag_ft", "est_ffe_ft", "freeboard_delta_h_ft"):
                prov.append(_prov(f, "UNAVAILABLE", SRC_EPQS))

        put("noaa_atlas15_p24h_100yr_in", rain if rain is not None else d["noaa_atlas15_p24h_100yr_in"], rain is not None, SRC_NOAA)
        put("atlas15_cmip6_mult", d["atlas15_cmip6_mult"], False, SRC_NOAA)
        put("landfire_fbfm40_code", fuel or d["landfire_fbfm40_code"], bool(fuel), SRC_LANDFIRE)
        for f in ("hand_rel_elev_ft", "twi_index", "slope_deg", "wui_class"):
            put(f, d[f], False, ("", ""))

        # USFS WRC burn probability: the only reachable mirror (imagery.geoplatform.gov, checked 2026-10-17) says its
        # "pixel values have been altered ... for visualization" and publishes no scale factor, so any conversion to a
        # 0-1 probability would be a guess. Left null and marked UNAVAILABLE until the source data is ingested.
        values["wrc_burn_probability"] = None
        prov.append(_prov("wrc_burn_probability", "UNAVAILABLE", SRC_WRC))

        if county is not None:
            values["openfema_tract_claim_count"] = county.claim_count
            prov.append(_prov("openfema_tract_claim_count", "LIVE", SRC_OPENFEMA))
            # Without policy exposure there is no honest loss cost ratio (claims alone have no denominator).
            values["openfema_tract_mean_lcr"] = county.mean_lcr or 0.0
            prov.append(_prov("openfema_tract_mean_lcr", "LIVE" if county.mean_lcr else "UNAVAILABLE", SRC_OPENFEMA))
        else:
            values.update(openfema_tract_claim_count=0, openfema_tract_mean_lcr=0.0)
            for f in ("openfema_tract_claim_count", "openfema_tract_mean_lcr"):
                prov.append(_prov(f, "UNAVAILABLE", SRC_OPENFEMA))

        if tract is not None:
            prior = tract.total_rate
            prov.append(_prov("tract_prior_lcr", "LIVE", SRC_NRI))
        else:
            prior = float(d["tract_prior_lcr"])
            prov.append(_prov("tract_prior_lcr", "DEFAULT", SRC_DEFAULT))

        status = {p.field: p.value_source for p in prov}
        vintages = dict(rasters.LIVE_VINTAGES)
        return HazardResult(
            layer=PublicHazardLayer(**values),
            vintages=vintages,
            provenance=prov,
            indicative_only=any(status[k] != "LIVE" for k in KEY_INPUTS),
            tract_prior_lcr=prior,
            nri_rates=dict(tract.rates) if tract else {},
        )
