"""Golden demo scenarios, loaded once from contracts/golden_scenarios.json (the demo's source of truth)."""

import json
from functools import cache
from pathlib import Path

from app.models.schemas import ParcelScoreResponse

GOLDEN_PATH = Path(__file__).resolve().parents[2] / "contracts" / "golden_scenarios.json"


@cache
def load_golden() -> dict[str, ParcelScoreResponse]:
    """Every golden scenario, keyed by scenario id, in file order."""
    raw = json.loads(GOLDEN_PATH.read_text())
    return {key: ParcelScoreResponse.model_validate(body) for key, body in raw.items()}


def by_scenario(scenario_id: str) -> ParcelScoreResponse | None:
    return load_golden().get(scenario_id)


def by_apn(apn_uid: str) -> ParcelScoreResponse | None:
    """First golden scenario for a parcel. The base scenario precedes its __VARIANT in file order."""
    return next((r for r in load_golden().values() if r.parcel_identity.apn_uid == apn_uid), None)


def by_address(address: str) -> ParcelScoreResponse | None:
    """Case-insensitive exact match against the golden addresses."""
    wanted = address.strip().casefold()
    return next((r for r in load_golden().values() if r.parcel_identity.address.casefold() == wanted), None)
