"""Run the flood validation end to end and write the result files.

Usage (from backend/):
    uv run python -m validation.flood_report                      # committed sample, no network
    RS_LIVE=1 uv run python -m validation.flood_report --claims validation/data/claims_full.csv

Outputs (in --results, default validation/results/):
  flood_summary.json          the fixed report contract (charts read this)
  flood_detail.json           everything else: split, holdout, bootstrap, data quality
  flood_severity_buckets.csv, flood_holdout_buckets.csv, flood_events.csv, flood_basement.csv
If the fitted curve beats Hazus on the holdout with a bootstrap CI that excludes zero, the proposal is also
written to validation/fitted/flood_ddf.json.
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
    DEPTH_BUCKETS_FT,
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
NRI_CACHE = HERE / "data" / "nri_flood_rates.csv"  # per-tract model flood rate and exposure; not committed
KNOTS_FT = np.arange(0.0, 16.01, 0.5)
MIN_EVENT_TRACTS = 30
MIN_EVENT_N = 20  # an event row with fewer claims is listed but its metrics are not trusted
ADOPT_LEVEL = 0.95
CI_REPS = 1000
SEED = 20261017

EVENT_YEAR = {"Katrina 2005": 2005, "Sandy 2012": 2012, "Harvey 2017": 2017, "Florence 2018": 2018,
              "Ida 2021 (LA surge)": 2021, "Ida 2021 (NY/NJ pluvial)": 2021, "Ian 2022": 2022, "Helene 2024": 2024}
EVENT_NOTE = {
    "Katrina 2005": "Surge and levee failure with long-lasting water; a likely reason a still-water curve is far "
                    "low (not tested).",
    "Sandy 2012": "Coastal surge; the basement claims are shown as a separate row.",
    "Harvey 2017": "Long-duration rain flooding; the largest event in the sample.",
    "Florence 2018": "Inland river flooding; Hazus is closest here.",
    "Ida 2021 (LA surge)": "Hurricane surge and rain in Louisiana.",
    "Ida 2021 (NY/NJ pluvial)": "Urban rain flooding; only about a hundred no-basement claims, so read as an indication.",
    "Ian 2022": "Surge and rain flooding in Florida.",
    "Helene 2024": "Fast river flooding in mountain terrain plus Florida surge; a likely reason Hazus is low (not tested).",
}


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


def load_nri_rates(path: Path) -> dict[str, tuple[float, float]] | None:
    """tract FIPS -> (model flood rate, exposed building value in $M), from the cache written by flood_ranking."""
    if not path.exists():
        return None
    with path.open() as fh:
        return {r["tract"]: (float(r["model_flood_lcr"]), float(r["exposed_building_value_musd"]))
                for r in csv.DictReader(fh)}


def tract_spearman(held: Claims, rates: dict[str, tuple[float, float]] | None) -> tuple[float | None, int | None]:
    """Spearman of the model's tract flood rate against claims per exposed $M, over tracts with a claim in the event."""
    if rates is None:
        return None, None
    from validation.flood_ranking import spearman  # imported here: it pulls in the live-data modules

    counts: dict[str, int] = {}
    for t in held.tract:
        if t in rates:
            counts[t] = counts.get(t, 0) + 1
    n = len(counts)
    if n < MIN_EVENT_TRACTS:
        return None, n
    pred = np.array([rates[t][0] for t in counts])
    incidence = np.array([counts[t] / rates[t][1] for t in counts])
    s = spearman(pred, incidence)
    return (None if math.isnan(s) else s), n


def leave_one_event_out(c0: Claims, rates=None) -> list[dict]:
    rows = []
    for name, (states, first, last) in EVENTS.items():
        held_mask = event_mask(c0, states, first, last)
        held = c0.take(held_mask)
        row = {"event": name, "year": EVENT_YEAR[name], "states": "/".join(states),
               "window": f"{first}..{last}", "n": len(held)}
        if len(held) == 0:
            rows.append(row)
            continue
        train = c0.take(~held_mask)
        fitted = fit_isotonic(train.depth_ft, train.ratio, KNOTS_FT)
        s = summary(held, _curves(held, fitted))
        row.update({k: s[k] for k in s if k != "n"})
        row["trusted"] = len(held) >= MIN_EVENT_N
        row["tract_spearman"], row["n_tracts"] = tract_spearman(held, rates)
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


