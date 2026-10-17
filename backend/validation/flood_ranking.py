"""Tract-level ranking test: does the model's flood loss cost rank-order observed NFIP claim incidence?

Model side. For each tract the engine is asked for the flood loss rate of its reference home
(`compound_model.peril_terms` with that tract's NRI base rates). The engine solves each peril's intercept so the
reference home's loss rate equals the NRI rate, so this number IS the NRI rate (inland plus coastal flood
expected annual loss over exposed building value), up to the engine's rate floor. The test is therefore a test
of NRI as a ranker. Our own relativities (freeboard, rain, terrain) are all zero for the reference home, so
their lift beyond NRI cannot be measured at tract level; it needs parcel-level hazard inputs and policy-level
claims, neither of which OpenFEMA's redacted claims provide.

Claims side. Single-family NFIP claims (occupancy 1 or 11) from 2005 on whose censusGeoid starts with the
tract FIPS, divided by the tract's NRI flood-exposed building value in $1M (IFLD_EXPB + CFLD_EXPB, the larger
of the two where they overlap is not knowable, so they are summed) and by the 21 loss years 2005-2025.
There are no policy counts, so this is claims per exposed dollar, not claims per policy-year.

Run (from backend/):  uv run python -m validation.flood_ranking --out validation/results/flood_ranking_tracts.csv
"""

import argparse
import csv
import math
import random
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
import numpy as np

from app.actuarial.base_rates import NriRates, base_rates_for
from app.actuarial.compound_model import peril_terms
from app.fixtures import by_apn
from app.models.schemas import PrivateVerificationLayer, PublicHazardLayer

NRI_URL = (
    "https://services.arcgis.com/XG15cJAlne2vxtgt/arcgis/rest/services/"
    "National_Risk_Index_Census_Tracts/FeatureServer/0/query"
)
CLAIMS_URL = "https://www.fema.gov/api/open/v3/NfipClaims"
STATES = ("LA", "TX", "FL", "NY")
TRACTS_PER_STATE = 100
LOSS_YEARS = 21  # 2005..2025
SEED = 20261017
NRI_FIELDS = "TRACTFIPS,STATEABBRV,BUILDVALUE,IFLD_EALB,IFLD_EXPB,CFLD_EALB,CFLD_EXPB,NRI_VER"
TEMPLATE_APN = "02200100041200"  # a flood-active golden hazard layer used only as a neutral template


@dataclass(frozen=True)
class Tract:
    fips: str
    state: str
    nri: NriRates


def fetch_nri_tracts(client: httpx.Client, state: str) -> list[Tract]:
    out: list[Tract] = []
    offset = 0
    while True:
        resp = client.get(NRI_URL, timeout=60, params={
            "where": f"STATEABBRV='{state}'", "outFields": NRI_FIELDS, "returnGeometry": "false",
            "f": "json", "resultOffset": offset, "resultRecordCount": 2000, "orderByFields": "TRACTFIPS",
        })
        resp.raise_for_status()
        feats = resp.json()["features"]
        for f in feats:
            a = f["attributes"]
            value = a.get("BUILDVALUE") or 0
            exp = (a.get("IFLD_EXPB") or 0) + (a.get("CFLD_EXPB") or 0)
            if value > 0 and exp > 0:
                out.append(Tract(str(a["TRACTFIPS"]), state, NriRates(
                    str(a["TRACTFIPS"]), float(value),
                    {"IFLD": float(a.get("IFLD_EALB") or 0), "CFLD": float(a.get("CFLD_EALB") or 0)},
                    {"IFLD": float(a.get("IFLD_EXPB") or 0), "CFLD": float(a.get("CFLD_EXPB") or 0)},
                    version=str(a.get("NRI_VER") or "unknown"),
                )))
        if len(feats) < 2000:
            return out
        offset += 2000


