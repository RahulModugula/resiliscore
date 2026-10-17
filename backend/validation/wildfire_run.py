"""Wildfire validation: relativity ratios, leave-one-fire-out discrimination and the fitted proposal.

    cd backend && uv run python -m validation.wildfire_run

Reads only the committed sample, so it needs no network. Writes results/ and fitted/ next to this file.
"""

import csv
import json
import math
from pathlib import Path

import numpy as np

from validation import wildfire_model as wm

HERE = Path(__file__).parent
RESULTS = HERE / "results"
FITTED = HERE / "fitted"
FIT_DATE = "2026-10-17"
HOLDOUT_FIRE = "Palisades"  # the stated Phase 2 split: fit on every other fire, hold out Palisades 2025
EXAMPLE_TRAIN = ("Eaton", "Camp")  # the narrower split from the brief: Eaton 2025 + Camp 2018 -> Palisades 2025
URBAN_CONFLAGRATION = ("Eaton", "Palisades")
MIN_BUCKET = 30
MIN_CLASS = 20  # fewest destroyed (or surviving) homes for which an AUC is reported
OBSERVABLE = ("roof_class_a", "enclosed_eaves", "screened_vents")
METHOD = (
    "Logistic regression of destroyed on DINS-coded hardening features, year-built era and fire fixed effects "
    "(Newton-Raphson, numpy), fitted on every fire except the holdout. Unknown values are kept as their own level."
)


def _y(homes: list[wm.Home]) -> np.ndarray:
    return np.array([float(h.destroyed) for h in homes])


def _by_fire(homes: list[wm.Home]) -> dict[str, list[wm.Home]]:
    out: dict[str, list[wm.Home]] = {}
    for h in homes:
        out.setdefault(h.fire, []).append(h)
    return out


def _fit(train: list[wm.Home]) -> tuple[wm.Logit, list[str]]:
    fires = sorted({h.fire for h in train})
    return wm.fit_logit(wm.design(train, fires), _y(train)), fires


def _fitted_lp(model: wm.Logit, homes: list[wm.Home]) -> np.ndarray:
    """Linear predictor with every unknown level scored zero: at underwriting an unknown earns no credit.

    The fit keeps the unknown levels as nuisance terms, because DINS records Unknown mostly on destroyed homes
    (nothing left to inspect); scoring them would predict "destroyed" from the missingness itself.
    """
    cols = wm.feature_columns()
    beta = np.array([0.0 if "unknown" in c else b for c, b in zip(cols, model.beta[: len(cols)])])
    return wm.design(homes, None) @ beta


def is_complete(h: wm.Home) -> bool:
    """Roof, eaves and vent screen all recorded: the three engine features DINS can observe."""
    return all(h.flags[f] is not None for f in OBSERVABLE)


def _current_calibration(train: list[wm.Home]) -> float:
    """Slope b of logit(destroyed) on log(engine destroyed relativity) with fire fixed effects, on training fires."""
    fires = sorted({h.fire for h in train})
    log_rel = np.log(wm.engine_scores(train)[0])
    fe = np.array([[float(h.fire == f) for f in fires] for h in train])
    return float(wm.fit_logit(np.column_stack([log_rel, fe]), _y(train)).beta[0])


def holdout_metrics(train: list[wm.Home], test: list[wm.Home]) -> dict:
    """Current (IBHS-derived) vs fitted on one holdout, on complete-case homes (headline) and on all homes.

    Intercepts are re-centred to the holdout base rate, so log-loss and AUC measure ranking and spread only.
    """
    model, _ = _fit(train)
    b = _current_calibration(train)
    lp_fit = _fitted_lp(model, test)
    destroyed_rel, loss_rel = wm.engine_scores(test)
    mask = np.array([is_complete(h) for h in test])
    all_homes = _metrics(lp_fit, b * np.log(destroyed_rel), destroyed_rel, loss_rel, _y(test))
    complete = _metrics(lp_fit[mask], b * np.log(destroyed_rel[mask]), destroyed_rel[mask], loss_rel[mask], _y(test)[mask])
    return {**complete, **{f"all_{k}": v for k, v in all_homes.items() if k.startswith("auc_")}, "n_all": len(test)}


