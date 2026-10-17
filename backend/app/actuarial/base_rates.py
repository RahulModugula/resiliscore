"""External base rates: FEMA National Risk Index building loss rates per tract.

Each peril's frequency intercept is solved in closed form so that a reference home (unmitigated, tract-typical
era, no freeboard verification) matches the NRI building loss rate in its tract. The compound model's
relativities (Hazus depth-damage, freeboard through first-floor height, IBHS wildfire, FORTIFIED, Class 4 hail)
then move a parcel away from that tract mean. Nothing here is fitted to a demo score.

Rates are fractions of replacement value:
* FLOOD     = IFLD + CFLD
* WILDFIRE  = WFIR
* WIND_HAIL = HRCN + SWND + HAIL
Basis. The model only runs a peril where the parcel is in that hazard (flood zone A/V, WUI), so the target is
the loss rate among exposed buildings, EALB / EXPB. The tract-wide EALB / BUILDVALUE dilutes it with buildings
that have no exposure (S2 wildfire: 3.9 bps tract-wide, 84 bps among exposed). `basis="all"` gives the
tract-wide figure. The credibility prior is the tract-wide sum, because it describes a typical home in the tract.

`base_rates_for(nri_rates)` is the seam: the ingestion lane's NRI client will build `NriRates` for any tract.
"""

import json
import math
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Literal

from app.actuarial import constants
from app.ingestion.rasters import distance_m
from app.models.schemas import ParcelScoreResponse, PublicHazardLayer

DATA_PATH = Path(__file__).resolve().parents[2] / "data" / "nri_reference_tracts.json"
HAZARD_GROUPS = {"FLOOD": ("IFLD", "CFLD"), "WILDFIRE": ("WFIR",), "WIND_HAIL": ("HRCN", "SWND", "HAIL")}


@dataclass(frozen=True)
class NriRates:
    """One tract's NRI building figures, in dollars, by hazard code (IFLD, CFLD, WFIR, HRCN, SWND, HAIL)."""

    tractfips: str
    buildvalue_usd: float
    ealb_usd: dict[str, float]
    expb_usd: dict[str, float]
    version: str = "v1.20"
    reference_hazard: PublicHazardLayer | None = None

    def loss_rate(self, peril: str, basis: Literal["exposed", "all"] = "exposed") -> float:
        codes = HAZARD_GROUPS[peril]
        eal = sum(self.ealb_usd.get(c, 0.0) for c in codes)
        if basis == "all":
            return eal / self.buildvalue_usd
        exposed = max((self.expb_usd.get(c, 0.0) for c in codes), default=0.0)
        return eal / exposed if exposed > 0 else 0.0

    @property
    def tract_prior_lcr(self) -> float:
        """Tract-wide building loss rate over every NRI hazard the model covers."""
        return sum(self.ealb_usd.get(c, 0.0) for codes in HAZARD_GROUPS.values() for c in codes) / self.buildvalue_usd


@dataclass(frozen=True)
class BaseRates:
    """Target reference-home loss rates (fraction of RCV) per modeled peril."""

    flood: float
    wildfire: float
    wind: float
    reference_hazard: PublicHazardLayer | None = None

    def for_peril(self, peril: str) -> float:
        return {"FLOOD": self.flood, "WILDFIRE": self.wildfire, "WIND_HAIL": self.wind}[peril]


def base_rates_for(nri: NriRates, basis: Literal["exposed", "all"] = "exposed") -> BaseRates:
    """Seam for any NRI source: the reference-home loss rate per peril for a tract."""
    return BaseRates(
        *(nri.loss_rate(p, basis) for p in ("FLOOD", "WILDFIRE", "WIND_HAIL")),
        reference_hazard=nri.reference_hazard,
    )


def intercept_for(rate: float, reference_loss_without_intercept: float) -> float:
    """Closed form: the intercept a that makes AAL_ref = exp(a) * reference_loss_without_intercept equal `rate`."""
    floor = constants.get("nri.rate_floor")
    return math.log(max(rate, floor) / reference_loss_without_intercept)


@cache
def _tracts() -> tuple[tuple[tuple[float, float], NriRates, tuple[str, ...]], ...]:
    doc = json.loads(DATA_PATH.read_text())
    out = []
    for t in doc["tracts"]:
        rates = NriRates(
            tractfips=t["tractfips"],
            buildvalue_usd=float(t["buildvalue_usd"]),
            ealb_usd={h: float(v["ealb_usd"]) for h, v in t["hazards"].items()},
            expb_usd={h: float(v["expb_usd"]) for h, v in t["hazards"].items()},
            version=doc["nri_version"],
            reference_hazard=PublicHazardLayer.model_validate(t["reference_hazard"]),
        )
        out.append(((t["point_lng_lat"][0], t["point_lng_lat"][1]), rates, tuple(t["scenario_ids"])))
    return tuple(out)


def nri_for_parcel(r: ParcelScoreResponse) -> NriRates:
    """NRI figures for the parcel's tract. Until the ingestion lane's NRI client supplies the real tract, this is
    the nearest reference tract (exact for the golden parcels): a REFERENCE_PARCEL stand-in, so any score
    that uses it from afar is indicative only (see provenance)."""
    lng, lat = r.parcel_identity.centroid
    return min(_tracts(), key=lambda t: distance_m(lat, lng, t[0][1], t[0][0]))[1]


def context_for(r: ParcelScoreResponse) -> tuple[BaseRates, float]:
    """(base rates, tract prior LCR) from NRI for the parcel's tract."""
    nri = nri_for_parcel(r)
    return base_rates_for(nri), nri.tract_prior_lcr