def sample_tracts(tracts: list[Tract], n: int, rng: random.Random) -> list[Tract]:
    """n tracts spread across the deciles of the NRI flood rate, so the predictor's whole range is tested."""
    ranked = sorted(tracts, key=lambda t: t.nri.loss_rate("FLOOD"))
    per = max(1, n // 10)
    picked: list[Tract] = []
    for d in range(10):
        chunk = ranked[d * len(ranked) // 10:(d + 1) * len(ranked) // 10]
        picked.extend(rng.sample(chunk, min(per, len(chunk))))
    return picked


def claim_count(client: httpx.Client, tract_fips: str, retries: int = 4) -> int:
    flt = (f"startswith(censusGeoid,'{tract_fips}') and (occupancyType eq 1 or occupancyType eq 11) "
           "and yearOfLoss ge 2005")
    for attempt in range(retries):
        try:
            resp = client.get(CLAIMS_URL, timeout=60,
                              params={"$filter": flt, "$top": 1, "$select": "id", "$inlinecount": "allpages"})
            resp.raise_for_status()
            return int(resp.json()["metadata"]["count"])
        except (httpx.HTTPError, KeyError, ValueError):
            if attempt == retries - 1:
                raise
            time.sleep(2**attempt)
    raise AssertionError("unreachable")


def model_flood_lcr(t: Tract) -> float:
    """The engine's flood loss rate for the tract's reference home."""
    template = by_apn(TEMPLATE_APN)
    assert template is not None
    # The reference home sits at the base flood elevation (freeboard 0) with no verified elevation certificate.
    hazard: PublicHazardLayer = template.public_hazard_layer.model_copy(update={"freeboard_delta_h_ft": 0.0})
    verification: PrivateVerificationLayer = template.private_verification_layer.model_copy(
        update={"elev_cert_verified": False}
    )
    terms = peril_terms(
        hazard, verification, state=t.state, year_built=1985, base_rates=base_rates_for(t.nri)
    )
    return sum(x.n * x.s for x in terms if x.peril == "FLOOD")


# ---- statistics ----

def ranks(x: np.ndarray) -> np.ndarray:
    order = np.argsort(x, kind="mergesort")
    r = np.empty(len(x))
    r[order] = np.arange(len(x))
    for v in np.unique(x):  # average the ranks of ties
        m = x == v
        if m.sum() > 1:
            r[m] = r[m].mean()
    return r


def spearman(a: np.ndarray, b: np.ndarray) -> float:
    ra, rb = ranks(a), ranks(b)
    if ra.std() == 0 or rb.std() == 0:
        return math.nan
    return float(np.corrcoef(ra, rb)[0, 1])


def spearman_ci(a: np.ndarray, b: np.ndarray, reps: int = 2000, seed: int = SEED) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    vals = []
    for _ in range(reps):
        i = rng.integers(0, len(a), len(a))
        s = spearman(a[i], b[i])
        if not math.isnan(s):
            vals.append(s)
    return float(np.quantile(vals, 0.025)), float(np.quantile(vals, 0.975))


def decile_table(pred: np.ndarray, claims: np.ndarray, exposure_m: np.ndarray) -> list[dict]:
    """Deciles of the model rate (1 = lowest). Observed and expected are claims per $1M exposed per year.

    Expected scales the model rate so that overall expected claims equal overall observed claims, since the
    model rate is a loss cost and the claim rate is a frequency; only the shape is being compared.
    """
    order = np.argsort(pred, kind="mergesort")
    groups = np.array_split(order, 10)
    scale = claims.sum() / (pred * exposure_m).sum()
    rows = []
    for d, idx in enumerate(groups, start=1):
        obs = claims[idx].sum()
        expct = (pred[idx] * exposure_m[idx]).sum() * scale
        rows.append({"decile": d, "tracts": len(idx), "claims": int(obs), "expected_claims": float(expct),
                     "actual_over_expected": float(obs / expct) if expct > 0 else math.nan,
                     "claims_per_m_per_yr": float(obs / exposure_m[idx].sum() / LOSS_YEARS),
                     "mean_model_rate": float(pred[idx].mean())})
    return rows


def gini(pred: np.ndarray, claims: np.ndarray, exposure_m: np.ndarray) -> float:
    """Normalised Gini of the model ordering against claims, weighting tracts by exposure.

    Lorenz curve of cumulative claims against cumulative exposure with tracts sorted by ascending model rate;
    Gini = 1 - 2 * area under it. Positive means higher-ranked tracts hold a larger share of claims.
    """
    order = np.argsort(pred, kind="mergesort")
    x = np.concatenate([[0.0], np.cumsum(exposure_m[order]) / exposure_m.sum()])
    y = np.concatenate([[0.0], np.cumsum(claims[order]) / claims.sum()])
    return float(1 - 2 * np.trapezoid(y, x))


def run(out: Path) -> list[dict]:
    rng = random.Random(SEED)
    rows = []
    with httpx.Client() as client:
        for state in STATES:
            tracts = sample_tracts(fetch_nri_tracts(client, state), TRACTS_PER_STATE, rng)
            print(f"{state}: counting claims for {len(tracts)} tracts", flush=True)
            for i, t in enumerate(tracts):
                if i % 10 == 0:
                    print(f"  {state} tract {i}/{len(tracts)}", flush=True)
                exp_m = (t.nri.expb_usd["IFLD"] + t.nri.expb_usd["CFLD"]) / 1e6
                rows.append({"tract": t.fips, "state": state, "nri_version": t.nri.version,
                             "nri_flood_rate": t.nri.loss_rate("FLOOD"), "model_flood_lcr": model_flood_lcr(t),
                             "exposed_building_value_musd": exp_m, "claims": claim_count(client, t.fips)})
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="validation/results/flood_ranking_tracts.csv")
    args = parser.parse_args()
    rows = run(Path(args.out))
    print(f"wrote {len(rows)} tracts to {args.out}")


if __name__ == "__main__":
    main()
