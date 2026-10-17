"""Which registry rules apply to a scored parcel."""

from app.models.schemas import ParcelScoreResponse
from app.rules.registry import Rule, get

GRANT_BY_STATE = {"LA": "LA_FORTIFY_HOMES_GRANT", "AL": "AL_STRENGTHEN_ALABAMA_HOMES"}


def applied_rule_ids(parcel: ParcelScoreResponse) -> list[str]:
    """Registry rules whose discount or duty is in force for the parcel's verified features."""
    state = parcel.parcel_identity.state
    pvl = parcel.private_verification_layer
    ids: list[str] = []
    if state == "CA":
        factors = parcel.regulatory_compliance.ca_2644_9_factors.model_dump()
        if any(factors[k] for k in factors if k.startswith(("cat_a", "cat_b"))):
            ids.append("CA_CCR_2644_9")
    if state == "LA" and pvl.ibhs_fortified_tier != "NONE":
        ids.append("LA_REG_136")
    if state == "NY":
        ids.append("NY_DFS_CL_2024_07")
    return ids


def grant_ids(parcel: ParcelScoreResponse, action_ids: list[str]) -> list[str]:
    """Grants that pay toward the chosen actions still to be done (non-zero grant subsidy, not yet applied)."""
    chosen = set(action_ids)
    funded = any(
        m.grant_subsidy_usd > 0 and not m.currently_applied
        for m in parcel.prescriptive_mitigations
        if m.action_id in chosen
    )
    grant = GRANT_BY_STATE.get(parcel.parcel_identity.state)
    return [grant] if funded and grant else []


def cite(rule_ids: list[str]) -> list[Rule]:
    return [get(i) for i in rule_ids]
