"""OpenFEMA NFIP claims and policies: county loss cost per policy-year (SPEC Prompt 1A, item 1).

Endpoints: the spec names v2 `FimaNfipClaims`, but v2 is deprecated (removal date 2026-10-15) and returned
0 rows for county 22051 when probed on 2026-10-17. v3 `NfipClaims` has the same fields and is the default.
Exposure comes from v3 `NfipPolicies` (live-checked 2026-10-17). Policies have no county code, only a
12-digit block-group `censusGeoid`, so they are selected by GEOID range.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
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
POLICIES_URL = "https://www.fema.gov/api/open/v3/NfipPolicies"
POLICY_FIELDS = (
    "id",  # lets paging detect duplicated rows (no stable $orderby is available for policies)
    "policyEffectiveDate",
    "policyTerminationDate",
    "policyCount",
    "totalBuildingInsuranceCoverage",
    "totalContentsInsuranceCoverage",
    "asOfDate",
)
WINDOW_START_YEAR = 2010  # NfipPolicies starts in 2010, so claims use the same window: the rate is like for like
PAGE_SIZE = 1000
MAX_PAGES = 300  # claims: 300k rows (Jefferson Parish, LA has about 136k)
# Policies have no usable count or date filter (both 503 live, 2026-10-17) and deep $skip is slow (about 30 s at
# 2,000 rows), so only small counties can be paged completely. Larger ones raise ExposureUnavailable.
MAX_POLICY_PAGES = 12
CONCURRENCY = 8
RETRIES = 2
BACKOFF_S = 0.5

log = logging.getLogger(__name__)


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


class ExposureUnavailable(Exception):
    """Claims were fetched but policy exposure is missing or incomplete, so no honest rate can be computed."""


@dataclass(frozen=True)
class CountyAggregate:
    """County loss cost over the window [WINDOW_START_YEAR, as-of), per policy-year of exposure."""

    claim_count: int
    paid_usd: float
    # The rest need policy exposure, which is None when the county has too many policies to page (see MAX_POLICY_PAGES).
    policy_years: float | None
    loss_cost_per_policy_year_usd: float | None
    mean_lcr: float | None  # annual paid / insured coverage-years: a true loss cost ratio
    prior: GammaPrior | None


def build_params(county_fips: str, top: int = PAGE_SIZE, skip: int = 0) -> dict[str, str]:
    params = {
        "$filter": f"(countyCode eq '{county_fips}' and yearOfLoss ge {WINDOW_START_YEAR})",
        "$top": str(top),
        "$select": ",".join(SELECT_FIELDS),
        "$orderby": "id",
        "$inlinecount": "allpages",
    }
    if skip:
        params["$skip"] = str(skip)
    return params


def policy_params(county_fips: str, top: int = PAGE_SIZE, skip: int = 0) -> dict[str, str]:
    """Policies carry a 12-digit block-group `censusGeoid` and no county code, so select by GEOID range."""
    lo, hi = county_fips + "0" * 7, f"{int(county_fips) + 1:05d}" + "0" * 7
    params = {
        "$filter": f"censusGeoid ge '{lo}' and censusGeoid lt '{hi}'",  # a date filter or $orderby 503s live
        "$top": str(top),
        "$select": ",".join(POLICY_FIELDS),
    }
    if skip:
        params["$skip"] = str(skip)
    return params


def _check_fips(county_fips: str) -> None:
    if not (county_fips.isdigit() and len(county_fips) == 5):
        raise ValueError(f"county_fips must be 5 digits: {county_fips!r}")


async def _get_json(client: httpx.AsyncClient, url: str, params: dict[str, str]) -> dict[str, Any]:
    """GET with a few retries: OpenFEMA answers 503 under load."""
    for attempt in range(RETRIES + 1):
        try:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            return resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            if attempt == RETRIES:
                raise
            log.warning("OpenFEMA %s attempt %d failed: %r", url.rsplit("/", 1)[-1], attempt + 1, exc)
            await asyncio.sleep(BACKOFF_S * (attempt + 1))
    raise AssertionError("unreachable")


async def _page_pages(
    client: httpx.AsyncClient,
    url: str,
    key: str,
    make_params: Any,
    first: dict[str, Any] | None = None,
    max_pages: int = MAX_PAGES,
) -> list[dict[str, Any]]:
    """Every row of a dataset query, fetched in concurrent batches of pages, up to MAX_PAGES."""
    rows: list[dict[str, Any]] = []
    page = 0
    total = None
    if first is not None:
        rows.extend(first.get(key, []))
        total = int(first.get("metadata", {}).get("count", 0)) or None
        page = 1
        if len(first.get(key, [])) < PAGE_SIZE:
            return _no_duplicates(rows, key)
    while page < max_pages:
        last = max_pages if total is None else min(max_pages, -(-total // PAGE_SIZE))
        batch = range(page, min(page + CONCURRENCY, last))
        if not batch:
            break
        bodies = await asyncio.gather(
            *(_get_json(client, url, make_params(skip=i * PAGE_SIZE)) for i in batch)
        )
        short = False
        for body in bodies:
            got = body.get(key, [])
            rows.extend(got)
            short = short or len(got) < PAGE_SIZE
        page = batch.stop
        if short:
            return _no_duplicates(rows, key)
    if page >= max_pages and (total is None or len(rows) < total):
        raise ExposureUnavailable(f"{key} exceeds {max_pages * PAGE_SIZE} rows: refusing to use a partial sample")
    return _no_duplicates(rows, key)


def _no_duplicates(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    """Skip-based paging without a stable order can repeat or drop rows; a repeated id proves it happened."""
    ids = [r["id"] for r in rows if "id" in r]
    if len(set(ids)) != len(ids):
        raise ExposureUnavailable(f"{key} paging returned duplicate rows: the sample is not trustworthy")
    return rows


def policy_years_of(row: dict[str, Any]) -> tuple[float, float]:
    """(policy-years, coverage-years in USD) of one policy record, truncated at the dataset as-of date."""
    window = datetime(WINDOW_START_YEAR, 1, 1, tzinfo=UTC)  # claims only cover the window
    start = max(datetime.fromisoformat(row["policyEffectiveDate"]), window)
    end_raw = row.get("policyTerminationDate") or row.get("asOfDate")
    end = datetime.fromisoformat(end_raw) if end_raw else start
    as_of = row.get("asOfDate")
    if as_of:
        end = min(end, datetime.fromisoformat(as_of))
    years = max((end - start).days, 0) / 365.0
    count = float(row.get("policyCount") or 1)
    cover = float(row.get("totalBuildingInsuranceCoverage") or 0) + float(row.get("totalContentsInsuranceCoverage") or 0)
    return count * years, cover * years


def aggregate(
    claim_rows: list[dict[str, Any]], policy_rows: list[dict[str, Any]] | None, claim_total: int
) -> CountyAggregate:
    claims = [normalize_claim(r) for r in claim_rows]
    paid = sum(c.paid_building_usd + c.paid_contents_usd for c in claims)
    if policy_rows is None:
        return CountyAggregate(claim_total, paid, None, None, None, None)
    py_total = cover_years = 0.0
    for row in policy_rows:
        py, cy = policy_years_of(row)
        py_total += py
        cover_years += cy
    if py_total <= 0 or cover_years <= 0:
        raise ExposureUnavailable("no policy exposure in the window")
    mean_lcr = paid / cover_years
    lcrs = [c.lcr for c in claims if c.lcr is not None]
    prior: GammaPrior | None = None
    try:
        claim_fit = gamma_mom_fit(lcrs)  # dispersion only: the mean comes from exposure
        prior = GammaPrior(alpha=claim_fit.alpha, beta=claim_fit.alpha / mean_lcr) if mean_lcr > 0 else None
    except ValueError:
        pass
    return CountyAggregate(claim_total, paid, py_total, paid / py_total, mean_lcr, prior)


async def fetch_county_aggregate(client: httpx.AsyncClient, county_fips: str) -> CountyAggregate:
    """All county claims (paged, not $top=1000) over policy exposure from NfipPolicies."""
    _check_fips(county_fips)
    first = await _get_json(client, OPENFEMA_URL, build_params(county_fips))
    total = int(first.get("metadata", {}).get("count", 0))
    claims, policies = await asyncio.gather(
        _page_pages(client, OPENFEMA_URL, "NfipClaims", lambda skip: build_params(county_fips, skip=skip), first),
        _page_pages(
            client, POLICIES_URL, "NfipPolicies", lambda skip: policy_params(county_fips, skip=skip),
            max_pages=MAX_POLICY_PAGES,
        ),
        return_exceptions=True,
    )
    if isinstance(claims, BaseException):
        raise claims
    if isinstance(policies, BaseException):
        if not isinstance(policies, (ExposureUnavailable, httpx.HTTPError)):
            raise policies
        log.warning("OpenFEMA policy exposure unavailable for %s: %s", county_fips, policies)
        policies = None
    return aggregate(claims, policies, total)


