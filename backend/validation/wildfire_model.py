"""Wildfire validation maths: DINS feature coding, the engine's relativities (read-only), logistic fit and metrics.

Pure numpy; scipy and statsmodels are not project dependencies.
"""

import csv
import math
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from app.actuarial import compound_model as engine

DATA = Path(__file__).parent / "data" / "wildfire_dins_sample.csv"
POPULATION = Path(__file__).parent / "data" / "wildfire_population.json"
Z95 = 1.959964

# DINS value -> 1 (favourable) / 0 (unfavourable); anything else is unknown (None). Inspectors record these after
# the fire, so "Unknown" is common for destroyed structures; it is kept as its own state, never dropped.
ROOF = {"Asphalt": 1, "Metal": 1, "Tile": 1, "Concrete": 1, "Fire Resistant": 1, "Wood": 0, "Combustible": 0}
EAVES = {"Enclosed": 1, "Unenclosed": 0}
VENTS = {'Mesh Screen <= 1/8"': 1, 'Mesh Screen > 1/8"': 0, "Unscreened": 0}
SIDING = {
    "Stucco Brick Cement": 1, "Stucco/Brick/Cement": 1, "Metal": 1, "Fire Resistant": 1, "Ignition Resistant": 1,
    "Wood": 0, "Combustible": 0, "Vinyl": 0,
}  # fmt: skip
WINDOWS = {"Multi Pane": 1, "Single Pane": 0}
SHED = {"<30'": 0, "30-50'": 1, ">50'": 1, "NA": 1, "N/A": 1}  # utility/misc structure within 30 ft
WOOD_DECK = {"Wood"}
NO_WOOD_DECK_OK = {"No Deck/Porch", "Masonry/Concrete", "Composite"}

BINARY = ("roof_class_a", "enclosed_eaves", "screened_vents", "noncombustible_siding", "multipane_windows",
          "no_wood_deck", "no_shed_within_30ft")  # fmt: skip
# DINS feature -> engine mitigation it stands for (only these have a current relativity).
ENGINE_MAP = {"roof_class_a": "roof_class_a", "enclosed_eaves": "enclosed_eaves", "screened_vents": "ember_vents",
              "no_shed_within_30ft": "zone1_no_shed"}  # fmt: skip
COUNT_FEATURES = ("roof_class_a", "enclosed_eaves", "screened_vents", "noncombustible_siding", "multipane_windows")
ERAS = ("pre1980", "1980_2007", "2008_plus")  # 2008: California Chapter 7A WUI building code


@dataclass(frozen=True)
class Home:
    fire: str
    destroyed: bool
    flags: dict[str, int | None]
    era: str | None


def _era(year_built: str) -> str | None:
    try:
        year = int(float(year_built))
    except ValueError:
        return None
    if year < 1850 or year > 2025:
        return None
    return ERAS[0] if year < 1980 else ERAS[1] if year < 2008 else ERAS[2]


def _deck(on_grade: str, elevated: str) -> int | None:
    values = {on_grade.strip(), elevated.strip()} - {""}
    if not values or "Unknown" in values:
        return None
    return 0 if values & WOOD_DECK else 1 if values <= NO_WOOD_DECK_OK else None


def load_homes(path: Path = DATA) -> list[Home]:
    """Sample rows as Homes. Rows with a blank roof field were never assessed (all undamaged) and are dropped."""
    homes = []
    with path.open() as fh:
        for r in csv.DictReader(fh):
            if not r["ROOFCONSTRUCTION"].strip():
                continue
            flags = {
                "roof_class_a": ROOF.get(r["ROOFCONSTRUCTION"]),
                "enclosed_eaves": EAVES.get(r["EAVES"]),
                "screened_vents": VENTS.get(r["VENTSCREEN"]),
                "noncombustible_siding": SIDING.get(r["EXTERIORSIDING"]),
                "multipane_windows": WINDOWS.get(r["WINDOWPANE"]),
                "no_wood_deck": _deck(r["DECKPORCHONGRADE"], r["DECKPORCHELEVATED"]),
                "no_shed_within_30ft": SHED.get(r["UTILITYMISCSTRUCTUREDISTANCE"]),
            }
            homes.append(Home(r["INCIDENTNAME"], r["DAMAGE"].startswith("Destroyed"), flags, _era(r["YEARBUILT"])))
    return homes


