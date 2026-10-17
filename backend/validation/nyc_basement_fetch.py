"""Fetch NFIP basement claims for Hurricane Sandy and the Ida NY/NJ pluvial event (live; needs the network).

Dataset: OpenFEMA NfipClaims v3, https://www.fema.gov/api/open/v3/NfipClaims (field notes in
docs/validation/flood.md). Basement claims are `basementEnclosureCrawlspaceType` 1 or 2 on single-family buildings.
Sandy is NY and NJ claims with a loss date from 2012-10-27 to 2012-11-05; Ida NY/NJ is 2021-09-01 to 2021-09-04.

Run (from backend/):  uv run python -m validation.nyc_basement_fetch [--out validation/data/nyc_basement_full.csv]
"""

import argparse
import csv
import sys
import time
from pathlib import Path

import httpx

URL = "https://www.fema.gov/api/open/v3/NfipClaims"
FIELDS = (
    "id", "state", "yearOfLoss", "dateOfLoss", "waterDepth", "buildingDamageAmount", "buildingPropertyValue",
    "totalBuildingInsuranceCoverage", "numberOfFloorsInTheInsuredBuilding", "basementEnclosureCrawlspaceType",
    "occupancyType", "censusGeoid", "ratedFloodZone", "reportedZipCode", "countyCode", "latitude", "longitude",
    "contentsDamageAmount",
)
BASE = (
    "(occupancyType eq 1 or occupancyType eq 11) and basementEnclosureCrawlspaceType ge 1 "
    "and basementEnclosureCrawlspaceType le 2 and waterDepth ge 0 and waterDepth le 240 "
    "and buildingPropertyValue ge 20000 and buildingDamageAmount ge 0"
)
EVENTS = {
    "Sandy 2012": ("2012-10-27T00:00:00.000Z", "2012-11-05T23:59:59.000Z"),
    "Ida 2021 NY/NJ": ("2021-09-01T00:00:00.000Z", "2021-09-04T23:59:59.000Z"),
}
STATES = ("NY", "NJ")
PAGE = 1000


def fetch_event(client: httpx.Client, state: str, start: str, end: str, log=print) -> list[dict]:
    flt = f"state eq '{state}' and dateOfLoss ge '{start}' and dateOfLoss le '{end}' and {BASE}"
    rows: list[dict] = []
    skip = 0
    while True:
        params = {"$filter": flt, "$select": ",".join(FIELDS), "$orderby": "id", "$top": PAGE, "$skip": skip}
        for attempt in range(4):
            try:
                resp = client.get(URL, params=params, timeout=90)
                resp.raise_for_status()
                break
            except httpx.HTTPError:
                if attempt == 3:
                    raise
                time.sleep(2**attempt)
        page = resp.json()["NfipClaims"]
        rows.extend(page)
        log(f"{state} {start[:10]} skip {skip}: {len(page)}")
        if len(page) < PAGE:
            return rows
        skip += PAGE


def fetch_all(log=print) -> list[dict]:
    out: list[dict] = []
    with httpx.Client() as client:
        for event, (start, end) in EVENTS.items():
            for state in STATES:
                for row in fetch_event(client, state, start, end, log):
                    row["event"] = event
                    out.append(row)
    return out


def write_csv(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["event", *FIELDS], extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="validation/data/nyc_basement_full.csv")
    args = parser.parse_args()
    rows = fetch_all(log=lambda m: print(m, file=sys.stderr))
    write_csv(rows, Path(args.out))
    print(f"wrote {len(rows)} rows to {args.out}")


if __name__ == "__main__":
    main()
