"""Pull CAL FIRE DINS structure outcomes and write the small committed sample (run by hand; CI never calls it).

Endpoint (found by web search, read 2026-10-17): CAL FIRE Damage Inspection Program (DINS) database, ArcGIS
FeatureServer "POSTFIRE_MASTER_DATA_SHARE", layer 0, 2013-present, maxRecordCount 2000. Non-damaged structures are
recorded only from 2018 on, so earlier fires hold damaged structures only and are excluded here.

    cd backend && uv run python -m validation.wildfire_fetch --list
    cd backend && uv run python -m validation.wildfire_fetch
"""

import argparse
import csv
import json
import random
from collections import Counter
from pathlib import Path

import httpx

LAYER_URL = "https://services1.arcgis.com/jUJYIo9tSA7EHvfZ/ArcGIS/rest/services/POSTFIRE_MASTER_DATA_SHARE/FeatureServer/0"
PAGE = 2000
TIMEOUT_S = 90.0
MIN_STRUCTURES = 300
MIN_UNDAMAGED_SHARE = 0.05  # inspections of undamaged structures begin in 2018
PER_FIRE_CAP = 300  # keeps the sample under the 2 MB budget
KEY_FIRES = ("Eaton", "Palisades", "Camp")  # the demo area and the two other large wind-driven fires
KEY_FIRE_CAP = 1500
SEED = 20261017
OUT = Path(__file__).parent / "data" / "wildfire_dins_sample.csv"
POPULATION_OUT = Path(__file__).parent / "data" / "wildfire_population.json"  # full-population counts per fire
FIELDS = (
    "OBJECTID", "INCIDENTNAME", "INCIDENTSTARTDATE", "DAMAGE", "STRUCTURECATEGORY", "ROOFCONSTRUCTION", "EAVES",
    "VENTSCREEN", "EXTERIORSIDING", "WINDOWPANE", "DECKPORCHONGRADE", "DECKPORCHELEVATED", "PATIOCOVERCARPORT",
    "UTILITYMISCSTRUCTUREDISTANCE", "YEARBUILT",
)  # fmt: skip
OUT_FIELDS = tuple(f for f in FIELDS if f not in ("INCIDENTSTARTDATE", "STRUCTURECATEGORY"))  # keeps the sample small
MIN_DESTROYED = 30  # below this a destroyed-vs-not AUC is noise, so the fire stays out of the sample
DAMAGE_CLASSES = ("Destroyed (>50%)", "Major (25-50%)", "Minor (10-25%)", "Affected (>0-10%)", "No Damage")


def _query(client: httpx.Client, **params) -> dict:
    response = client.get(f"{LAYER_URL}/query", params={"f": "json", **params}, timeout=TIMEOUT_S)
    response.raise_for_status()
    body = response.json()
    if "error" in body:
        raise RuntimeError(body["error"])
    return body


def list_fires(client: httpx.Client) -> list[dict]:
    """Fires with at least MIN_STRUCTURES inspected structures and a recorded share of undamaged ones.

    A fire that recorded only damaged structures (all pre-2018 fires, e.g. Tubbs and Thomas) has no negatives, so
    destroyed-vs-not cannot be measured there; MIN_UNDAMAGED_SHARE screens those out.
    """
    where = "DAMAGE IN ({})".format(",".join(f"'{d}'" for d in DAMAGE_CLASSES))
    stats = [{"statisticType": "count", "onStatisticField": "OBJECTID", "outStatisticFieldName": "n"}]
    body = _query(
        client, where=where, outStatistics=json.dumps(stats), groupByFieldsForStatistics="INCIDENTNAME,DAMAGE"
    )
    total: Counter = Counter()
    undamaged: Counter = Counter()
    for f in body["features"]:
        a = f["attributes"]
        total[a["INCIDENTNAME"]] += a["n"]
        if a["DAMAGE"] == "No Damage":
            undamaged[a["INCIDENTNAME"]] += a["n"]
    return sorted(
        ({"INCIDENTNAME": k, "n": n} for k, n in total.items() if n >= MIN_STRUCTURES and undamaged[k] / n >= MIN_UNDAMAGED_SHARE),
        key=lambda r: -r["n"],
    )


def fetch_fire(client: httpx.Client, name: str) -> list[dict]:
    """Every inspected structure of one fire, paged by OBJECTID."""
    rows: list[dict] = []
    where = "INCIDENTNAME = '{}' AND DAMAGE IN ({})".format(name, ",".join(f"'{d}'" for d in DAMAGE_CLASSES))
    while True:
        body = _query(
            client, where=where, outFields=",".join(FIELDS), returnGeometry="false",
            orderByFields="OBJECTID", resultOffset=len(rows), resultRecordCount=PAGE,
        )  # fmt: skip
        page = [f["attributes"] for f in body["features"]]
        rows += page
        if not body.get("exceededTransferLimit") and len(page) < PAGE:
            return rows


def sample(rows: list[dict], cap: int = PER_FIRE_CAP) -> list[dict]:
    """Seeded random sample of single residences (the sampling unit the model scores)."""
    homes = [r for r in rows if r["STRUCTURECATEGORY"] == "Single Residence"]
    return random.Random(SEED).sample(homes, min(cap, len(homes)))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--list", action="store_true", help="print the qualifying fires and exit")
    args = parser.parse_args()
    with httpx.Client() as client:
        fires = list_fires(client)
        if args.list:
            for f in fires:
                print(f["INCIDENTNAME"], f["n"])
            return
        out: list[dict] = []
        population: dict[str, dict] = {}
        for fire in fires:
            name = fire["INCIDENTNAME"]
            rows = fetch_fire(client, name)
            homes = [r for r in rows if r["STRUCTURECATEGORY"] == "Single Residence"]
            kept = sample(rows, KEY_FIRE_CAP if name in KEY_FIRES else PER_FIRE_CAP)
            population[name] = {
                "inspected": len(rows),
                "single_residences": len(homes),
                "destroyed": sum(r["DAMAGE"] == "Destroyed (>50%)" for r in homes),
                "start_year": min(r["INCIDENTSTARTDATE"] for r in rows if r["INCIDENTSTARTDATE"]) // 31_557_600_000 + 1970,
            }
            population[name]["in_sample"] = population[name]["destroyed"] >= MIN_DESTROYED
            print(name, population[name], "sampled", len(kept), Counter(r["DAMAGE"] for r in kept))
            if population[name]["in_sample"]:
                out += kept
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=OUT_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(out)
    POPULATION_OUT.write_text(json.dumps(population, indent=1, sort_keys=True))
    print(f"wrote {len(out)} rows, {OUT.stat().st_size / 1e6:.2f} MB")


if __name__ == "__main__":
    main()
