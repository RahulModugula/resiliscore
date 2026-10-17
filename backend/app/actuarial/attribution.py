"""Score attribution: exact Shapley values over factor groups, in score points.

The score is a function of a handful of factor groups (freeboard, terrain, wildfire hardening, wind roof, water
shut-off, aerial CV evidence, registry and sensor evidence, construction era). The value of a coalition S is the
unrounded score with the groups in S at their actual values and every other group at its neutral value
(mitigation dose 0, evidence channel weight 0, freeboard 0, the tract's reference terrain, reference construction
year). With at
most 8 groups the Shapley value is computed exactly over all 2^n coalitions, so the rows are additive without a
plug:  sum(rows) = score(full) - score(neutral).

One further row, "in-hazard reference home vs tract-wide average", is score(neutral) - score(tract prior): the
reference home is exposed to the hazard (loss rate among exposed buildings) while the credibility prior is the
tract-wide rate, and lidar-only credibility. It is a defined quantity, not a remainder, and there is no
interaction row: Shapley values split interactions between the factors. Together the rows sum exactly to unrounded score - unrounded
baseline score, where the baseline is the tract-prior score.
"""

from collections.abc import Callable
from dataclasses import dataclass, replace
from itertools import combinations
from math import factorial

from app.actuarial import compound_model as cm
from app.actuarial.base_rates import BaseRates
from app.actuarial.constants import get as c
from app.actuarial.credibility import K, channel_weights, posterior_lcr
from app.actuarial.score_map import score_continuous
from app.models.schemas import (
    FactorContribution,
    ParcelScoreResponse,
    PrivateVerificationLayer,
    PublicHazardLayer,
)

TERRAIN_FIELDS = ("hand_rel_elev_ft", "twi_index", "slope_deg")
DOSE_GROUPS = {
    "Wildfire home hardening": ("zone0_clear", "zone1_no_shed", "ember_vents", "enclosed_eaves", "roof_class_a"),
    "Wind and hail roof": ("roof_impact_class4", "roof_fortified"),
    "Water shut-off valve": ("water_shutoff",),
}
CHANNEL_GROUPS = {
    "Verification evidence (CV, registry, sensors)": (
        "aerial_cv", "elevation_certificate", "ibhs_registry", "iot_smart_valve"
    ),
}


@dataclass(frozen=True)
class State:
    hazard: PublicHazardLayer
    doses: cm.Mitigations
    dropped_channels: frozenset[str]
    year_built: int
    firewise: bool


@dataclass(frozen=True)
class Group:
    label: str
    input_value: float | str | bool | None
    source: str
    neutralise: Callable[[State], State]


def shapley(n: int, value: Callable[[frozenset[int]], float]) -> list[float]:
    """Exact Shapley values of an n-player game with characteristic function `value`."""
    cache: dict[frozenset[int], float] = {}

    def v(s: frozenset[int]) -> float:
        if s not in cache:
            cache[s] = value(s)
        return cache[s]

    out = []
    for i in range(n):
        others = [j for j in range(n) if j != i]
        total = 0.0
        for k in range(n):
            weight = factorial(k) * factorial(n - k - 1) / factorial(n)
            for s in combinations(others, k):
                fs = frozenset(s)
                total += weight * (v(fs | {i}) - v(fs))
        out.append(total)
    return out


def _groups(
    r: ParcelScoreResponse, v: PrivateVerificationLayer, doses: cm.Mitigations, base_rates: BaseRates,
    firewise: bool,
) -> list[Group]:
    h = r.public_hazard_layer
    ref = base_rates.reference_hazard or h
    terrain_neutral = {f: getattr(ref, f) for f in TERRAIN_FIELDS}  # the tract's reference terrain, not flat ground
    groups: list[Group] = []
    if h.freeboard_delta_h_ft not in (None, 0):
        groups.append(Group(
            "Freeboard (first floor vs base flood elevation)", h.freeboard_delta_h_ft, "public hazard layer",
            lambda s: replace(s, hazard=s.hazard.model_copy(update={"freeboard_delta_h_ft": 0.0})),
        ))
    if any(getattr(h, f) != terrain_neutral[f] for f in TERRAIN_FIELDS):
        groups.append(Group(
            "Terrain vs tract reference (HAND, TWI, slope)", None, "public hazard layer",
            lambda s: replace(s, hazard=s.hazard.model_copy(update=terrain_neutral)),
        ))
    for label, names in DOSE_GROUPS.items():
        if any(getattr(doses, nm) for nm in names):
            groups.append(Group(
                label, True, "mitigation dose (verification layer)",
                lambda s, names=names: replace(s, doses=replace(s.doses, **dict.fromkeys(names, 0.0))),
            ))
    weights = channel_weights(v)
    for label, keys in CHANNEL_GROUPS.items():
        if any(weights[k] > 0 for k in keys):
            groups.append(Group(
                label, True, "credibility channel weight",
                lambda s, keys=keys: replace(s, dropped_channels=s.dropped_channels | frozenset(keys)),
            ))
    if v.cv_overhang_ft > 0 or firewise:
        groups.append(Group(
            "Wildfire site (canopy overhang, Firewise)", v.cv_overhang_ft, "verification layer, regulatory factors",
            lambda s: replace(s, doses=replace(s.doses, canopy_trim=1.0), firewise=False),
        ))
    ref_year = int(c("nri.reference_year_built"))
    if r.parcel_identity.year_built != ref_year:
        groups.append(Group(
            "Construction era", r.parcel_identity.year_built, "parcel identity",
            lambda s: replace(s, year_built=ref_year),
        ))
    return groups


def contributions(
    r: ParcelScoreResponse, v: PrivateVerificationLayer, *, base_rates: BaseRates, prior: float
) -> list[FactorContribution]:
    doses = cm.mitigations_from(v)
    firewise = r.regulatory_compliance.ca_2644_9_factors.cat_a_firewise_usa
    full_state = State(r.public_hazard_layer, doses, frozenset(), r.parcel_identity.year_built, firewise)
    weights = channel_weights(v)

    def score_of(s: State) -> float:
        terms = cm.peril_terms(
            s.hazard, v, state=r.parcel_identity.state, year_built=s.year_built, firewise=s.firewise,
            mitigations=s.doses, base_rates=base_rates,
        )
        raw = sum(t.n * t.s for t in terms)
        w = sum(0.0 if k in s.dropped_channels else x for k, x in weights.items())
        return score_continuous(posterior_lcr(raw, prior, w / (w + K)))

    groups = _groups(r, v, doses, base_rates, firewise)

    def coalition(members: frozenset[int]) -> float:
        state = full_state
        for i, g in enumerate(groups):
            if i not in members:
                state = g.neutralise(state)
        return score_of(state)

    phi = shapley(len(groups), coalition)
    neutral = coalition(frozenset())
    rows = [
        FactorContribution(factor=g.label, input_value=g.input_value, score_points=p, source=g.source)
        for g, p in zip(groups, phi, strict=True)
    ]
    rows.append(FactorContribution(
        factor="In-hazard reference home vs tract-wide average", input_value=None, score_points=neutral - score_continuous(prior),
        source="unlisted inputs (rain, fuel, own hazard layer) and lidar-only credibility; defined, not a remainder",
    ))
    rows = [x for x in rows if abs(x.score_points) >= 5e-5]
    return [x.model_copy(update={"score_points": round(x.score_points, 4)}) for x in rows]
