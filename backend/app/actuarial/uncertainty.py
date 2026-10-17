"""Seeded Monte Carlo of per-peril compound loss with a shared-driver Gaussian copula.

Each draw carries two layers of randomness:

* Parameter uncertainty. Every peril's expected loss is scaled by a mean-one lognormal factor. The factors
  are driven by correlated standard normals (Gaussian copula): flood and wind share a driver in Gulf states,
  other pairs get a weak common correlation. This is what widens the AAL and score bands.
* Process uncertainty. Given the scaled rate, the annual event count is Poisson and each event draws a
  severity from the engine's spliced distribution (lognormal body, truncated GPD tail).

AAL quantiles and the score band come from the expected-loss draws; the 1-in-100 and 1-in-250 losses are
quantiles of the simulated annual aggregate. Both sit on the same credibility-blended basis as the priced AAL:
annual loss = Z * simulated parcel loss + (1 - Z) * tract prior * RCV, capped at the replacement cost, so its
mean is the priced loss. The method string reports p_any_loss, the chance of at least one event in a year.
Rare perils can put the 1-in-100 below the AAL: when P(any loss) is under 1% the 99th percentile is the
no-event (prior-only) value while the mean carries the rare large losses. Fixed seed, so output is reproducible.
"""

from dataclasses import dataclass

import numpy as np

from app.actuarial import compound_model as cm
from app.actuarial.constants import get as c
from app.actuarial.score_map import score_continuous_array

GULF_STATES = ("LA", "AL", "FL", "MS", "TX")
METHOD = "seeded Monte Carlo, 10k draws, Gaussian copula on peril drivers, Poisson-spliced severity"


@dataclass(frozen=True)
class McResult:
    aal_p05_usd: float
    aal_p50_usd: float
    aal_p95_usd: float
    score_p05: float
    score_p95: float
    loss_1_in_100_usd: float
    loss_1_in_250_usd: float
    method: str = METHOD


def correlation(perils: list[str], state: str) -> np.ndarray:
    rho = np.full((len(perils), len(perils)), c("mc.copula_rho_other"))
    if "FLOOD" in perils and "WIND_HAIL" in perils and state in GULF_STATES:
        i, j = perils.index("FLOOD"), perils.index("WIND_HAIL")
        rho[i, j] = rho[j, i] = c("mc.copula_rho_gulf")
    np.fill_diagonal(rho, 1.0)
    return rho


def _severities(rng: np.random.Generator, sp: cm.SevParams, shape: tuple[int, int]) -> np.ndarray:
    """Event severities as a fraction of RCV, from the spliced body/tail distribution."""
    cv = c("mc.body_cv")
    sig = np.sqrt(np.log1p(cv * cv))
    body = np.exp(np.log(max(sp.body_mean, 1e-9)) - sig * sig / 2 + sig * rng.standard_normal(shape))
    body = np.minimum(body, sp.body_cap)
    if sp.p_tail <= 0:
        return body
    g = 1 - (1 + sp.xi * (1 - cm.U_TAIL) / sp.sigma) ** (-1 / sp.xi)
    tail = cm.U_TAIL + sp.sigma / sp.xi * ((1 - rng.random(shape) * g) ** (-sp.xi) - 1)
    return np.where(rng.random(shape) < sp.p_tail, np.minimum(tail, 1.0), body)


def simulate_losses(
    terms: list[cm.PerilTerm],
    *,
    state: str,
    rcv_usd: float,
    tract_prior_lcr: float,
    z: float,
    draws: int | None = None,
    freeboard_known: bool = True,
) -> McResult:
    n_draws = int(c("mc.draws")) if draws is None else draws
    rng = np.random.default_rng(int(c("mc.seed")))
    perils = [t.peril for t in terms]
    chol = np.linalg.cholesky(correlation(perils, state))
    drivers = rng.standard_normal((n_draws, len(terms))) @ chol.T
    cv = np.array([c("mc.param_cv")[p] for p in perils])
    if not freeboard_known:  # an unknown first-floor height widens the flood band
        cv = np.where(np.array(perils) == "FLOOD", cv * c("mc.freeboard_missing_cv_mult"), cv)
    sig = np.sqrt(np.log1p(cv * cv))
    theta = np.exp(drivers * sig - sig * sig / 2)  # mean-one lognormal rate multipliers

    lam = np.array([t.n for t in terms]) * theta  # (draws, perils)
    expected = (lam * np.array([t.s for t in terms])).sum(axis=1)  # raw expected-loss fraction per draw
    post_draw = z * expected + (1 - z) * tract_prior_lcr
    aal = post_draw * rcv_usd
    scores = score_continuous_array(post_draw)

    annual = np.zeros(n_draws)
    cap = int(c("mc.max_events_per_peril"))
    counts = np.minimum(rng.poisson(np.minimum(lam, cap)), cap)
    for k, t in enumerate(terms):
        n_max = int(counts[:, k].max())
        if n_max == 0 or t.sev is None:
            continue
        sev = _severities(rng, t.sev, (n_draws, n_max))
        annual += (sev * (np.arange(n_max) < counts[:, k : k + 1])).sum(axis=1)
    p_any = float((counts.sum(axis=1) > 0).mean())
    annual = np.minimum(z * annual + (1 - z) * tract_prior_lcr, 1.0) * rcv_usd

    p05, p50, p95 = np.percentile(aal, [5, 50, 95])
    s05, s95 = np.percentile(scores, [5, 95])
    q100, q250 = np.percentile(annual, [99.0, 99.6])
    return McResult(
        aal_p05_usd=round(float(p05), 2),
        aal_p50_usd=round(float(p50), 2),
        aal_p95_usd=round(float(p95), 2),
        score_p05=round(float(s05), 1),
        score_p95=round(float(s95), 1),
        loss_1_in_100_usd=round(float(q100), 2),
        loss_1_in_250_usd=round(float(q250), 2),
        method=f"{METHOD}; p_any_loss={p_any:.4f}",
    )
