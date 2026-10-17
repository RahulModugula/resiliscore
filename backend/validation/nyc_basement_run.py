"""Validate the NYC basement severity choice on NFIP basement claims, leave one event out.

Question: which curve should give building damage for a flooded basement? The candidates are Hazus 129 (the
engine's flood curve, applied to the recorded depth), a rescaled Hazus 129, the four Hazus basement structure
curves plus a finish term (the design in the first NYC draft), an isotonic fit, and a constant.

Split: train on one event, test on the other, both ways (Sandy to Ida NY/NJ, Ida NY/NJ to Sandy). Metric: damage
ratio = buildingDamageAmount / buildingPropertyValue, capped at 1, against the recorded water depth in feet.
Adopt rule: a candidate replaces Hazus 129 only if its paired squared-error difference to Hazus 129 has a 95%
interval wholly below zero in BOTH directions (resampling census tracts, the independence unit). Squared error is
the right criterion for an expected-loss model because it rewards the mean; absolute error is reported as well and
can disagree, because it rewards the median of a skewed ratio.

Run (from backend/):
    uv run python -m validation.nyc_basement_run                       # committed sample, no network
    uv run python -m validation.nyc_basement_run --claims validation/data/nyc_basement_full.csv
"""

import argparse
import csv
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from app.actuarial import constants
from app.actuarial.compound_model import ddf

HERE = Path(__file__).resolve().parent
SAMPLE = HERE / "data" / "nyc_basement_sample.csv"
RESULTS = HERE / "results"
EVENTS = ("Sandy 2012", "Ida 2021 NY/NJ")
BASEMENT_FT = 7.5  # the registry's full-basement depth, used only to place the structure curves
FIRST_FLOOR_FT = 1.0  # first floor above grade
FINISH_FULL_DEPTH_FT = 3.0  # depth at which the first draft's finish and contents loss was total
PRIOR_FINISH = 0.075  # first draft: full-basement finish share 0.15 times the unconverted multiplier 0.5
CURVES = {
    "FIA 121 one floor": "nyc.ddf.fia_1floor_basement_a",
    "FIA 122 two floors": "nyc.ddf.fia_2floor_basement_a",
    "FIA(MOD) 108 two floors": "nyc.ddf.fia_mod_2floor_basement_a",
    "USACE-Chicago 133": "nyc.ddf.usace_chicago_1story_basement",
}
BOOT = 2000
SEED = 20261017


@dataclass(frozen=True)
class Claims:
    event: np.ndarray
    depth_ft: np.ndarray
    ratio: np.ndarray
    tract: np.ndarray

    def mask(self, event: str) -> np.ndarray:
        return self.event == event


def load(path: Path = SAMPLE) -> Claims:
    with path.open(newline="") as fh:
        rows = list(csv.DictReader(fh))
    return Claims(
        event=np.array([r["event"] for r in rows]),
        depth_ft=np.array([float(r["waterDepth"]) / 12.0 for r in rows]),
        ratio=np.minimum(1.0, np.array([float(r["buildingDamageAmount"]) / float(r["buildingPropertyValue"]) for r in rows])),
        tract=np.array([(r["censusGeoid"] or "NA")[:11] for r in rows]),
    )


def hazus129(depth_ft: np.ndarray) -> np.ndarray:
    return np.array([ddf(d) for d in depth_ft])


def structure_plus_finish(curve: str, depth_ft: np.ndarray, finish: float) -> np.ndarray:
    lo, hi = constants.get("nyc.ddf.basement_depth_range_ft")
    table = np.array(constants.get(curve), dtype=float) / 100.0
    structure = np.interp(depth_ft - BASEMENT_FT - FIRST_FLOOR_FT, np.arange(lo, hi + 1), table)
    return structure + finish * np.minimum(1.0, depth_ft / FINISH_FULL_DEPTH_FT)


