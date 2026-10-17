"""OpenFEMA NFIP claims client and Gamma prior (SPEC Prompt 1A, item 1).

Endpoint: the spec names v2 `FimaNfipClaims`, but v2 is deprecated (removal date 2026-10-15) and returned
0 rows for county 22051 when probed on 2026-10-17. v3 `NfipClaims` has the same fields and is the default.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import fmean, pvariance
from typing import Any, NamedTuple

import httpx

OPENFEMA_URL = "https://www.fema.gov/api/open/v3/NfipClaims"
SELECT_FIELDS = (
    "amountPaidOnBuildingClaim",
    "amountPaidOnContentsClaim",
    "baseFloodElevation",
    "lowestFloorElevation",
    "lowestAdjacentGrade",
    "elevationDifference",
    "ratedFloodZone",
    "elevationCertificateIndicator",
    "totalBuildingInsuranceCoverage",
    "totalContentsInsuranceCoverage",
)
MIN_YEAR_OF_LOSS = 2010
PAGE_SIZE = 1000


@dataclass(frozen=True)
class Claim:
    """One NFIP claim, normalised. `elevation_difference` is None whenever BFE is missing."""

    paid_building_usd: float
    paid_contents_usd: float
    insured_usd: float
    bfe_ft: float | None
    lowest_floor_ft: float | None
    lowest_adjacent_grade_ft: float | None
    elevation_difference_ft: float | None
    rated_flood_zone: str | None
    elevation_certificate: str | None

    @property
    def lcr(self) -> float | None:
        """Claim-level loss cost ratio: paid / insured value. None if nothing was insured."""
        if self.insured_usd <= 0:
            return None
        return (self.paid_building_usd + self.paid_contents_usd) / self.insured_usd


class GammaPrior(NamedTuple):
    """Gamma(shape alpha, rate beta); prior mean is alpha / beta."""

    alpha: float
    beta: float


@dataclass(frozen=True)
class CountyPrior:
    prior: GammaPrior | None
    claim_count: int
    mean_lcr: float


def _num(value: Any) -> float | None:
    return None if value is None else float(value)


def normalize_claim(raw: dict[str, Any]) -> Claim:
    """Spec data-hygiene rule: a null/missing baseFloodElevation forces elevationDifference = None, never 0."""
    bfe = _num(raw.get("baseFloodElevation"))
    diff = _num(raw.get("elevationDifference")) if bfe is not None else None
    return Claim(
        paid_building_usd=_num(raw.get("amountPaidOnBuildingClaim")) or 0.0,
        paid_contents_usd=_num(raw.get("amountPaidOnContentsClaim")) or 0.0,
        insured_usd=(_num(raw.get("totalBuildingInsuranceCoverage")) or 0.0)
        + (_num(raw.get("totalContentsInsuranceCoverage")) or 0.0),
        bfe_ft=bfe,
        lowest_floor_ft=_num(raw.get("lowestFloorElevation")),
        lowest_adjacent_grade_ft=_num(raw.get("lowestAdjacentGrade")),
        elevation_difference_ft=diff,
        rated_flood_zone=raw.get("ratedFloodZone"),
        elevation_certificate=None
        if raw.get("elevationCertificateIndicator") is None
        else str(raw["elevationCertificateIndicator"]),
    )


def gamma_mom_fit(values: list[float]) -> GammaPrior:
    """Gamma method of moments: alpha = mean^2 / var, beta = mean / var (rate parameterisation)."""
    positive = [v for v in values if v > 0]
    if len(positive) < 2:
        raise ValueError("need at least 2 positive values for a Gamma fit")
    mean, var = fmean(positive), pvariance(positive)
    if var <= 0:
        raise ValueError("zero variance: Gamma fit is degenerate")
    return GammaPrior(alpha=mean * mean / var, beta=mean / var)


def build_params(county_fips: str, top: int = PAGE_SIZE) -> dict[str, str]:
    return {
        "$filter": f"(countyCode eq '{county_fips}' and yearOfLoss ge {MIN_YEAR_OF_LOSS})",
        "$top": str(top),
        "$select": ",".join(SELECT_FIELDS),
        "$inlinecount": "allpages",
    }


async def fetch_county_claims(
    client: httpx.AsyncClient, county_fips: str
) -> tuple[list[Claim], int]:
    """Return (claims in the first page, total matching claims in the county)."""
    if not (county_fips.isdigit() and len(county_fips) == 5):
        raise ValueError(f"county_fips must be 5 digits: {county_fips!r}")
    resp = await client.get(OPENFEMA_URL, params=build_params(county_fips))
    resp.raise_for_status()
    body = resp.json()
    rows = body.get("NfipClaims", [])
    total = int(body.get("metadata", {}).get("count", len(rows)))
    return [normalize_claim(r) for r in rows], total


async def fetch_county_prior(client: httpx.AsyncClient, county_fips: str) -> CountyPrior:
    """County empirical prior (alpha_j, beta_j) for the Gamma loss-cost prior. The prior is None if unfittable."""
    claims, total = await fetch_county_claims(client, county_fips)
    lcrs = [c.lcr for c in claims if c.lcr is not None]
    try:
        prior = gamma_mom_fit(lcrs)
    except ValueError:
        prior = None
    return CountyPrior(prior=prior, claim_count=total, mean_lcr=fmean(lcrs) if lcrs else 0.0)
