"""Golden demo scenarios, loaded once from contracts/golden_scenarios.json (the demo's source of truth)."""

import json
from functools import cache
from pathlib import Path

from app import provenance
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


# Sections of a golden scenario that the engine owns; everything else is input (parcel, hazard, verification).
ENGINE_SECTIONS = (
    "actuarial_breakdown", "prescriptive_mitigations", "hitl_status", "regulatory_compliance",
    "factor_contributions", "uncertainty", "premium_build",
)


def reconcile(raw: dict) -> dict:
    """Return the scenario with its engine-derived sections replaced by what `simulate` outputs.

    Scored with no extra actions: the verification layer already holds each scenario's applied actions, and
    re-applying them would overwrite as-found flags (the __UNPERMITTED variant keeps its shed).
    """
    from app.actuarial.optimizer import simulate  # local: optimizer must not import this module's cache
    from app.ingestion.rasters import VINTAGES

    out = simulate(ParcelScoreResponse.model_validate(raw), []).model_dump(mode="json")
    new = {**raw, **{k: out[k] for k in ENGINE_SECTIONS}}
    new["regulatory_compliance"]["dataset_vintages"] = {
        **new["regulatory_compliance"]["dataset_vintages"],
        "OpenFEMA": VINTAGES["OpenFEMA"],
    }
    # The golden parcels are the reference set, so every input is REFERENCE_PARCEL and the score is not indicative.
    new["input_provenance"] = [
        row.model_dump(mode="json") for row in provenance.build(ParcelScoreResponse.model_validate(new))
    ]
    return new


SIMULATIONS_PATH = GOLDEN_PATH.with_name("golden_simulations.json")
SIMULATIONS_SCHEMA_PATH = GOLDEN_PATH.with_name("golden_simulations_schema.json")


def subset_key(action_ids) -> str:
    """Key for a set of selected actions: sorted ids joined with "+", "" for none."""
    return "+".join(sorted(action_ids))


def simulation_summary(base: ParcelScoreResponse, selected: list[str]) -> dict:
    """Headline numbers of `simulate(base, selected)`; net capex counts only actions not already applied."""
    from app.actuarial.optimizer import simulate

    before, out = simulate(base, []), simulate(base, selected)
    applied = {m.action_id for m in before.prescriptive_mitigations if m.currently_applied}
    b = out.actuarial_breakdown
    return {
        "resili_score": b.resili_score,
        "underwriting_tier": b.underwriting_tier,
        "posterior_lcr": b.posterior_lcr,
        "credibility_weight_z": b.credibility_weight_z,
        "expected_annual_loss_usd": b.expected_annual_loss_usd,
        "statutory_discount_pct": b.statutory_discount_pct,
        "annual_discounted_premium_usd": b.annual_discounted_premium_usd,
        "total_annual_savings_usd": round(b.annual_base_premium_usd - b.annual_discounted_premium_usd, 2),
        "net_capex_usd": sum(
            m.net_capex_usd for m in out.prescriptive_mitigations if m.action_id in set(selected) - applied
        ),
        "trigger_code": out.hitl_status.trigger_code,
    }


def simulation_table(raw: dict) -> dict[str, dict]:
    """Summary for every subset of the scenario's applicable actions, keyed by `subset_key`."""
    from itertools import combinations

    from app.actuarial.optimizer import simulate

    base = ParcelScoreResponse.model_validate(raw)
    ids = [m.action_id for m in simulate(base, []).prescriptive_mitigations]
    return {
        subset_key(combo): simulation_summary(base, list(combo))
        for r in range(len(ids) + 1)
        for combo in combinations(ids, r)
    }