def _metrics(lp_fit: np.ndarray, lp_cur: np.ndarray, destroyed_rel: np.ndarray, loss_rel: np.ndarray, y: np.ndarray) -> dict:
    nan = float("nan")
    if min(y.sum(), len(y) - y.sum()) < MIN_CLASS:  # one class too thin for a stable AUC
        return {"n": len(y), "destroyed_share": float(y.mean()) if len(y) else nan, "auc_current": nan, "auc_fitted": nan,
                "auc_current_ci": (nan, nan), "auc_fitted_ci": (nan, nan), "auc_current_loss_rel": nan,
                "log_loss_current": nan, "log_loss_fitted": nan, "cal_slope_current": nan, "cal_slope_fitted": nan,
                "p_fitted": np.array([]), "p_current": np.array([]), "y": np.array([])}  # fmt: skip
    a_fit, a_cur, a_loss = wm.auc(lp_fit, y), wm.auc(lp_cur, y), wm.auc(loss_rel, y)
    slope_fit, se_fit = wm.calibration_slope(lp_fit, y)
    slope_cur, se_cur = wm.calibration_slope(np.log(destroyed_rel), y)
    return {
        "n": len(y), "destroyed_share": float(y.mean()),
        "auc_current": a_cur, "auc_current_ci": wm.auc_ci(a_cur, y), "auc_current_loss_rel": a_loss,
        "auc_fitted": a_fit, "auc_fitted_ci": wm.auc_ci(a_fit, y),
        "log_loss_current": wm.log_loss(wm._sigmoid(wm.recentre(lp_cur, y)), y),
        "log_loss_fitted": wm.log_loss(wm._sigmoid(wm.recentre(lp_fit, y)), y),
        "cal_slope_current": slope_cur, "cal_slope_current_se": se_cur,
        "cal_slope_fitted": slope_fit, "cal_slope_fitted_se": se_fit,
        "p_fitted": wm._sigmoid(wm.recentre(lp_fit, y)), "p_current": wm._sigmoid(wm.recentre(lp_cur, y)), "y": y,
    }  # fmt: skip


def leave_one_fire_out(homes: list[wm.Home], population: dict) -> list[dict]:
    rows = []
    for fire, test in sorted(_by_fire(homes).items(), key=lambda kv: -population[kv[0]]["inspected"]):
        train = [h for h in homes if h.fire != fire]
        m = holdout_metrics(train, test)
        rows.append({"fire": fire, "start_year": population[fire]["start_year"],
                     "n_inspected": population[fire]["inspected"], "n_sample": m["n_all"], "n_complete": m["n"],
                     "destroyed_share_population": population[fire]["destroyed"] / population[fire]["single_residences"],
                     **m})  # fmt: skip
    return rows