# --- the current model's relativities, read from the engine's constants --------------------------------------


def engine_relativity(doses: dict[str, float]) -> tuple[float, float]:
    """(destroyed-probability, expected-loss) relativity vs no mitigation, hazard held constant.

    Destroyed = a loss event (1 - immunity pi) that lands in the catastrophic tail, P = Phi(a0 - sum alpha*m).
    Expected loss = (1 - pi) * severity. Both come from the engine's own functions and EFFECTS table.
    """

    def raw(m: engine.Mitigations) -> tuple[float, float]:
        pi = engine._sigmoid(engine.ETA0 + engine._sum("WILDFIRE", m, "eta"))
        severity = engine.sev_params("WILDFIRE", engine.BODY_WILDFIRE, m)
        return (1 - pi) * severity.p_tail, (1 - pi) * severity.mean

    base, loss0 = raw(engine.Mitigations())
    destroyed, loss = raw(engine.Mitigations(**doses))
    return destroyed / base, loss / loss0


def engine_scores(homes: list[Home]) -> tuple[np.ndarray, np.ndarray]:
    """Per-home engine relativities (destroyed, loss). Unknown features earn no credit, as in production."""
    cache: dict[tuple, tuple[float, float]] = {}
    out = []
    for h in homes:
        doses = {engine_name: float(h.flags[f] == 1) for f, engine_name in ENGINE_MAP.items()}
        key = tuple(sorted(doses.items()))
        cache.setdefault(key, engine_relativity(doses))
        out.append(cache[key])
    arr = np.array(out)
    return arr[:, 0], arr[:, 1]


# --- logistic regression ---------------------------------------------------------------------------------------


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(x, -30, 30)))


@dataclass(frozen=True)
class Logit:
    beta: np.ndarray
    cov: np.ndarray

    @property
    def se(self) -> np.ndarray:
        return np.sqrt(np.diag(self.cov))


def fit_logit(x: np.ndarray, y: np.ndarray, ridge: float = 1e-6, iters: int = 60) -> Logit:
    """Newton-Raphson maximum likelihood with a vanishing ridge for numerical stability."""
    beta = np.zeros(x.shape[1])
    for _ in range(iters):
        p = _sigmoid(x @ beta)
        hess = x.T @ (x * (p * (1 - p))[:, None]) + ridge * np.eye(x.shape[1])
        step = np.linalg.solve(hess, x.T @ (y - p) - ridge * beta)
        beta += step
        if np.max(np.abs(step)) < 1e-9:
            break
    p = _sigmoid(x @ beta)
    hess = x.T @ (x * (p * (1 - p))[:, None]) + ridge * np.eye(x.shape[1])
    return Logit(beta, np.linalg.inv(hess))


def feature_columns() -> list[str]:
    cols = []
    for f in BINARY:
        cols += [f"{f}", f"{f}__unknown"]
    return cols + ["era_1980_2007", "era_2008_plus", "era__unknown"]


def design(homes: list[Home], fires: list[str] | None) -> np.ndarray:
    """Feature columns (favourable and unknown dummies; reference = known unfavourable), then fire dummies."""
    rows = []
    for h in homes:
        row = []
        for f in BINARY:
            row += [float(h.flags[f] == 1), float(h.flags[f] is None)]
        row += [float(h.era == ERAS[1]), float(h.era == ERAS[2]), float(h.era is None)]
        if fires is not None:
            row += [float(h.fire == name) for name in fires]
        rows.append(row)
    return np.array(rows)


