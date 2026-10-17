"""Run the flood validation end to end and write the result files.

Usage (from backend/):
    uv run python -m validation.flood_report                      # committed sample, no network
    RS_LIVE=1 uv run python -m validation.flood_report --claims validation/data/claims_full.csv

Outputs (in --results, default validation/results/): flood_severity_buckets.csv, flood_holdout_buckets.csv,
flood_events.csv, flood_basement.csv, flood_summary.json. If the fitted curve beats Hazus on the holdout with a
bootstrap CI that excludes zero, the proposal is written to validation/fitted/flood_ddf.json.
"""

import argparse
import csv
import json
import math
import os
from datetime import date
from pathlib import Path

import numpy as np

from validation.flood_backtest import (
    BASEMENT_CODES,
    EVENTS,
    HOLDOUT_EVENT,
    HOLDOUT_STATES,
    Claims,
    bucket_table,
    cluster_bootstrap_ci,
    depth_quality,
    event_mask,
    fia_105,
    fit_isotonic,
    hazus_129,
    is_holdout,
    read_claims,
    summary,
)

HERE = Path(__file__).resolve().parent
SAMPLE = HERE / "data" / "claims_sample.csv"
KNOTS_FT = np.arange(0.0, 16.01, 0.5)
MIN_EVENT_TRACTS = 30
MIN_EVENT_N = 20  # an event row with fewer claims is listed but its metrics are not trusted
ADOPT_LEVEL = 0.95


def _curves(c: Claims, fitted=None) -> dict[str, np.ndarray]:
    out = {"hazus129": hazus_129(c.depth_ft), "fia105": fia_105(c.depth_ft)}
    if fitted is not None:
        out["fitted"] = fitted(c.depth_ft)
    return out


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def _cluster_key(c: Claims) -> np.ndarray:
    """Cluster id for the bootstrap: the named flood event, or state-year when none is named."""
    return np.array([e if e else f"{s}-{y}" for e, s, y in zip(c.event, c.state, c.year, strict=True)])


def split_and_fit(c0: Claims) -> dict:
    hold = is_holdout(c0)
    train, test = c0.take(~hold), c0.take(hold)
    fitted = fit_isotonic(train.depth_ft, train.ratio, KNOTS_FT)
    pred = _curves(test, fitted)
    haz_err = np.abs(pred["hazus129"] - test.ratio)
    fit_err = np.abs(pred["fitted"] - test.ratio)
    diff, lo, hi = cluster_bootstrap_ci(fit_err - haz_err, _cluster_key(test), level=ADOPT_LEVEL)
    return {
        "fitted": fitted, "train": train, "test": test, "holdout_buckets": bucket_table(test, pred),
        "holdout_summary": summary(test, pred),
        "mae_diff_fitted_minus_hazus": diff, "mae_diff_ci_lo": lo, "mae_diff_ci_hi": hi,
        "adopt": bool(len(test) > 0 and hi < 0),
    }


def leave_one_event_out(c0: Claims) -> list[dict]:
    rows = []
    for name, (states, first, last) in EVENTS.items():
        held_mask = event_mask(c0, states, first, last)
        held = c0.take(held_mask)
        row = {"event": name, "states": "/".join(states), "window": f"{first}..{last}", "n": len(held)}
        if len(held) == 0:
            rows.append(row)
            continue
        train = c0.take(~held_mask)
        fitted = fit_isotonic(train.depth_ft, train.ratio, KNOTS_FT)
        s = summary(held, _curves(held, fitted))
        row.update({k: s[k] for k in s if k != "n"})
        row["trusted"] = len(held) >= MIN_EVENT_N
        rows.append(row)
    return rows


def basement_split(c: Claims, curves=hazus_129) -> list[dict]:
    """Basement claims for Sandy and Ida-NYC, observed against the no-basement Hazus 129 curve (all the engine has)."""
    rows = []
    for name in ("Sandy 2012", "Ida 2021 (NY/NJ pluvial)"):
        states, first, last = EVENTS[name]
        in_event = event_mask(c, states, first, last)
        for label, mask in (("no basement", c.basement == 0), ("basement", np.isin(c.basement, BASEMENT_CODES))):
            sub = c.take(in_event & mask)
            if len(sub):
                s = summary(sub, {"hazus129": curves(sub.depth_ft)})
                rows.append({"event": name, "group": label, **s})
    return rows


