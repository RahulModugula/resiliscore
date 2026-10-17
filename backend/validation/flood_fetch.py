"""Fetch NFIP flood claims from OpenFEMA for the flood validation (live; needs the network).

Dataset: NfipClaims v3, https://www.fema.gov/api/open/v3/NfipClaims. Field names and meanings were read from
the dataset metadata (OpenFemaDataSetFields) on 2026-10-17. Notes from that metadata:
  * waterDepth is "depth of flood water in inches" with the reference level unstated, and "there are
    instances where measurements were provided in feet".
  * buildingDamageAmount and buildingPropertyValue are actual cash value, in dollars.
  * latitude / longitude are rounded to one decimal place; censusGeoid is a census block group.

Run (from backend/):  uv run python -m validation.flood_fetch [--out validation/data/claims_full.csv]
"""

import argparse
import csv
import sys
import time
from pathlib import Path

import httpx

URL = "https://www.fema.gov/api/open/v3/NfipClaims"
DATASET = "NfipClaims"
DATASET_VERSION = 3
STATES = ("LA", "TX", "FL", "NJ", "NY", "MS", "NC", "SC")
PAGE = 1000
MIN_YEAR = 2005
MIN_BUILDING_VALUE_USD = 20_000  # drops placeholder values such as $100
MAX_DEPTH_IN = 240

FIELDS = (
    "id", "state", "yearOfLoss", "dateOfLoss", "floodEvent", "waterDepth", "buildingDamageAmount",
    "buildingPropertyValue", "totalBuildingInsuranceCoverage", "numberOfFloorsInTheInsuredBuilding",
    "basementEnclosureCrawlspaceType", "occupancyType", "censusGeoid", "ratedFloodZone", "elevationDifference",
    "latitude", "longitude", "reportedZipCode",
)

# Single-family (1; 11 under Risk Rating 2.0), one floor, no basement, with a depth and a usable value.
BASE_FILTER = (
    "(occupancyType eq 1 or occupancyType eq 11) and numberOfFloorsInTheInsuredBuilding eq 1 "
    "and basementEnclosureCrawlspaceType eq 0 and waterDepth ge 0 "
    f"and waterDepth le {MAX_DEPTH_IN} and buildingPropertyValue ge {MIN_BUILDING_VALUE_USD} "
    f"and buildingDamageAmount ge 0 and yearOfLoss ge {MIN_YEAR}"
)

# Basement claims, kept for the Sandy and Ida-NYC basement split.
BASEMENT_FILTER = (
    "(occupancyType eq 1 or occupancyType eq 11) and basementEnclosureCrawlspaceType ge 1 "
    "and basementEnclosureCrawlspaceType le 2 and waterDepth ge 0 "
    f"and waterDepth le {MAX_DEPTH_IN} and buildingPropertyValue ge {MIN_BUILDING_VALUE_USD} "
    f"and buildingDamageAmount ge 0 and yearOfLoss ge {MIN_YEAR}"
)


def fetch_rows(client: httpx.Client, flt: str, *, retries: int = 4) -> list[dict]:
    """Every row matching `flt`, paged with $skip over a stable $orderby=id."""
    rows: list[dict] = []
    skip = 0
    while True:
        params = {"$filter": flt, "$select": ",".join(FIELDS), "$orderby": "id", "$top": PAGE, "$skip": skip}
        for attempt in range(retries):
            try:
                resp = client.get(URL, params=params, timeout=60)
                resp.raise_for_status()
                break
            except httpx.HTTPError:
                if attempt == retries - 1:
                    raise
                time.sleep(2**attempt)
        page = resp.json()[DATASET]
        rows.extend(page)
        if len(page) < PAGE:
            return rows
        skip += PAGE


def fetch_all(states: tuple[str, ...] = STATES, log=print) -> list[dict]:
    out: list[dict] = []
    with httpx.Client() as client:
        for state in states:
            for label, flt in (("no-basement", BASE_FILTER), ("basement", BASEMENT_FILTER)):
                rows = fetch_rows(client, f"state eq '{state}' and {flt}")
                log(f"{state} {label}: {len(rows)} rows")
                out.extend(rows)
    return out


def write_csv(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="validation/data/claims_full.csv")
    args = parser.parse_args()
    rows = fetch_all(log=lambda m: print(m, file=sys.stderr))
    write_csv(rows, Path(args.out))
    print(f"wrote {len(rows)} rows to {args.out}")


if __name__ == "__main__":
    main()