def feature_table(homes: list[wm.Home]) -> list[dict]:
    """Fire-stratified observed RR vs the engine's modelled RR, plus the pooled fire-adjusted fitted OR."""
    model, _ = _fit(homes)
    cols = wm.feature_columns()
    out = []
    for f in wm.BINARY:
        obs = wm.mh_risk_ratio(homes, f)
        i = cols.index(f)
        z = wm.Z95
        row = {
            "feature": f, "n_known": obs["n"], "share_unknown": sum(h.flags[f] is None for h in homes) / len(homes),
            "observed_rr": obs["rr"], "observed_rr_ci_low": obs["ci_low"], "observed_rr_ci_high": obs["ci_high"],
            "fitted_or": math.exp(model.beta[i]),
            "fitted_or_ci_low": math.exp(model.beta[i] - z * model.se[i]),
            "fitted_or_ci_high": math.exp(model.beta[i] + z * model.se[i]),
            "or_unknown_vs_unfavourable": math.exp(model.beta[i + 1]),
            "modelled_rr_destroyed": None, "modelled_rr_loss": None, "observed_over_modelled": None,
        }  # fmt: skip
        if f in wm.ENGINE_MAP:
            d, loss = wm.engine_relativity({wm.ENGINE_MAP[f]: 1.0})
            row.update(modelled_rr_destroyed=d, modelled_rr_loss=loss, observed_over_modelled=obs["rr"] / d,
                       observed_over_modelled_ci_low=obs["ci_low"] / d, observed_over_modelled_ci_high=obs["ci_high"] / d)  # fmt: skip
        out.append(row)
    for j, name in enumerate(("era_1980_2007", "era_2008_plus")):
        i = cols.index(name)
        out.append({"feature": name, "fitted_or": math.exp(model.beta[i]),
                    "fitted_or_ci_low": math.exp(model.beta[i] - wm.Z95 * model.se[i]),
                    "fitted_or_ci_high": math.exp(model.beta[i] + wm.Z95 * model.se[i])})  # fmt: skip
    return out


def count_table(homes: list[wm.Home]) -> list[dict]:
    """Destroyed share by number of favourable hardening features, on homes with all five features known."""
    known = [h for h in homes if all(h.flags[f] is not None for f in wm.COUNT_FEATURES)]
    counts = [min(4, sum(h.flags[f] == 1 for f in wm.COUNT_FEATURES)) for h in known]
    destroyed_rel = wm.engine_scores(known)[0]
    out = []
    for c in range(5):
        idx = [i for i, k in enumerate(counts) if k == c]
        k = sum(known[i].destroyed for i in idx)
        lo, hi = wm.wilson(k, len(idx))
        out.append({"count": "4+" if c == 4 else str(c), "n": len(idx), "destroyed_share": k / len(idx) if idx else None,
                    "ci_low": lo, "ci_high": hi,
                    "mean_engine_relativity": float(np.mean(destroyed_rel[idx])) if idx else None})  # fmt: skip
    if out[0]["n"] >= MIN_BUCKET:
        for row in out:
            if row["n"]:
                row["observed_vs_count0"] = row["destroyed_share"] / out[0]["destroyed_share"]
                row["modelled_vs_count0"] = row["mean_engine_relativity"] / out[0]["mean_engine_relativity"]
    return out


def proposal(homes: list[wm.Home], holdout: dict) -> dict:
    """Fitted relativities, only where the holdout beats the current model and the coefficient CI excludes 0.

    Every coded level is the favourable one, so a CI wholly above 0 (an OR above 1: "hardening makes destruction
    likelier") contradicts the physics and is reported as a data artifact in the write-up, never proposed.
    """
    train = [h for h in homes if h.fire != HOLDOUT_FIRE]
    model, fires = _fit(train)
    cols = wm.feature_columns()
    beats = holdout["auc_fitted"] > holdout["auc_current"] or holdout["log_loss_fitted"] < holdout["log_loss_current"]
    out: dict = {}
    if beats:
        for f in (*wm.BINARY, "era_1980_2007", "era_2008_plus"):
            i = cols.index(f)
            lo, hi = model.beta[i] - wm.Z95 * model.se[i], model.beta[i] + wm.Z95 * model.se[i]
            if hi < 0:
                out[f] = {"odds_ratio": math.exp(model.beta[i]), "ci_low": math.exp(lo), "ci_high": math.exp(hi)}
    return {**out, "train_fires": fires, "holdout_fire": HOLDOUT_FIRE, "holdout_auc": holdout["auc_fitted"],
            "current_holdout_auc": holdout["auc_current"], "fit_date": FIT_DATE, "method": METHOD}  # fmt: skip


