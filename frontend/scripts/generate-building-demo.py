#!/usr/bin/env python3
"""Generate NY demo counterfactuals with the canonical engine; no network or golden inputs.

Run after generate-manhattan-screening.py, with backend dependencies installed.
The UI supplies real building identity/geometry, while these explicit default-input
scenarios remain separate from its recorded assessment and never establish verification.
"""
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from app.actuarial.optimizer import simulate
from app.models.schemas import ParcelScoreResponse

SOURCE = ROOT / "frontend/src/data/manhattan/screening.json"
OUT = ROOT / "frontend/src/data/manhattan/building-demo.json"
screening = json.loads(SOURCE.read_text())
# Fail instead of generating projections from a stale baseline cache.
engine_hash = hashlib.sha256()
for name in screening["engineFiles"]:
    engine_hash.update(name.encode())
    engine_hash.update((ROOT / name).read_bytes())
assert engine_hash.hexdigest() == screening["engineSha256"], "Regenerate Manhattan screening first"

projections = {}
for era, cached in screening["screens"].items():
    projections[era] = {}
    for roof in (False, True):
        for reviewed in (False, True):
            base = ParcelScoreResponse.model_validate(cached)
            if reviewed:
                base = base.model_copy(update={"private_verification_layer": base.private_verification_layer.model_copy(update={"cv_confidence": 0.99})})
            ids = ["HAIL_CLASS4_ROOF"] if roof else []
            result = simulate(base, ids).model_dump(mode="json")
            assert result["indicative_only"]
            assert result["parcel_identity"]["state"] == "NY"
            assert result["public_hazard_layer"]["usgs_lag_ft"] is None
            # Store exact engine outputs rather than summing individual action credits.
            projections[era][f"{int(roof)}:{int(reviewed)}"] = {name: result[name] for name in (
                "actuarial_breakdown", "premium_build", "private_verification_layer", "hitl_status", "prescriptive_mitigations"
            )}

output = {
    "engineSha256": engine_hash.hexdigest(),
    "screeningSha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
    "yearCutoff": screening["yearCutoff"],
    "replacementValueUsd": screening["screens"]["pre2002"]["parcel_identity"]["rcv_usd"],
    "method": "Canonical optimizer.simulate on NY national-default screening. Nonlocal NRI reference, no measured hazard lookup, hypothetical roof completion and CV review. No filed NY quote, actual verification or policy authority.",
    "projections": projections,
}
serialized = json.dumps(output, sort_keys=True, indent=2) + "\n"
if "--check" in sys.argv:
    if OUT.read_text() != serialized:
        raise SystemExit("Building demo cache differs from the canonical engine. Regenerate it.")
    print("Building demo projections match canonical engine exactly.")
else:
    OUT.write_text(serialized)
    print(f"Wrote {OUT.relative_to(ROOT)}")
