"""Rewrite the engine-derived golden files from the engine.

contracts/golden_scenarios.json: engine-owned sections of each scenario.
contracts/golden_simulations.json: summary of every action subset per scenario.

Run from the repo root:  uv run --directory backend python scripts/regen_golden.py
tests/test_golden_sync.py fails if either file drifts from the engine.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.fixtures import GOLDEN_PATH, SIMULATIONS_PATH, reconcile, simulation_table


def main() -> None:
    raw = json.loads(GOLDEN_PATH.read_text())
    golden = {k: reconcile(v) for k, v in raw.items()}
    GOLDEN_PATH.write_text(json.dumps(golden, indent=2) + "\n")
    sims = {k: simulation_table(v) for k, v in golden.items()}
    SIMULATIONS_PATH.write_text(json.dumps(sims, indent=2) + "\n")
    print(f"rewrote {GOLDEN_PATH} and {SIMULATIONS_PATH}")


if __name__ == "__main__":
    main()
