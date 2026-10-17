"""Flood severity backtest and empirical depth-damage fit against NFIP claims.

Observed damage ratio = buildingDamageAmount / buildingPropertyValue (both actual cash value), capped at 1.
Water depth is waterDepth (inches) / 12, taken as depth above the first floor. The OpenFEMA metadata does not
state the reference level, so that is an assumption; see docs/validation/flood.md.

The engine's curves are read only: Hazus DmgFnId 129 through `compound_model.ddf`, and the FIA A-zone curve
(DmgFnId 105) from the constants registry. Nothing under app/ is changed.
"""

import csv
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from app.actuarial import constants
from app.actuarial.compound_model import ddf

DEPTH_BUCKETS_FT = [(0, 0.5), (0.5, 1), (1, 2), (2, 3), (3, 4), (4, 6), (6, 8), (8, 20.01)]
HOLDOUT_STATES = ("NY", "NJ")
HOLDOUT_EVENT = "Hurricane Ida"
BASEMENT_CODES = (1, 2)


@dataclass
class Claims:
    """Columns of claims as numpy arrays."""

    depth_ft: np.ndarray
    ratio: np.ndarray
    state: np.ndarray
    event: np.ndarray
    year: np.ndarray
    date: np.ndarray  # ISO date strings, YYYY-MM-DD
    basement: np.ndarray
    tract: np.ndarray
    zone: np.ndarray

    def __len__(self) -> int:
        return len(self.ratio)

    def take(self, mask: np.ndarray) -> "Claims":
        return Claims(**{k: v[mask] for k, v in self.__dict__.items()})


def read_claims(path: Path) -> Claims:
    cols: dict[str, list] = {k: [] for k in Claims.__dataclass_fields__}
    with path.open(newline="") as fh:
        for r in csv.DictReader(fh):
            try:
                value = float(r["buildingPropertyValue"])
                depth_in = float(r["waterDepth"])
                damage = float(r["buildingDamageAmount"])
            except (TypeError, ValueError):
                continue
            if value <= 0:
                continue
            cols["depth_ft"].append(depth_in / 12.0)
            cols["ratio"].append(min(1.0, damage / value))
            cols["state"].append(r["state"])
            cols["event"].append(r["floodEvent"] or "")
            cols["year"].append(int(r["yearOfLoss"]))
            cols["date"].append((r["dateOfLoss"] or "")[:10])
            cols["basement"].append(int(float(r["basementEnclosureCrawlspaceType"] or 0)))
            cols["tract"].append((r["censusGeoid"] or "")[:11])
            cols["zone"].append(r["ratedFloodZone"] or "")
    return Claims(**{k: np.array(v) for k, v in cols.items()})


# ---- curves (read-only use of the engine) ----

def hazus_129(depth_ft: np.ndarray) -> np.ndarray:
    return np.array([ddf(float(d)) for d in depth_ft])


def fia_105(depth_ft: np.ndarray) -> np.ndarray:
    lo, hi = constants.get("flood.ddf.depth_clamp_ft")
    knots = np.arange(lo, hi + 1.0)
    values = np.array(constants.get("flood.ddf.fia_a_zone_low"), dtype=float) / 100.0
    return np.interp(depth_ft, knots, values)


# ---- metrics ----

def mae(obs: np.ndarray, pred: np.ndarray) -> float:
    return float(np.mean(np.abs(pred - obs))) if len(obs) else math.nan


def bias(obs: np.ndarray, pred: np.ndarray) -> float:
    """Mean predicted minus mean observed (positive = the curve over-predicts)."""
    return float(np.mean(pred - obs)) if len(obs) else math.nan


def bucket_table(c: Claims, curves: dict[str, np.ndarray]) -> list[dict]:
    rows = []
    for lo, hi in DEPTH_BUCKETS_FT:
        m = (c.depth_ft >= lo) & (c.depth_ft < hi)
        row = {"depth_lo_ft": lo, "depth_hi_ft": hi, "n": int(m.sum()),
               "observed_mean": float(c.ratio[m].mean()) if m.any() else math.nan}
        for name, pred in curves.items():
            row[f"{name}_mean"] = float(pred[m].mean()) if m.any() else math.nan
            row[f"{name}_mae"] = mae(c.ratio[m], pred[m])
            row[f"{name}_bias"] = bias(c.ratio[m], pred[m])
        rows.append(row)
    return rows


def summary(c: Claims, curves: dict[str, np.ndarray]) -> dict:
    out = {"n": len(c), "observed_mean": float(c.ratio.mean()) if len(c) else math.nan}
    for name, pred in curves.items():
        out[f"{name}_mean"] = float(pred.mean()) if len(c) else math.nan
        out[f"{name}_mae"] = mae(c.ratio, pred)
        out[f"{name}_bias"] = bias(c.ratio, pred)
    return out