# --- metrics ------------------------------------------------------------------------------------------------------


def auc(score: np.ndarray, y: np.ndarray) -> float:
    """Mann-Whitney AUC with average ranks for ties."""
    order = np.argsort(score, kind="mergesort")
    sorted_scores = score[order]
    ranks = np.empty(len(score))
    i = 0
    while i < len(score):
        j = i
        while j + 1 < len(score) and sorted_scores[j + 1] == sorted_scores[i]:
            j += 1
        ranks[order[i : j + 1]] = (i + j) / 2 + 1
        i = j + 1
    pos = y == 1
    n1, n0 = int(pos.sum()), int((~pos).sum())
    return float((ranks[pos].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def auc_ci(a: float, y: np.ndarray) -> tuple[float, float]:
    """Hanley-McNeil 95% interval."""
    n1, n0 = int(y.sum()), int(len(y) - y.sum())
    q1, q2 = a / (2 - a), 2 * a * a / (1 + a)
    var = (a * (1 - a) + (n1 - 1) * (q1 - a * a) + (n0 - 1) * (q2 - a * a)) / (n1 * n0)
    half = Z95 * math.sqrt(max(var, 0.0))
    return max(0.0, a - half), min(1.0, a + half)


def calibration_slope(lp: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    """Slope (and its SE) of y on the linear predictor with a free intercept; 1 = spread is right."""
    fit = fit_logit(np.column_stack([np.ones(len(lp)), lp]), y)
    return float(fit.beta[1]), float(fit.se[1])


def log_loss(p: np.ndarray, y: np.ndarray) -> float:
    p = np.clip(p, 1e-9, 1 - 1e-9)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def recentre(lp: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Shift the linear predictor so mean predicted probability equals the observed share (intercept only)."""
    lo, hi = -20.0, 20.0
    for _ in range(80):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if _sigmoid(lp + mid).mean() < y.mean() else (lo, mid)
    return lp + (lo + hi) / 2


def decile_table(p: np.ndarray, y: np.ndarray, bins: int = 10) -> list[dict]:
    order = np.argsort(p, kind="mergesort")
    out = []
    for i, idx in enumerate(np.array_split(order, bins), start=1):
        out.append({"decile": i, "n": len(idx), "mean_predicted": float(p[idx].mean()), "observed": float(y[idx].mean())})
    return out


def wilson(k: int, n: int) -> tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    p = k / n
    d = 1 + Z95**2 / n
    centre = (p + Z95**2 / (2 * n)) / d
    half = Z95 * math.sqrt(p * (1 - p) / n + Z95**2 / (4 * n * n)) / d
    return centre - half, centre + half


def mh_risk_ratio(homes: list[Home], feature: str) -> dict:
    """Fire-stratified Mantel-Haenszel risk ratio of destroyed, favourable vs unfavourable, known values only."""
    strata: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0, 0])  # a, n1, c, n0
    for h in homes:
        v = h.flags[feature]
        if v is None:
            continue
        s = strata[h.fire]
        if v == 1:
            s[0] += h.destroyed
            s[1] += 1
        else:
            s[2] += h.destroyed
            s[3] += 1
    num = den = var_num = 0.0
    for a, n1, c, n0 in strata.values():
        n = n1 + n0
        if n1 == 0 or n0 == 0:
            continue
        num += a * n0 / n
        den += c * n1 / n
        var_num += (n1 * n0 * (a + c) - a * c * n) / (n * n)
    if num == 0 or den == 0:
        return {"rr": float("nan"), "ci_low": float("nan"), "ci_high": float("nan"), "n": 0}
    rr = num / den
    se = math.sqrt(max(var_num, 0.0) / (num * den))
    n_known = sum(s[1] + s[3] for s in strata.values())
    return {"rr": rr, "ci_low": rr * math.exp(-Z95 * se), "ci_high": rr * math.exp(Z95 * se), "n": n_known}
