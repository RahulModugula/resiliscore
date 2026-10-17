"""Cut the small committed sample (about 1.4 MB) from the full basement-claims pull, so tests need no network.

Every Ida NY/NJ claim is kept; Sandy is sampled uniformly with a fixed seed. The sample is not representative of
the full means, so the committed results come from the full pull and the tests only check the direction.

Usage (from backend/):  uv run python -m validation.nyc_basement_sample --full validation/data/nyc_basement_full.csv
"""

import argparse
import csv
import random
from pathlib import Path

HERE = Path(__file__).resolve().parent
SEED = 20261017
SANDY_ROWS = 5000


def build_sample(full: Path, out: Path) -> int:
    with full.open(newline="") as fh:
        reader = csv.DictReader(fh)
        fields = reader.fieldnames or []
        rows = list(reader)
    rng = random.Random(SEED)
    sandy = [r for r in rows if r["event"] == "Sandy 2012"]
    keep = [r for r in rows if r["event"] != "Sandy 2012"] + rng.sample(sandy, min(SANDY_ROWS, len(sandy)))
    keep.sort(key=lambda r: (r["event"], int(r["id"])))
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(keep)
    return len(keep)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", default=str(HERE / "data" / "nyc_basement_full.csv"))
    parser.add_argument("--out", default=str(HERE / "data" / "nyc_basement_sample.csv"))
    args = parser.parse_args()
    print(f"wrote {build_sample(Path(args.full), Path(args.out))} rows to {args.out}")


if __name__ == "__main__":
    main()