def pooled_deciles(lofo: list[dict]) -> dict[str, list[dict]]:
    y = np.concatenate([r["y"] for r in lofo])
    return {
        "fitted": wm.decile_table(np.concatenate([r["p_fitted"] for r in lofo]), y),
        "current": wm.decile_table(np.concatenate([r["p_current"] for r in lofo]), y),
    }


def run() -> dict:
    homes = wm.load_homes()
    population = json.loads(wm.POPULATION.read_text())
    lofo = leave_one_fire_out(homes, population)
    palisades = next(r for r in lofo if r["fire"] == HOLDOUT_FIRE)
    example = holdout_metrics(
        [h for h in homes if h.fire in EXAMPLE_TRAIN], [h for h in homes if h.fire == HOLDOUT_FIRE]
    )
    weight = [r["n"] for r in lofo]
    urban = [r for r in lofo if r["fire"] in URBAN_CONFLAGRATION]
    other = [r for r in lofo if r["fire"] not in URBAN_CONFLAGRATION]

    def mean(rows: list[dict], key: str) -> float:
        rated = [r for r in rows if not math.isnan(r[key])]
        return float(np.average([r[key] for r in rated], weights=[r["n"] for r in rated]))

    return {
        "lofo": lofo, "features": feature_table(homes), "counts": count_table(homes), "deciles": pooled_deciles(lofo),
        "palisades_holdout": palisades, "example_split": example, "proposal": proposal(homes, palisades),
        "n_sample": len(homes), "n_fires": len(lofo), "weights": weight,
        "mean_auc": {
            "current": mean(lofo, "auc_current"), "fitted": mean(lofo, "auc_fitted"),
            "current_urban": mean(urban, "auc_current"), "fitted_urban": mean(urban, "auc_fitted"),
            "current_other": mean(other, "auc_current"), "fitted_other": mean(other, "auc_fitted"),
        },
    }  # fmt: skip


def _clean(value):
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items() if k not in ("p_fitted", "p_current", "y")}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    if isinstance(value, (np.floating, float)):
        return None if math.isnan(value) else round(float(value), 5)
    return value


def write(result: dict) -> None:
    RESULTS.mkdir(exist_ok=True)
    FITTED.mkdir(exist_ok=True)
    cols = ["fire", "start_year", "n_inspected", "n_sample", "n_complete", "destroyed_share_population",
            "auc_current", "auc_fitted", "all_auc_current", "all_auc_fitted", "auc_current_loss_rel", "log_loss_current", "log_loss_fitted", "cal_slope_current",
            "cal_slope_fitted"]  # fmt: skip
    with (RESULTS / "wildfire_fires.csv").open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(_clean(result["lofo"]))
    feature_cols = ["feature", "n_known", "share_unknown", "observed_rr", "observed_rr_ci_low", "observed_rr_ci_high",
                    "modelled_rr_destroyed", "modelled_rr_loss", "observed_over_modelled", "fitted_or",
                    "fitted_or_ci_low", "fitted_or_ci_high", "or_unknown_vs_unfavourable"]  # fmt: skip
    with (RESULTS / "wildfire_features.csv").open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=feature_cols, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(_clean(result["features"]))
    summary = {
        "fit_date": FIT_DATE, "n_sample": result["n_sample"], "n_fires": result["n_fires"],
        "mean_auc_weighted_by_n": _clean(result["mean_auc"]),
        "palisades_holdout": _clean(result["palisades_holdout"]),
        "example_split_eaton_camp_to_palisades": _clean(result["example_split"]),
        "counts": _clean(result["counts"]), "deciles": _clean(result["deciles"]),
    }  # fmt: skip
    (RESULTS / "wildfire_summary.json").write_text(json.dumps(summary, indent=1))
    (FITTED / "wildfire_relativities.json").write_text(json.dumps(_clean(result["proposal"]), indent=1))


if __name__ == "__main__":
    write(run())
    print("wrote results/ and fitted/")
