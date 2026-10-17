"""FEMA National Risk Index tract-level expected annual loss rates: the tract prior.

Source: the NRI Census Tracts feature layer (ArcGIS Online, NRI_VER "December 2025"), live-checked 2026-10-17:
https://services.arcgis.com/XG15cJAlne2vxtgt/arcgis/rest/services/National_Risk_Index_Census_Tracts/FeatureServer/0
There is no OpenFEMA JSON API for the NRI. In v1.20 inland flooding is IFLD (not RFLD). The rate for a peril
is its building-value EAL (<PERIL>_EALB) divided by the tract building value (BUILDVALUE).
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

NRI_URL = (
    "https://services.arcgis.com/XG15cJAlne2vxtgt/arcgis/rest/services/"
    "National_Risk_Index_Census_Tracts/FeatureServer/0/query"
)
PERILS = {
    "IFLD": "inland flood",
    "CFLD": "coastal flood",
    "WFIR": "wildfire",
    "HAIL": "hail",
    "SWND": "strong wind",
    "HRCN": "hurricane",
}
OUT_FIELDS = ("TRACTFIPS", "NRI_VER", "BUILDVALUE", *(f"{p}_EALB" for p in PERILS))


@dataclass(frozen=True)
class TractPrior:
    tract_fips: str
    version: str
    rates: dict[str, float]  # peril code -> annual loss as a fraction of building value

    @property
    def total_rate(self) -> float:
        return sum(self.rates.values())


def parse_nri(payload: dict) -> TractPrior:
    if "error" in payload:
        raise ValueError(f"NRI error: {payload['error']}")
    features = payload.get("features")
    if not features:
        raise ValueError("no NRI tract at this point")
    a = features[0]["attributes"]
    value = a.get("BUILDVALUE")
    if not value or float(value) <= 0:
        raise ValueError(f"NRI tract {a.get('TRACTFIPS')} has no building value")
    rates = {p: float(a.get(f"{p}_EALB") or 0.0) / float(value) for p in PERILS}  # null EAL = peril absent
    return TractPrior(tract_fips=str(a["TRACTFIPS"]), version=str(a.get("NRI_VER") or "unknown"), rates=rates)


async def fetch_tract_prior(client: httpx.AsyncClient, lat: float, lng: float) -> TractPrior:
    resp = await client.get(
        NRI_URL,
        params={
            "geometry": f"{lng},{lat}",
            "geometryType": "esriGeometryPoint",
            "inSR": 4326,
            "outFields": ",".join(OUT_FIELDS),
            "returnGeometry": "false",
            "f": "json",
        },
    )
    resp.raise_for_status()
    return parse_nri(resp.json())