def isotonic(x: np.ndarray, y: np.ndarray):
    """Non-decreasing least-squares fit (pool adjacent violators); returns a function of depth."""
    ux, inv = np.unique(x, return_inverse=True)
    sums = np.bincount(inv, weights=y)
    counts = np.bincount(inv).astype(float)
    blocks: list[list[float]] = []
    for s, n in zip(sums, counts, strict=True):
        blocks.append([s / n, n, 1])
        while len(blocks) > 1 and blocks[-2][0] > blocks[-1][0]:
            b2, b1 = blocks.pop(), blocks.pop()
            total = b1[1] + b2[1]
            blocks.append([(b1[0] * b1[1] + b2[0] * b2[1]) / total, total, b1[2] + b2[2]])
    fitted = np.concatenate([[b[0]] * int(b[2]) for b in blocks])
    return lambda q: np.interp(q, ux, fitted)


def _grid_fit(make, grid: np.ndarray, mask: np.ndarray, claims: Claims, loss: str) -> float:
    def score(p: float) -> float:
        err = make(p)[mask] - claims.ratio[mask]
        return float(np.mean(np.abs(err)) if loss == "mae" else np.mean(err**2))

    return float(min(grid, key=score))


def fit_scale(claims: Claims, mask: np.ndarray, loss: str) -> float:
    """Scale k on Hazus 129 minimising absolute ('mae') or squared ('mse') error on the masked claims."""
    base = hazus129(claims.depth_ft)
    return _grid_fit(lambda p: np.minimum(1.0, p * base), np.arange(0.2, 3.0, 0.01), mask, claims, loss)


def predictions(claims: Claims, train: np.ndarray) -> tuple[dict[str, np.ndarray], dict[str, float]]:
    """Every candidate's prediction for every claim (parameters fitted on `train` only) and those parameters."""
    d, base = claims.depth_ft, hazus129(claims.depth_ft)
    out, params = {"Hazus 129": base}, {}
    for loss in ("mae", "mse"):
        k = fit_scale(claims, train, loss)
        out[f"Hazus 129 x k ({loss} fit)"] = np.minimum(1.0, k * base)
        params[f"Hazus 129 x k ({loss} fit)"] = k
    for name, curve in CURVES.items():
        out[f"{name} + first-draft finish"] = structure_plus_finish(curve, d, PRIOR_FINISH)
        g = _grid_fit(lambda p, c=curve: structure_plus_finish(c, d, p), np.arange(0.0, 0.6001, 0.005), train, claims, "mae")
        out[f"{name} + fitted finish"] = structure_plus_finish(curve, d, g)
        params[f"{name} + fitted finish"] = g
    out["Isotonic on depth"] = isotonic(d[train], claims.ratio[train])(d)
    out["Constant (train mean)"] = np.full_like(d, claims.ratio[train].mean())
    return out, params


