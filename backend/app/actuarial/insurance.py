"""Insurance layer: deductible, loads and the premium build.

Net expected loss is E[(S - d)+] summed over perils, from the engine's own severity distributions, with
d the deductible as a share of RCV. The indicated premium is
(net expected loss + fixed expense) / (1 - variable expense - profit). The expense and profit loads are
explicit parameters (validated: false in the registry): no primary figure was found, so replace them with the
filed rate manual or NAIC Profitability by Line before relying on the dollar output.

The modeled mitigation credit is the fall in the non-flood expected loss between the unmitigated parcel and
the parcel as verified, on the raw n * s basis (flood is excluded because the filed credit excludes NFIP flood).
It sits beside the filed statutory credit and the two are reported, not reconciled. The two need not agree: the filed credit is
a regulatory schedule, the modeled credit is what the engine's loss reductions imply.
"""

from statistics import NormalDist

import numpy as np

from app.actuarial import compound_model as cm
from app.actuarial.constants import get as c
from app.models.schemas import PremiumBuild

_GRID = 400
_Z_GRID = np.array([NormalDist().inv_cdf((i + 0.5) / _GRID) for i in range(_GRID)])


def retained_share(sp: cm.SevParams, d: float) -> tuple[float, float]:
    """(E[(S - d)+], E[S]) on a deterministic quantile grid of the same lognormal-body/GPD-tail severity
    the Monte Carlo draws from. d is a fraction of RCV and sits below the tail splice, so every tail loss
    exceeds it."""
    cv = c("mc.body_cv")
    sig = float(np.sqrt(np.log1p(cv * cv)))
    body = np.minimum(np.exp(np.log(max(sp.body_mean, 1e-9)) - sig * sig / 2 + sig * _Z_GRID), sp.body_cap)
    excess = (1 - sp.p_tail) * np.maximum(body - d, 0).mean() + sp.p_tail * max(sp.tail_mean - d, 0.0)
    mean = (1 - sp.p_tail) * body.mean() + sp.p_tail * sp.tail_mean
    return float(excess), float(mean)


def net_expected_loss(terms: list[cm.PerilTerm], *, scale: float, rcv_usd: float, deductible_pct: float) -> float:
    """Annual expected loss in dollars after the deductible, on the priced (posterior) basis."""
    total = 0.0
    for t in terms:
        if t.sev is None:
            continue
        excess, mean = retained_share(t.sev, deductible_pct)
        if mean > 0:
            total += t.n * t.s * scale * rcv_usd * excess / mean
    return total


def modeled_credit_pct(bare: list[cm.PerilTerm], current: list[cm.PerilTerm]) -> float:
    """Percent fall in non-flood expected loss, unmitigated to as-verified."""
    before = sum(t.n * t.s for t in bare if t.peril != "FLOOD")
    after = sum(t.n * t.s for t in current if t.peril != "FLOOD")
    return round(100 * (1 - after / before), 2) if before > 0 else 0.0


def premium_build(
    terms: list[cm.PerilTerm],
    *,
    bare_terms: list[cm.PerilTerm],
    expected_loss_usd: float,
    scale: float,
    rcv_usd: float,
    filed_credit_pct: float,
) -> PremiumBuild:
    expense, profit = c("premium.expense_load"), c("premium.profit_load")
    pct = c("premium.deductible_pct_rcv")
    net = net_expected_loss(terms, scale=scale, rcv_usd=rcv_usd, deductible_pct=pct)
    return PremiumBuild(
        expected_loss_usd=round(expected_loss_usd, 2),
        deductible_usd=round(pct * rcv_usd, 2),
        net_expected_loss_usd=round(net, 2),
        expense_load_pct=round(expense * 100, 2),
        profit_load_pct=round(profit * 100, 2),
        indicated_premium_usd=round((net + c("premium.fixed_expense_usd")) / (1 - expense - profit), 2),
        modeled_mitigation_credit_pct=modeled_credit_pct(bare_terms, terms),
        filed_mitigation_credit_pct=round(filed_credit_pct, 2),
    )
