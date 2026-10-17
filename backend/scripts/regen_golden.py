"""Rewrite contracts/golden_scenarios.json so every engine-derived field equals the engine's output.

Run from the repo root:  uv run --directory backend python scripts/regen_golden.py
tests/test_golden_sync.py fails if the file drifts from the engine.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.fixtures import GOLDEN_PATH, reconcile


def main() -> None:
    raw = json.loads(GOLDEN_PATH.read_text())
    GOLDEN_PATH.write_text(json.dumps({k: reconcile(v) for k, v in raw.items()}, indent=2) + "\n")
    print(f"rewrote {GOLDEN_PATH}")


if __name__ == "__main__":
    main()
