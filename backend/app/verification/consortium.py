"""Consortium credibility prototype. SYNTHETIC: no carrier data is used anywhere in this module.

Two made-up carriers each contribute anonymised, verified-mitigation outcomes: per-cohort mean loss ratios
(cohort = a class of verified mitigation, say "Class A roof + Zone 0 clear"). Bühlmann-Straub credibility
needs k = sigma^2 / tau^2. A carrier's cohorts are few, so its k is noisy; pooling both carriers' cohorts
gives a steadier k, and so a tighter Z = w / (w + k). The spread is measured across replications of the
same synthetic experiment, so the shrinking is an average effect, not one lucky seed.
"""

import random
import statistics
from typing import Any

from fastapi import APIRouter

from app.actuarial.credibility import K as ENGINE_K

router = APIRouter(prefix="/v1/consortium")

TRUE_SIGMA2 = 0.6  # within-cohort variance of a single policy-year, as in the engine
TRUE_TAU2 = TRUE_SIGMA2 / ENGINE_K  # between-cohort variance, so the true k equals the engine's k
POLICY_YEARS_PER_COHORT = 25
REFERENCE_W = 8.0  # credibility weight of a parcel with one strong certificate (Z = w / (w + k))
COHORTS_PER_CARRIER = (4, 8, 16, 32, 64)  # contributed cohorts per carrier, growing with pooled exposure
REPLICATIONS = 200
SEED = 20261017


def estimate_k(cohort_means: list[list[float]]) -> float | None:
    """Method-of-moments Bühlmann k from cohorts of equal size. None when tau^2 is not identifiable."""
    n = len(cohort_means[0])
    m = len(cohort_means)
    within = statistics.fmean(statistics.variance(c) for c in cohort_means)
    means = [statistics.fmean(c) for c in cohort_means]
    tau2 = statistics.variance(means) - within / n
    if m < 2 or tau2 <= 0:
        return None
    return within / tau2


def _cohorts(rng: random.Random, count: int) -> list[list[float]]:
    out = []
    for _ in range(count):
        theta = rng.gauss(0.0, TRUE_TAU2**0.5)
        out.append([rng.gauss(theta, TRUE_SIGMA2**0.5) for _ in range(POLICY_YEARS_PER_COHORT)])
    return out


def _summary(ks: list[float]) -> dict[str, float]:
    zs = [REFERENCE_W / (REFERENCE_W + k) for k in ks]
    return {
        "k_mean": round(statistics.fmean(ks), 4),
        "k_sd": round(statistics.stdev(ks), 4),
        "z_mean": round(statistics.fmean(zs), 4),
        "z_sd": round(statistics.stdev(zs), 4),
    }


def run_experiment() -> list[dict[str, Any]]:
    """For each exposure level: carrier A alone vs A and B pooled, over `REPLICATIONS` synthetic draws."""
    rng = random.Random(SEED)
    steps = []
    for per_carrier in COHORTS_PER_CARRIER:
        alone, pooled = [], []
        for _ in range(REPLICATIONS):
            a, b = _cohorts(rng, per_carrier), _cohorts(rng, per_carrier)
            k_alone, k_pooled = estimate_k(a), estimate_k(a + b)
            if k_alone is not None and k_pooled is not None:
                alone.append(k_alone)
                pooled.append(k_pooled)
        steps.append({
            "cohorts_per_carrier": per_carrier,
            "pooled_policy_years": 2 * per_carrier * POLICY_YEARS_PER_COHORT,
            "usable_replications": len(pooled),
            "carrier_alone": _summary(alone),
            "pooled": _summary(pooled),
        })
    return steps


_cache: dict[str, Any] = {}


@router.get("/credibility")
def consortium_credibility() -> dict[str, Any]:
    if not _cache:
        _cache.update({
            "synthetic": True,
            "disclaimer": (
                "Two synthetic carriers; every number is simulated. It shows the mechanism, not real carrier "
                "outcomes."
            ),
            "carriers": ["SYNTHETIC_CARRIER_A", "SYNTHETIC_CARRIER_B"],
            "true_k": round(ENGINE_K, 4),
            "reference_w": REFERENCE_W,
            "replications": REPLICATIONS,
            "steps": run_experiment(),
        })
    return _cache
