"""Cut the small committed sample (under 2 MB) from a full claims pull, so tests and CI need no network.

Stratified by (state, event-or-year): up to PER_CELL rows per cell, chosen with a fixed seed, so every state
and every named event keeps rows. Basement claims for the Sandy and Ida windows are kept in full up to a cap.

Usage (from backend/):  uv run python -m validation.flood_sample --full validation/data/claims_full.csv
"""

import argparse
import csv
import random
from collections import defaultdict
from pathlib import Path

from validation.flood_fetch import FIELDS

HERE = Path(__file__).resolve().parent
PER_CELL = 25
SEED = 20261017
MAX_BYTES = 1_800_000


def build_sample(full: Path, out: Path) -> int:
    cells: dict[tuple, list[dict]] = defaultdict(list)
    with full.open(newline="") as fh:
        for r in csv.DictReader(fh):
            basement = r["basementEnclosureCrawlspaceType"] not in ("0", "0.0", "")
            cells[(r["state"], r["floodEvent"] or r["yearOfLoss"], basement)].append(r)
    rng = random.Random(SEED)
    keep: list[dict] = []
    for key in sorted(cells, key=str):
        rows = cells[key]
        keep.extend(rng.sample(rows, min(PER_CELL, len(rows))))
    keep.sort(key=lambda r: int(r["id"]))
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(keep)
    if out.stat().st_size > MAX_BYTES:
        raise SystemExit(f"sample is {out.stat().st_size} bytes, over the {MAX_BYTES} limit; lower PER_CELL")
    return len(keep)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", default=str(HERE / "data" / "claims_full.csv"))
    parser.add_argument("--out", default=str(HERE / "data" / "claims_sample.csv"))
    args = parser.parse_args()
    print(f"wrote {build_sample(Path(args.full), Path(args.out))} rows to {args.out}")


if __name__ == "__main__":
    main()
