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

`base_rates_for(nri_rates)` is the seam: the NRI ingestion client builds `NriRates` for any tract and the caller
passes it to `simulate` explicitly.
"""

import json
import math
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Literal

from app.actuarial import constants
from app.actuarial.constants import get as c_get
from app.ingestion import nri
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
        if exposed <= 0:  # no exposed-value figure (or no exposure): fall back to the tract-wide building value
            return eal / self.buildvalue_usd if eal > 0 else 0.0
        return eal / exposed

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
    pluvial: float = 0.0  # NYC only: the pluvial share of the NRI inland-flood rate
    sewer: float = 0.0  # NYC only: the sewer-backup share

    def for_peril(self, peril: str) -> float:
        return {
            "FLOOD": self.flood, "WILDFIRE": self.wildfire, "WIND_HAIL": self.wind,
            "PLUVIAL": self.pluvial, "SEWER_BACKUP": self.sewer,
        }[peril]


def base_rates_for(
    nri: NriRates, basis: Literal["exposed", "all"] = "exposed", *, nyc: bool = False
) -> BaseRates:
    """Seam for any NRI source: the reference-home loss rate per peril for a tract.

    With `nyc` the inland-flood (IFLD) rate is divided among the mapped-zone, pluvial and sewer-backup perils by the
    registered shares and the coastal rate (CFLD) stays with FLOOD, so the tract flood total is unchanged."""
    flood, wildfire, wind = (nri.loss_rate(p, basis) for p in ("FLOOD", "WILDFIRE", "WIND_HAIL"))
    if not nyc:
        return BaseRates(flood, wildfire, wind, reference_hazard=nri.reference_hazard)
    ifld = nri.ealb_usd.get("IFLD", 0.0)
    exposed = nri.expb_usd.get("IFLD", 0.0)
    denominator = exposed if basis == "exposed" and exposed > 0 else nri.buildvalue_usd
    inland = ifld / denominator if denominator > 0 else 0.0
    share = c_get("nyc.ifld_split")
    return BaseRates(
        flood=flood - inland + share["FLOOD"] * inland, wildfire=wildfire, wind=wind,
        reference_hazard=nri.reference_hazard, pluvial=share["PLUVIAL"] * inland, sewer=share["SEWER_BACKUP"] * inland,
    )


def intercept_for(rate: float, reference_loss_without_intercept: float) -> float:
    """Closed form: the intercept a that makes AAL_ref = exp(a) * reference_loss_without_intercept equal `rate`."""
    floor = constants.get("nri.rate_floor")
    lo, hi = constants.get("nri.intercept_clamp")
    return min(hi, max(lo, math.log(max(rate, floor) / reference_loss_without_intercept)))


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


REFERENCE_MATCH_M = 100.0  # a parcel this close to a reference tract point is that reference parcel


def nri_from_tract(tract: "nri.TractPrior", reference_hazard: PublicHazardLayer) -> NriRates:
    """NriRates from the ingestion client's live tract figures (HAZARD codes IFLD, CFLD, WFIR, HRCN, SWND, HAIL).

    No tract-median rain, terrain or fuel is ingested, so the parcel's own live hazard layer is the tract's
    reference hazard: those inputs are then neutral relativities and the NRI rate sets the level."""
    return NriRates(
        tractfips=tract.tract_fips, buildvalue_usd=tract.buildvalue_usd, ealb_usd=dict(tract.ealb_usd),
        expb_usd=dict(tract.expb_usd), version=tract.version, reference_hazard=reference_hazard,
    )


def nearest_reference(r: ParcelScoreResponse) -> tuple[NriRates, bool]:
    """The nearest reference tract and whether the parcel IS that reference parcel (within 100 m)."""
    lng, lat = r.parcel_identity.centroid
    best = min(_tracts(), key=lambda t: distance_m(lat, lng, t[0][1], t[0][0]))
    return best[1], distance_m(lat, lng, best[0][1], best[0][0]) <= REFERENCE_MATCH_M


def resolve(r: ParcelScoreResponse, nri: NriRates | None) -> tuple[NriRates, bool]:
    """(tract figures, stand_in). An explicit `nri` is always used as given. With none, the nearest reference
    tract is a stand-in unless the parcel is the reference parcel itself; a stand-in makes the score
    indicative only. Nothing is read from any other request."""
    if nri is not None:
        return nri, False
    tract, exact = nearest_reference(r)
    return tract, not exact


def context_for(
    r: ParcelScoreResponse, nri: NriRates | None = None, *, nyc: bool = False
) -> tuple[BaseRates, float]:
    """(base rates, tract prior LCR) for the parcel's tract: `nri` when given, else the nearest reference tract."""
    tract = resolve(r, nri)[0]
    return base_rates_for(tract, nyc=nyc), tract.tract_prior_lcr
