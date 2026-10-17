"""SpatialIngestionEngine: parallel federal fetches with a 2.5 s per-call timeout and golden fallback (SPEC 1A)."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from typing import Literal, TypeVar

import httpx

from app.ingestion import openfema, rasters, usgs_3dep
from app.models.schemas import PublicHazardLayer

TIMEOUT_S = 2.5
PIN_RADIUS_M = 100.0  # a request this close to a golden centroid is the demo parcel and is served exactly

SourceFlag = Literal["live", "cache"]
T = TypeVar("T")


class SpatialIngestionEngine:
    def __init__(self, client: httpx.AsyncClient | None = None, timeout_s: float = TIMEOUT_S):
        self._client = client
        self._timeout_s = timeout_s

    async def fetch(
        self, address: str, lat: float, lng: float, county_fips: str, state: str
    ) -> tuple[PublicHazardLayer, dict[str, str], dict[str, SourceFlag]]:
        site = rasters.nearest_site(lat, lng, county_fips)
        golden = site.response.public_hazard_layer
        vintages = rasters.vintages_for(state)
        flags: dict[str, SourceFlag] = {"openfema": "cache", "usgs_3dep": "cache", "rasters": "cache"}

        if rasters.distance_m(lat, lng, site.lat, site.lng) <= PIN_RADIUS_M:
            return golden.model_copy(), vintages, flags

        owns_client = self._client is None
        client = self._client or httpx.AsyncClient()
        try:
            prior, lag = await asyncio.gather(
                self._guarded(openfema.fetch_county_prior(client, county_fips)),
                self._guarded(usgs_3dep.fetch_lag_ft(client, lat, lng)),
            )
        finally:
            if owns_client:
                await client.aclose()

        r = rasters.lookup_rasters(lat, lng, county_fips)
        update: dict = {**r.__dict__}
        if prior is not None:
            flags["openfema"] = "live"
            update["openfema_tract_claim_count"] = prior.claim_count
            update["openfema_tract_mean_lcr"] = prior.mean_lcr
        if lag is not None:
            flags["usgs_3dep"] = "live"
            elev = usgs_3dep.compute_elevations(lag, golden.bfe_ft_navd88)
            update["usgs_lag_ft"] = elev.usgs_lag_ft
            update["est_ffe_ft"] = elev.est_ffe_ft
            # The contract field is a non-null float, so "no BFE" is carried as 0.0, as in the golden parcels.
            update["freeboard_delta_h_ft"] = elev.freeboard_delta_h_ft or 0.0
        return golden.model_copy(update=update), vintages, flags

    async def _guarded(self, call: Awaitable[T]) -> T | None:
        """Run one call under the timeout; any error or timeout returns None so the caller uses the cache."""
        try:
            return await asyncio.wait_for(call, self._timeout_s)
        except Exception:  # noqa: BLE001 - spec: network glitches never fail a request
            return None