def _bootstrap_mean_ci(x: np.ndarray, rng: np.random.Generator, level: float = 0.95) -> tuple[float, float]:
    if len(x) == 0:
        return math.nan, math.nan
    means = np.array([x[rng.integers(0, len(x), len(x))].mean() for _ in range(CI_REPS)])
    a = (1 - level) / 2
    return float(np.quantile(means, a)), float(np.quantile(means, 1 - a))


def _label(lo: float, hi: float) -> str:
    return f"{lo:g}+ ft" if hi > 20 else f"{lo:g}-{hi:g} ft"


def severity_by_depth(c0: Claims, fitted) -> list[dict]:
    """Contract rows: per depth bucket, observed mean with a bootstrap 95% CI, Hazus 129 and the fitted curve."""
    rng = np.random.default_rng(SEED)
    haz, fit = hazus_129(c0.depth_ft), fitted(c0.depth_ft)
    rows = []
    for lo, hi in DEPTH_BUCKETS_FT:
        m = (c0.depth_ft >= lo) & (c0.depth_ft < hi)
        if not m.any():
            continue
        ci_lo, ci_hi = _bootstrap_mean_ci(c0.ratio[m], rng)
        rows.append({
            "depth_bucket": _label(lo, hi), "depth_mid_ft": round((lo + min(hi, 12.0)) / 2, 3), "n": int(m.sum()),
            "observed_mean_dr": float(c0.ratio[m].mean()), "observed_ci_low": ci_lo, "observed_ci_high": ci_hi,
            "hazus_pred_dr": float(haz[m].mean()), "fitted_pred_dr": float(fit[m].mean()),
        })
    return rows


def contract_events(events: list[dict], basement: list[dict]) -> list[dict]:
    out = []
    for e in events:
        if e["n"] == 0:
            continue
        out.append({
            "event": e["event"], "year": e["year"], "states": e["states"].split("/"), "n_claims": e["n"],
            "observed_mean_dr": e["observed_mean"], "hazus_mae": e["hazus129_mae"], "fitted_mae": e["fitted_mae"],
            "bias": e["hazus129_bias"], "tract_spearman": e.get("tract_spearman"), "n_tracts": e.get("n_tracts"),
            "note": EVENT_NOTE[e["event"]],
        })
    for b in basement:
        if b["group"] != "basement":
            continue
        out.append({
            "event": f"{b['event']} (basement)", "year": EVENT_YEAR[b["event"]],
            "states": list(EVENTS[b["event"]][0]), "n_claims": b["n"],
            "observed_mean_dr": b["observed_mean"], "hazus_mae": b["hazus129_mae"], "fitted_mae": None,
            "bias": b["hazus129_bias"], "tract_spearman": None, "n_tracts": None,
            "note": "Basement claims against the no-basement Hazus 129 curve; the engine has no basement curve.",
        })
    return out


def contract_ranking(results: Path) -> dict | None:
    path = results / "flood_ranking_summary.json"
    if not path.exists():
        return None
    r = json.loads(path.read_text())
    return {"n_tracts": r["tracts"], "spearman": r["spearman"], "gini": r["gini"],
            "deciles": [{"decile": d["decile"], "expected": d["expected_claims"], "actual": float(d["claims"])}
                        for d in r["deciles"]]}


