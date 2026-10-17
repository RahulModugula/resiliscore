"""Add the three NYC golden parcels to contracts/golden_scenarios.json (and their NRI tracts to the reference file).

Inputs, all recorded and committed:
* tests/fixtures/nyc/<slug>.json: the NYC data sources for the address (GeoSearch, PLUTO, DEP stormwater, FloodNet,
  311, DOB, footprints, zones), replayed through the real pipeline.
* tests/fixtures/nyc/golden_federal.json: the federal layers (NFHL, EPQS, NRI tract, NOAA, LANDFIRE) captured live on
  2026-10-17 by the engine for the same points (run `uv run python scripts/snapshot_nyc_federal.py` to refresh).

The parcel is built by `pipeline.build_parcel_for_address`, its hazard layer and tract are replaced by the snapshot,
and the engine sections are then filled by scripts/regen_golden.py. Run from backend/:
    uv run python scripts/build_nyc_golden.py && uv run python scripts/regen_golden.py
"""

import asyncio
import json
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from test_nyc import Replay

from app import http, pipeline
from app.fixtures import GOLDEN_PATH
from app.ingestion import nri
from app.ingestion.nyc.common import NycCaches
from app.models.schemas import InputProvenance, PublicHazardLayer

SCENARIOS = {"red_hook": "NYC_RED_HOOK", "hollis": "NYC_HOLLIS", "rockaway": "NYC_ROCKAWAY"}
FEDERAL = json.loads((ROOT / "tests" / "fixtures" / "nyc" / "golden_federal.json").read_text())
NRI_FILE = ROOT / "data" / "nri_reference_tracts.json"
FEDERAL_FIELDS = {
    "fema_flood_zone", "bfe_ft_navd88", "usgs_lag_ft", "est_ffe_ft", "freeboard_delta_h_ft", "noaa_atlas15_p24h_100yr_in",
    "atlas15_cmip6_mult", "landfire_fbfm40_code", "hand_rel_elev_ft", "twi_index", "slope_deg", "wui_class",
    "wrc_burn_probability", "openfema_tract_claim_count", "openfema_tract_mean_lcr", "tract_prior_lcr",
}


def build(slug: str) -> dict:
    rep = Replay(slug)
    http._client = rep.client()
    pipeline.NYC_CACHES = NycCaches()
    built = asyncio.run(pipeline.build_parcel_for_address(rep.data["address"]))
    snap = FEDERAL[slug]
    r = built.parcel
    layer = PublicHazardLayer.model_validate(snap["layer"])
    bbl = r.nyc.bbl
    identity = r.parcel_identity.model_copy(update={"apn_uid": f"{bbl}0000"})  # 10-digit BBL padded to the 14-digit apn
    kept = [p for p in r.input_provenance if p.field not in FEDERAL_FIELDS]
    federal = [InputProvenance.model_validate(p) for p in snap["provenance"] if p["field"] in FEDERAL_FIELDS]
    vintages = {**r.regulatory_compliance.dataset_vintages, **snap["vintages"]}
    compliance = r.regulatory_compliance.model_copy(update={"dataset_vintages": vintages})
    parcel = r.model_copy(update={
        "parcel_identity": identity, "public_hazard_layer": layer, "regulatory_compliance": compliance,
        "input_provenance": federal + kept, "indicative_only": False,
        "request_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"resiliscore/{slug}")),
    })
    return {"parcel": parcel, "snapshot": snap, "bbl": bbl}


def add_reference_tract(entry: dict, scenario: str, layer: PublicHazardLayer) -> None:
    doc = json.loads(NRI_FILE.read_text())
    t = entry["snapshot"]["nri_tract"]
    doc["tracts"] = [x for x in doc["tracts"] if scenario not in x["scenario_ids"]]
    hazards = {}
    for code in nri.PERILS:
        hazards[code] = {"ealb_usd": t["ealb_usd"].get(code, 0.0), "expb_usd": t["expb_usd"].get(code, 0.0), "afreq": 0.0}
    doc["tracts"].append({
        "tractfips": t["tract_fips"], "stcofips": t["tract_fips"][:5], "scenario_ids": [scenario],
        "point_lng_lat": entry["snapshot"]["point"], "buildvalue_usd": t["buildvalue_usd"], "hazards": hazards,
        "reference_hazard": layer.model_dump(),
    })
    NRI_FILE.write_text(json.dumps(doc, indent=2) + "\n")


def main() -> None:
    golden = json.loads(GOLDEN_PATH.read_text())
    for slug, scenario in SCENARIOS.items():
        entry = build(slug)
        golden[scenario] = entry["parcel"].model_dump(mode="json")
        add_reference_tract(entry, scenario, entry["parcel"].public_hazard_layer)
        print(scenario, entry["bbl"], entry["parcel"].parcel_identity.address)
    GOLDEN_PATH.write_text(json.dumps(golden, indent=2) + "\n")


if __name__ == "__main__":
    main()