def depth_quality(c: Claims) -> dict:
    """Signs that waterDepth is not a clean inches-above-first-floor measurement.

    OpenFEMA warns that some values were entered in feet. Entries in feet would pile up on small integers, and
    inches entered as whole feet would heap on multiples of 12; `heaping_ratio_12_in` is the count at exact
    multiples of 12 between 12 and 120 inches over the mean count at their neighbours (1 means no heaping).
    """
    inches = np.round(c.depth_ft * 12).astype(int)
    counts = np.bincount(inches[inches <= 130], minlength=131)
    at12 = [counts[m] for m in range(12, 121, 12)]
    near = [(counts[m - 1] + counts[m + 1]) / 2 for m in range(12, 121, 12)]
    return {
        "n": len(c),
        "share_zero_in": float((inches == 0).mean()),
        "share_le_5_in": float((inches <= 5).mean()),
        "share_ge_12_in": float((inches >= 12).mean()),
        "heaping_ratio_12_in": float(sum(at12) / max(1.0, sum(near))),
    }


# ---- split ----

def is_holdout(c: Claims) -> np.ndarray:
    """Holdout = New York and New Jersey (any year) plus Hurricane Ida (any state). Train = everything else."""
    return np.isin(c.state, HOLDOUT_STATES) | (c.event == HOLDOUT_EVENT)


# ---- isotonic fit ----

def pava(y: np.ndarray, w: np.ndarray) -> np.ndarray:
    """Weighted pool-adjacent-violators: the non-decreasing least-squares fit to y."""
    vals: list[float] = []
    wts: list[float] = []
    sizes: list[int] = []
    for yi, wi in zip(y, w, strict=True):
        vals.append(float(yi))
        wts.append(float(wi))
        sizes.append(1)
        while len(vals) > 1 and vals[-2] > vals[-1]:
            tw = wts[-2] + wts[-1]
            vals[-2] = (vals[-2] * wts[-2] + vals[-1] * wts[-1]) / tw
            wts[-2] = tw
            sizes[-2] += sizes[-1]
            vals.pop(), wts.pop(), sizes.pop()
    return np.repeat(vals, sizes)


@dataclass(frozen=True)
class FittedCurve:
    knots: np.ndarray  # depth in ft
    values: np.ndarray  # damage ratio, non-decreasing

    def __call__(self, depth_ft: np.ndarray) -> np.ndarray:
        return np.interp(depth_ft, self.knots, self.values)


def fit_isotonic(depth_ft: np.ndarray, ratio: np.ndarray, knots: np.ndarray) -> FittedCurve:
    """Monotone non-decreasing fit of damage ratio on depth, evaluated at `knots`.

    The data are first pooled by integer inch of depth (the resolution of waterDepth), then PAVA is run on
    the pooled means weighted by claim counts, and the result is read off at `knots` (flat beyond the data).
    """
    inches = np.round(depth_ft * 12).astype(int)
    uniq = np.unique(inches)
    means = np.array([ratio[inches == u].mean() for u in uniq])
    counts = np.array([(inches == u).sum() for u in uniq], dtype=float)
    fit = pava(means, counts)
    return FittedCurve(knots, np.interp(knots, uniq / 12.0, fit))


# ---- bootstrap ----

def cluster_bootstrap_ci(
    diffs: np.ndarray, clusters: np.ndarray, *, reps: int = 2000, seed: int = 20261017, level: float = 0.95
) -> tuple[float, float, float]:
    """Mean of paired per-claim differences with a percentile CI from resampling whole clusters (events)."""
    rng = np.random.default_rng(seed)
    ids = np.unique(clusters)
    sums = np.array([diffs[clusters == i].sum() for i in ids])
    ns = np.array([(clusters == i).sum() for i in ids], dtype=float)
    means = np.empty(reps)
    for r in range(reps):
        pick = rng.integers(0, len(ids), len(ids))
        means[r] = sums[pick].sum() / ns[pick].sum()
    a = (1 - level) / 2
    return float(diffs.mean()), float(np.quantile(means, a)), float(np.quantile(means, 1 - a))


# ---- leave-one-event-out ----

EVENTS = {
    # name: (states, first date, last date). Dates are the NFIP dateOfLoss window around the event.
    "Katrina 2005": (("LA", "MS"), "2005-08-23", "2005-09-05"),
    "Sandy 2012": (("NY", "NJ"), "2012-10-27", "2012-11-05"),
    "Harvey 2017": (("TX",), "2017-08-23", "2017-09-05"),
    "Florence 2018": (("NC", "SC"), "2018-09-12", "2018-09-24"),
    "Ida 2021 (LA surge)": (("LA",), "2021-08-28", "2021-09-04"),
    "Ida 2021 (NY/NJ pluvial)": (("NY", "NJ"), "2021-09-01", "2021-09-04"),
    "Ian 2022": (("FL",), "2022-09-27", "2022-10-03"),
    "Helene 2024": (("NC", "FL"), "2024-09-24", "2024-09-30"),
}


def event_mask(c: Claims, states: tuple[str, ...], first: str, last: str) -> np.ndarray:
    return np.isin(c.state, states) & (c.date >= first) & (c.date <= last)