def run_report(
    claims_path: Path, results: Path, fitted_dir: Path | None, *, source: str, fetched: str,
    nri_cache: Path | None = None,
) -> dict:
    allc = read_claims(claims_path)
    c0 = allc.take(allc.basement == 0)
    overall = summary(c0, _curves(c0))
    buckets = bucket_table(c0, _curves(c0))
    sp = split_and_fit(c0)
    events = leave_one_event_out(c0, load_nri_rates(nri_cache) if nri_cache else None)
    basement = basement_split(allc)

    _write_csv(results / "flood_severity_buckets.csv", buckets)
    _write_csv(results / "flood_holdout_buckets.csv", sp["holdout_buckets"])
    _write_csv(results / "flood_events.csv", events)
    if basement:
        _write_csv(results / "flood_basement.csv", basement)

    holdout_mae_fit = sp["holdout_summary"]["fitted_mae"]
    holdout_mae_haz = sp["holdout_summary"]["hazus129_mae"]
    verdict = "adopt" if sp["adopt"] else "keep Hazus"
    split_text = f"states {list(HOLDOUT_STATES)} (any year) plus {HOLDOUT_EVENT} (any state)"
    detail = {
        "source": source, "fetched": fetched, "claims_total": len(allc), "claims_no_basement": len(c0),
        "overall": overall, "depth_quality": depth_quality(c0),
        "split": {"holdout": split_text, "train_n": len(sp["train"]), "holdout_n": len(sp["test"])},
        "holdout": sp["holdout_summary"],
        "mae_diff_fitted_minus_hazus": {
            "estimate": sp["mae_diff_fitted_minus_hazus"], "ci_lo": sp["mae_diff_ci_lo"],
            "ci_hi": sp["mae_diff_ci_hi"], "level": ADOPT_LEVEL,
            "method": "cluster bootstrap by event, 2000 resamples",
        },
        "verdict": verdict, "events": events,
    }
    ci = detail["mae_diff_fitted_minus_hazus"]
    contract = {
        "method": (
            "Observed damage ratio = buildingDamageAmount / buildingPropertyValue (actual cash value), capped at 1, "
            "for single-family one-floor no-basement NFIP claims; depth = waterDepth / 12 ft above the first floor "
            "(reference level unstated by OpenFEMA). Per-bucket CIs are percentile bootstraps over claims "
            f"({CI_REPS} resamples). Bias = Hazus 129 predicted minus observed. Fitted curve: isotonic fit "
            f"trained on everything outside the holdout ({split_text}); fitted_mae per event is leave-one-event-out. "
            "Tract Spearman: model tract flood rate against claims per exposed building $M, over tracts with a "
            f"claim in the event (needs at least {MIN_EVENT_TRACTS} tracts)."
        ),
        "data_source": "OpenFEMA NfipClaims v3 (https://www.fema.gov/api/open/v3/NfipClaims), FEMA NRI for tract rates",
        "data_vintage": "NfipClaims last refreshed 2026-09-09; losses 2005-2025",
        "fetched_on": fetched,
        "verdict": verdict,
        "severity_by_depth": severity_by_depth(c0, sp["fitted"]),
        "events": contract_events(events, basement),
        "ranking": contract_ranking(results),
        "adopted": sp["adopt"],
        "adoption_note": (
            f"Holdout MAE {holdout_mae_fit:.3f} (fitted) vs {holdout_mae_haz:.3f} (Hazus 129); 95% interval on the "
            f"difference {ci['ci_lo']:+.3f} to {ci['ci_hi']:+.3f} "
            + ("excludes zero." if sp["adopt"] else "includes zero, so Hazus 129 stays.")
        ),
    }
    results.mkdir(parents=True, exist_ok=True)
    (results / "flood_detail.json").write_text(json.dumps(detail, indent=2, default=_json_default) + "\n")
    (results / "flood_summary.json").write_text(json.dumps(contract, indent=2, default=_json_default) + "\n")
    if sp["adopt"] and fitted_dir is not None:
        fitted_dir.mkdir(parents=True, exist_ok=True)
        (fitted_dir / "flood_ddf.json").write_text(json.dumps({
            "knots": [float(k) for k in sp["fitted"].knots],
            "values": [round(float(v), 5) for v in sp["fitted"].values],
            "train_n": len(sp["train"]), "holdout_n": len(sp["test"]),
            "holdout_mae": holdout_mae_fit, "hazus_holdout_mae": holdout_mae_haz,
            "fit_date": fetched,
            "method": "Monotone (isotonic, PAVA) fit of damage ratio on depth above first floor, ft, "
                      "NFIP single-family one-floor no-basement claims; " + split_text,
        }, indent=2) + "\n")
    elif fitted_dir is not None and (fitted_dir / "flood_ddf.json").exists():
        (fitted_dir / "flood_ddf.json").unlink()  # a stale proposal must not outlive a failed adopt rule
    return {**detail, "contract": contract}


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
    parser.add_argument("--nri-cache", default=str(NRI_CACHE))
    args = parser.parse_args()
    if Path(args.claims) != SAMPLE and os.environ.get("RS_LIVE") != "1":
        raise SystemExit("full runs need RS_LIVE=1")
    out = run_report(Path(args.claims), Path(args.results), Path(args.fitted), source=str(args.claims),
                     fetched=date.today().isoformat(), nri_cache=Path(args.nri_cache))
    print(json.dumps({k: out[k] for k in ("claims_total", "split", "mae_diff_fitted_minus_hazus", "verdict")},
                     indent=2, default=_json_default))


if __name__ == "__main__":
    main()
