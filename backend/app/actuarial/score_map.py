"""LCR -> SaveMyHome (300-850) map. Decision D1 (docs/DECISIONS.md) overrides spec section 3.3.

The spec sigmoid misses its own golden scenarios by up to 44 points, so the production map is a strictly
decreasing piecewise-linear curve in ln(LCR), anchored at the golden reference parcels. Strict
monotonicity keeps the section 3.4 proof valid: d(score)/d(LCR) < 0 everywhere between the end knots.
"""

import math

import numpy as np

SCORE_MIN, SCORE_MAX = 300, 850
TIER_1_MIN, TIER_2_MIN = 720, 580

# (LCR in bps, score). The four D1 anchors plus the two golden baseline_macro_score points
# (160 bps -> 465, 210 bps -> 405) and the end pins (1 bp -> 850, 1000 bps -> 300).
_KNOTS_BPS_SCORE: tuple[tuple[float, float], ...] = (
    (1.0, 850.0),
    (18.0, 815.0),
    (24.0, 765.0),
    (160.0, 465.0),
    (185.0, 430.0),
    (210.0, 405.0),
    (245.0, 385.0),
    (1000.0, 300.0),
)
_LN_LCR = np.log(np.array([b / 1e4 for b, _ in _KNOTS_BPS_SCORE]))
_SCORES = np.array([s for _, s in _KNOTS_BPS_SCORE])


def score_continuous(lcr: float) -> float:
    """Unrounded score; flat beyond the 1 bp / 1000 bps pins. Used for derivatives."""
    if lcr <= 0:
        return float(SCORE_MAX)
    return float(np.interp(math.log(lcr), _LN_LCR, _SCORES))


def score_continuous_array(lcr: np.ndarray) -> np.ndarray:
    """Vectorised score_continuous for Monte Carlo draws."""
    safe = np.maximum(lcr, 1e-12)
    return np.where(lcr <= 0, float(SCORE_MAX), np.interp(np.log(safe), _LN_LCR, _SCORES))


def score(lcr: float) -> int:
    return min(SCORE_MAX, max(SCORE_MIN, round(score_continuous(lcr))))


def tier(resili_score: int) -> str:
    """Spec 3.3 bands: 720-850 / 580-719 / 300-579."""
    if resili_score >= TIER_1_MIN:
        return "TIER_1_AUTO_BIND"
    if resili_score >= TIER_2_MIN:
        return "TIER_2_CONDITIONAL"
    return "TIER_3_DECLINE_ESCALATE"


def spec_sigmoid(lcr: float) -> int:
    """Spec section 3.3 / Prompt 1C: 300 + round(550 / (1 + (LCR/0.0085)^1.15)).

    Reference only. It does not reproduce the golden scenarios (see D1), so nothing calls it.
    """
    return SCORE_MIN + round(550 / (1 + (lcr / 0.0085) ** 1.15))