def paired_interval(pred: np.ndarray, ref: np.ndarray, claims: Claims, test: np.ndarray, loss: str) -> tuple[float, float, float]:
    """Mean paired loss difference pred - ref on the test claims, with a 95% bootstrap interval over tracts."""
    err_a, err_b = pred - claims.ratio, ref - claims.ratio
    delta = np.abs(err_a) - np.abs(err_b) if loss == "mae" else err_a**2 - err_b**2
    idx = np.where(test)[0]
    tracts = claims.tract[idx]
    groups = {t: idx[tracts == t] for t in np.unique(tracts)}
    keys = list(groups)
    rng = np.random.default_rng(SEED)
    means = [
        delta[np.concatenate([groups[keys[i]] for i in rng.integers(0, len(keys), len(keys))])].mean() for _ in range(BOOT)
    ]
    return float(delta[idx].mean()), float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def run(claims: Claims) -> dict:
    directions = []
    for train_event, test_event in (EVENTS, EVENTS[::-1]):
        train, test = claims.mask(train_event), claims.mask(test_event)
        preds, params = predictions(claims, train)
        ref = preds["Hazus 129"]
        rows = []
        for name, pred in preds.items():
            row = {
                "candidate": name, "fitted_parameter": params.get(name), "mae": float(np.mean(np.abs(pred[test] - claims.ratio[test]))),
                "mse": float(np.mean((pred[test] - claims.ratio[test]) ** 2)),
                "bias": float(np.mean(pred[test] - claims.ratio[test])),
            }
            for loss in ("mae", "mse"):
                diff, lo, hi = paired_interval(pred, ref, claims, test, loss)
                row[f"{loss}_vs_hazus"] = {"diff": diff, "lo": lo, "hi": hi}
            rows.append(row)
        directions.append({
            "train": train_event, "test": test_event, "n_train": int(train.sum()), "n_test": int(test.sum()),
            "observed_mean": float(claims.ratio[test].mean()), "rows": rows,
        })
    verdicts = {}
    for entry in directions[0]["rows"]:
        name = entry["candidate"]
        by_loss = {}
        for loss in ("mae", "mse"):
            wins = [next(r for r in d["rows"] if r["candidate"] == name)[f"{loss}_vs_hazus"]["hi"] < 0 for d in directions]
            by_loss[loss] = "adopt" if all(wins) else "keep Hazus 129"
        verdicts[name] = by_loss
    everything = np.ones(len(claims.ratio), dtype=bool)
    return {
        "adopt_rule": "paired error vs Hazus 129 on the held-out event, 95% interval (tract bootstrap) wholly below zero "
                      "in both directions; mae is the rule of docs/validation/flood.md, mse is reported beside it",
        "directions": directions,
        "verdicts": verdicts,
        "pooled_k": {"mae": fit_scale(claims, everything, "mae"), "mse": fit_scale(claims, everything, "mse")},
    }


def write(result: dict, out: Path = RESULTS) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "nyc_basement.json").write_text(json.dumps(result, indent=1) + "\n")
    with (out / "nyc_basement.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["train", "test", "candidate", "mae", "mse", "bias", "mse_diff_vs_hazus", "mse_lo", "mse_hi",
                    "mae_diff_vs_hazus", "mae_lo", "mae_hi"])
        for d in result["directions"]:
            for r in d["rows"]:
                m, a = r["mse_vs_hazus"], r["mae_vs_hazus"]
                w.writerow([d["train"], d["test"], r["candidate"], f"{r['mae']:.5f}", f"{r['mse']:.5f}", f"{r['bias']:+.5f}",
                            f"{m['diff']:+.5f}", f"{m['lo']:+.5f}", f"{m['hi']:+.5f}", f"{a['diff']:+.5f}", f"{a['lo']:+.5f}", f"{a['hi']:+.5f}"])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--claims", default=str(SAMPLE))
    parser.add_argument("--out", default=str(RESULTS))
    args = parser.parse_args()
    claims = load(Path(args.claims))
    result = run(claims)
    write(result, Path(args.out))
    for d in result["directions"]:
        print(f"\ntrain {d['train']} (n={d['n_train']}) -> test {d['test']} (n={d['n_test']}), observed mean {d['observed_mean']:.3f}")
        for r in d["rows"]:
            m, a = r["mse_vs_hazus"], r["mae_vs_hazus"]
            print(f"  {r['candidate']:48s} MAE {r['mae']:.4f} MSE {r['mse']:.4f} bias {r['bias']:+.3f} | "
                  f"dMSE {m['diff']:+.4f} [{m['lo']:+.4f},{m['hi']:+.4f}] dMAE {a['diff']:+.4f} [{a['lo']:+.4f},{a['hi']:+.4f}]")
    print("\nverdicts (mae rule, mse rule):")
    for name, v in result["verdicts"].items():
        print(f"  {name:48s} {v['mae']:16s} {v['mse']}")
    print("pooled k:", result["pooled_k"])


if __name__ == "__main__":
    main()