def run_report(
    claims_path: Path, results: Path, fitted_dir: Path | None, *, source: str, fetched: str
) -> dict:
    allc = read_claims(claims_path)
    c0 = allc.take(allc.basement == 0)
    overall = summary(c0, _curves(c0))
    buckets = bucket_table(c0, _curves(c0))
    sp = split_and_fit(c0)
    events = leave_one_event_out(c0)
    basement = basement_split(allc)

    _write_csv(results / "flood_severity_buckets.csv", buckets)
    _write_csv(results / "flood_holdout_buckets.csv", sp["holdout_buckets"])
    _write_csv(results / "flood_events.csv", events)
    if basement:
        _write_csv(results / "flood_basement.csv", basement)

    holdout_mae_fit = sp["holdout_summary"]["fitted_mae"]
    holdout_mae_haz = sp["holdout_summary"]["hazus129_mae"]
    verdict = "adopt" if sp["adopt"] else "keep Hazus"
    result = {
        "source": source, "fetched": fetched, "claims_total": len(allc), "claims_no_basement": len(c0),
        "overall": overall,
        "depth_quality": depth_quality(c0),
        "split": {"holdout": f"states {list(HOLDOUT_STATES)} (any year) plus {HOLDOUT_EVENT} (any state)",
                  "train_n": len(sp["train"]), "holdout_n": len(sp["test"])},
        "holdout": sp["holdout_summary"],
        "mae_diff_fitted_minus_hazus": {
            "estimate": sp["mae_diff_fitted_minus_hazus"], "ci_lo": sp["mae_diff_ci_lo"],
            "ci_hi": sp["mae_diff_ci_hi"], "level": ADOPT_LEVEL, "method": "cluster bootstrap by event, 2000 resamples",
        },
        "verdict": verdict,
        "events": events,
    }
    (results / "flood_summary.json").parent.mkdir(parents=True, exist_ok=True)
    (results / "flood_summary.json").write_text(json.dumps(result, indent=2, default=_json_default) + "\n")
    if sp["adopt"] and fitted_dir is not None:
        fitted_dir.mkdir(parents=True, exist_ok=True)
        (fitted_dir / "flood_ddf.json").write_text(json.dumps({
            "knots": [float(k) for k in sp["fitted"].knots],
            "values": [round(float(v), 5) for v in sp["fitted"].values],
            "train_n": len(sp["train"]), "holdout_n": len(sp["test"]),
            "holdout_mae": holdout_mae_fit, "hazus_holdout_mae": holdout_mae_haz,
            "fit_date": fetched,
            "method": "Monotone (isotonic, PAVA) fit of damage ratio on depth above first floor, ft, "
                      "NFIP single-family one-floor no-basement claims; " + result["split"]["holdout"],
        }, indent=2) + "\n")
    elif fitted_dir is not None and (fitted_dir / "flood_ddf.json").exists():
        (fitted_dir / "flood_ddf.json").unlink()  # a stale proposal must not outlive a failed adopt rule
    return result


def _json_default(o):
    if isinstance(o, (np.floating, np.integer)):
        return None if isinstance(o, np.floating) and math.isnan(o) else o.item()
    if isinstance(o, float) and math.isnan(o):
        return None
    raise TypeError(type(o))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--claims", default=str(SAMPLE))
    parser.add_argument("--results", default=str(HERE / "results"))
    parser.add_argument("--fitted", default=str(HERE / "fitted"))
    args = parser.parse_args()
    full = Path(args.claims) != SAMPLE
    if full and os.environ.get("RS_LIVE") != "1":
        raise SystemExit("full runs need RS_LIVE=1")
    out = run_report(Path(args.claims), Path(args.results), Path(args.fitted),
                     source=str(args.claims), fetched=date.today().isoformat())
    print(json.dumps({k: out[k] for k in ("claims_total", "split", "mae_diff_fitted_minus_hazus", "verdict")},
                     indent=2, default=_json_default))


if __name__ == "__main__":
    main()
