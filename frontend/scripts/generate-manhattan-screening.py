#!/usr/bin/env python3
"""Cache the canonical engine's two NY construction-era outputs, without network access.

Run from the repo: backend-environment-python frontend/scripts/generate-manhattan-screening.py [--check]
No golden response is read or used as an input. The engine's own explicit nearest-NRI stand-in policy
is retained and marked REFERENCE_PARCEL. These are default-input screens, not NY hazard observations.
"""
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from app.actuarial.constants import get as constant
from app.actuarial.optimizer import simulate
from app.ingestion.engine import SpatialIngestionEngine
from app.models.schemas import Ca26449Factors, ParcelScoreResponse
from app.pipeline import DEFAULT_RCV_USD, DEFAULT_YEAR_BUILT

OUT = ROOT / "frontend/src/data/manhattan/screening.json"
ENGINE_FILES = sorted((ROOT / "backend/app/actuarial").glob("*.py")) + [
    ROOT / "backend/app/ingestion/rasters.py", ROOT / "backend/app/ingestion/engine.py",
    ROOT / "backend/app/pipeline.py", ROOT / "backend/data/nri_reference_tracts.json",
]
engine_hash = hashlib.sha256()
for path in ENGINE_FILES:
    engine_hash.update(path.relative_to(ROOT).as_posix().encode())
    engine_hash.update(path.read_bytes())

def screen(year):
    hazard = SpatialIngestionEngine._assemble(None, None, None, None, None, None)
    ring = [[-74.0001, 40.7499], [-73.9999, 40.7499], [-73.9999, 40.7501], [-74.0001, 40.7501], [-74.0001, 40.7499]]
    p = ParcelScoreResponse.model_validate({
        "request_id": "00000000-0000-4000-8000-000000000001", "processing_time_ms": 0,
        "parcel_identity": {"apn_uid": "00000000000000", "address": "Offline NY default-input model screen", "county_fips": "36061", "state": "NY", "h3_res11": "", "h3_res13": "", "rcv_usd": DEFAULT_RCV_USD, "year_built": year, "centroid": [-74.0, 40.75], "geometries": {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [ring]}, "properties": {"kind": "building_footprint", "label": "Placeholder replaced by selected NYC building"}}]}},
        "public_hazard_layer": hazard.layer.model_dump(),
        "private_verification_layer": {"cv_roof_class": "WOOD_SHAKE_UNRATED", "cv_confidence": 0, "cv_overhang_ft": 0, "cv_zone0_clear": False, "cv_zone1_no_shed": False, "cv_enclosed_eaves": False, "cv_ember_vents": False, "elev_cert_verified": False, "ibhs_fortified_tier": "NONE", "ibhs_wph_tier": "NONE", "iot_shutoff_active": False, "unpermitted_footprint_delta_sqft": 0},
        "actuarial_breakdown": {"tract_prior_lcr": 0, "parcel_raw_lcr": 0, "credibility_weight_z": 0, "posterior_lcr": 0, "expected_annual_loss_usd": 0, "peril_split": [], "resili_score": 300, "baseline_macro_score": 300, "underwriting_tier": "TIER_3_DECLINE_ESCALATE", "statutory_discount_pct": 0, "annual_base_premium_usd": 0, "annual_discounted_premium_usd": 0},
        "prescriptive_mitigations": [], "hitl_status": {"escalated": False, "trigger_code": "NONE", "trigger_reason": None, "recommended_underwriter_action": None},
        "regulatory_compliance": {"monotonicity_verified": False, "ny_dfs_cl7_ecdis_free": False, "ca_2644_9_factors": {k: False for k in Ca26449Factors.model_fields}, "dataset_vintages": {}},
        "indicative_only": True, "input_provenance": [r.model_dump() for r in hazard.provenance] + [
            {"field": "rcv_usd", "value_source": "DEFAULT", "source_name": "backend.app.pipeline.DEFAULT_RCV_USD; not a NYC valuation", "vintage": None},
            {"field": "year_built", "value_source": "DEFAULT", "source_name": "Construction era cache representative; runtime selects pre/post 2002 using mapped year or default 1990", "vintage": None},
            {"field": "private_verification_layer", "value_source": "UNAVAILABLE", "source_name": "No property verification supplied; false means unknown or not established", "vintage": None},
            {"field": "credibility.lidar_1m", "value_source": "DEFAULT", "source_name": "Canonical engine assumes LiDAR weight 0.6 even without measured elevation; not verified evidence", "vintage": None},
        ],
    })
    out = simulate(p, [])
    assert out.indicative_only and out.hitl_status.escalated
    assert out.private_verification_layer.cv_confidence == 0
    assert out.actuarial_breakdown.statutory_discount_pct == 0
    assert any(r.value_source == "REFERENCE_PARCEL" for r in out.input_provenance)
    result = out.model_dump(mode="json")
    result["processing_time_ms"] = 0
    return result

cutoff = int(constant("wind.pre_code_year"))
pre = screen(cutoff - 1)
post = screen(cutoff)
# Geometry/elevation are not risk inputs under this no-live-evidence path. If the engine gains a
# continuous construction-age effect, these checks reject a cache that covers only two eras.
assert screen(1800)["actuarial_breakdown"] == pre["actuarial_breakdown"]
assert screen(2026)["actuarial_breakdown"] == post["actuarial_breakdown"]

result = {
    "engineSha256": engine_hash.hexdigest(),
    "engineFiles": [p.relative_to(ROOT).as_posix() for p in ENGINE_FILES],
    "method": "Canonical backend optimizer.simulate, NY state, national-default hazards, no property verification, default $350,000 RCV, nearest reference NRI stand-in. No live geographic hazard lookup. Model assumes a LiDAR weight even though local evidence is absent. Not a production underwriting model or filed quote.",
    "yearCutoff": cutoff,
    "defaultYearBuilt": DEFAULT_YEAR_BUILT,
    "screens": {"pre2002": pre, "post2002": post},
}
serialized = json.dumps(result, indent=2, sort_keys=True) + "\n"
if "--check" in sys.argv:
    if OUT.read_text() != serialized:
        raise SystemExit("Offline screening cache differs from the canonical engine. Regenerate it.")
    print("Offline screening cache matches canonical engine exactly.")
else:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(serialized)
    print(f"Wrote {OUT.relative_to(ROOT)}")
