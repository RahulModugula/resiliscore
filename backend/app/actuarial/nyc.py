"""NYC pluvial and sewer-backup perils, and the basement terms that also modify the mapped-zone flood peril.

These perils are relativities. Their level comes from the FEMA NRI inland-flood rate for the tract (base_rates.py):
the engine solves each intercept so that a reference NYC home (partial basement, nuisance-class ponding in every
DEP scenario, citywide-average 311 sewer-backup density, no mitigation) matches its share of the tract rate. A parcel
moves away from that home through its DEP flood class, basement, 311 and FloodNet history, catch basins and
retrofits. Nothing here is fitted to a demo score; priors are marked validated: false in constants.py.

Pluvial. DEP publishes ponding classes per rainfall scenario (1.77, 2.13 and 3.66 in/hr). Each scenario's rate is
mapped to an annual exceedance probability through the NOAA Atlas 14 60-minute intensity table (log-linear in the
recurrence interval). With D_j the damage ratio in scenario j and p_j its exceedance probability (p_1 > p_2 > p_3),
the annual expected damage is  D_1 (p_1 - p_2) + D_2 (p_2 - p_3) + D_3 p_3  (each scenario's damage applied to the
events between it and the next rarer one, the conservative-low reading of the ladder).

Damage. First floor: the Hazus 129 curve once ponding reaches it. Basement: water fills a share of the basement per
foot of ponding at grade, and the damage is the Hazus 129 curve at the water depth above the basement floor, scaled
by basement size and finish and added to the first-floor damage. The basement choice follows a leave-one-event-out
test on NFIP basement claims (docs/validation/nyc_basement.md): the structure-plus-finish curves lost to Hazus 129.
"""

from dataclasses import dataclass

import numpy as np

from app.actuarial.constants import get as c
from app.models.schemas import DepStormwater, NycLayer

BASEMENT_KINDS = ("FULL", "PARTIAL", "NONE")
NYC_PERILS = ("PLUVIAL", "SEWER_BACKUP")
WINDOW_YEARS = 5  # the 311 and FloodNet counts cover five years
UNITS_PER_DENSITY = 1000  # 311 density is reports per 1,000 residential units per year


@dataclass(frozen=True)
class NycDoses:
    """Retrofit doses in [0, 1]; the Mitigations dataclass carries the same fields."""

    backwater_valve: float = 0.0
    sump_pump_battery: float = 0.0
    flood_vents: float = 0.0
    dry_floodproofing: float = 0.0
    elevated_mechanicals: float = 0.0
    cellar_reversal: float = 0.0


def basement_kind(layer: NycLayer) -> tuple[str, bool]:
    """(FULL | PARTIAL | NONE, defaulted). A missing or unrecognised type takes the registered default."""
    raw = (layer.basement_type or "").strip().upper()
    if raw in BASEMENT_KINDS:
        return raw, False
    return str(c("nyc.basement_unknown_default")), True


def reference_layer() -> NycLayer:
    """The reference NYC home the intercepts are solved on: tract-typical basement, nuisance ponding in every
    scenario, citywide-average sewer-backup density and catch basins, no FloodNet history, not in the Sandy zone."""
    units = int(c("nyc.res_units_500m_default"))
    density = c("nyc.sewer.ref_density_per_1000_units_yr")
    return NycLayer(
        bbl="reference", basement_type=str(c("nyc.reference_basement")),
        dep_stormwater=[DepStormwater(scenario=f"{rate} in/hr", flood_class="NUISANCE") for rate in _scenario_rates()],
        sewer_backup_311_500m_5y=round(density * units / UNITS_PER_DENSITY * WINDOW_YEARS),
        catch_basins_150m=int(c("nyc.sewer.catch_basin_reference")), residential_units_500m=units,
        floodnet_events_500m_5y=0, dob_cellar_conversion_flag=False, sandy_inundated=False,
    )


def _scenario_rates() -> list[float]:
    return sorted(c("nyc.dep_scenario_rate_in_hr").values())


def annual_exceedance(rate_in_hr: float) -> float:
    """Annual exceedance probability of a 60-minute rainfall intensity (NOAA Atlas 14 table, log-linear in ARI)."""
    ari = np.array(c("nyc.pfds_60min_ari_years"), dtype=float)
    intensity = np.array(c("nyc.pfds_60min_intensity_in_hr"), dtype=float)
    return float(1.0 / np.exp(np.interp(rate_in_hr, intensity, np.log(ari))))


def _rate_of(scenario: str) -> float | None:
    """DEP scenario label -> its rainfall rate (in/hr): the number in the label, else Limited/Moderate/Extreme."""
    text = scenario.lower()
    rates = c("nyc.dep_scenario_rate_in_hr")
    for rate in rates.values():
        if f"{rate:.2f}" in text:
            return float(rate)
    for name, rate in rates.items():
        if name.lower() in text:
            return float(rate)
    return None


def _class_depth_ft(flood_class: str) -> float:
    text = flood_class.lower()
    depths = c("nyc.dep_class_depth_ft")
    if "deep" in text:
        return float(depths["DEEP_CONTIGUOUS"])
    if "nuisance" in text:
        return float(depths["NUISANCE"])
    return 0.0


def scenario_ladder(layer: NycLayer) -> list[tuple[float, float]]:
    """[(annual exceedance, ponding depth in ft)] for the DEP scenarios, most frequent first. A scenario the
    parcel is not mapped in has depth 0. Where two scenarios share a rate (the two Moderate maps), the deeper wins."""
    depth_by_rate = dict.fromkeys(_scenario_rates(), 0.0)
    for row in layer.dep_stormwater:
        rate = _rate_of(row.scenario)
        if rate is not None:
            depth_by_rate[rate] = max(depth_by_rate[rate], _class_depth_ft(row.flood_class))
    return [(annual_exceedance(rate), depth) for rate, depth in depth_by_rate.items()]


def finish_multiplier(layer: NycLayer, doses: NycDoses) -> float:
    """Relativity for an occupied (DOB-flagged) cellar conversion over an unconverted basement; reversing the
    conversion moves a flagged cellar to the unconverted level."""
    m = c("nyc.finish_multiplier")
    if layer.dob_cellar_conversion_flag:
        return float(m["converted"] - (m["converted"] - c("nyc.cellar_reversal_multiplier")) * doses.cellar_reversal)
    return float(m["unconverted"])


def mechanicals_cut(doses: NycDoses) -> float:
    """Share of the loss avoided by elevating the boiler, water heater and electrical service."""
    return float(c("nyc.sev_reduction")["elevated_mechanicals"]) * doses.elevated_mechanicals


def first_floor_damage(depth_above_first_floor_ft: float) -> float:
    """Hazus RES1 one-story curve once water reaches the first floor; nothing below it. The curve's sub-floor
    damage reflects foundation types, and interpolating across its step at 0 ft would invent damage."""
    from app.actuarial import compound_model as cm

    return 0.0 if depth_above_first_floor_ft < 0 else cm.ddf(depth_above_first_floor_ft)


def basement_damage(water_above_floor_ft: float, kind: str, layer: NycLayer, doses: NycDoses) -> float:
    """Basement-only building damage (share of RCV): the Hazus 129 curve at the water depth above the basement
    floor, scaled by the basement's size and finish. Leave-one-event-out on NFIP basement claims kept Hazus 129
    unscaled over every structure-curve-plus-finish alternative (docs/validation/nyc_basement.md). Water is capped
    at the basement depth; above it the first-floor curve takes over. It is added to the first-floor damage, so a
    home with a basement never scores below the same home without one."""
    from app.actuarial import compound_model as cm

    if kind == "NONE" or water_above_floor_ft <= 0:
        return 0.0
    water = min(water_above_floor_ft, float(c("nyc.basement_depth_ft")[kind]))
    return (
        float(c("nyc.basement_scale")) * float(c("nyc.basement_kind_scale")[kind]) * cm.ddf(water)
        * finish_multiplier(layer, doses)
    )


def pluvial_damage(depth_at_grade_ft: float, kind: str, layer: NycLayer, doses: NycDoses) -> float:
    """Damage ratio for ponding of this depth at street grade."""
    d = max(0.0, depth_at_grade_ft - float(c("nyc.dry_floodproof_depth_ft")) * doses.dry_floodproofing)
    if d <= 0:
        return 0.0
    ground = first_floor_damage(d - float(c("nyc.first_floor_above_grade_ft")))
    below = 0.0
    if kind != "NONE":
        depth = float(c("nyc.basement_depth_ft")[kind])
        water = depth * min(1.0, float(c("nyc.basement_entry_per_ft")) * d)
        water *= 1.0 - c("nyc.sev_reduction")["sump_pump_battery"] * doses.sump_pump_battery
        below = basement_damage(water, kind, layer, doses)
    return min(1.0, (ground + below) * (1.0 - mechanicals_cut(doses)))


def pluvial_rate(layer: NycLayer, doses: NycDoses) -> tuple[float, float]:
    """(n_raw, severity) before the NRI level: n_raw is the exceedance probability of the first scenario that
    floods the lot (times the FloodNet history relativity) and severity makes n_raw * severity the annual expected
    damage from the ladder."""
    kind, _ = basement_kind(layer)
    ladder = scenario_ladder(layer)
    probs = [p for p, _ in ladder] + [0.0]
    damages = [pluvial_damage(d, kind, layer, doses) for _, d in ladder]
    expected = sum(dm * (probs[j] - probs[j + 1]) for j, dm in enumerate(damages))
    first = next((probs[j] for j, dm in enumerate(damages) if dm > 0), 0.0)
    if first <= 0 or expected <= 0:
        return 0.0, 0.0
    events = min(layer.floodnet_events_500m_5y or 0, int(c("nyc.floodnet_event_cap")))
    rel = float(np.exp(c("nyc.floodnet_log_per_event") * events))
    return first * rel, expected / first


def _units(layer: NycLayer) -> float:
    return float(layer.residential_units_500m or c("nyc.res_units_500m_default"))


def sewer_density_relativity(layer: NycLayer) -> float:
    """311 sewer-backup reports per 1,000 residential units per year, relative to the citywide level, raised to the
    elasticity and clamped; times the catch-basin covariate (more basins within 150 m, fewer backups)."""
    count = layer.sewer_backup_311_500m_5y
    if count is None:
        return 1.0
    density = (count / WINDOW_YEARS) / (_units(layer) / UNITS_PER_DENSITY)
    lo, hi = c("nyc.sewer.relativity_clamp")
    rel = min(hi, max(lo, (density / c("nyc.sewer.ref_density_per_1000_units_yr")) ** c("nyc.sewer.density_elasticity")))
    if layer.catch_basins_150m is not None:
        rel *= float(np.exp(c("nyc.sewer.catch_basin_coeff") * (layer.catch_basins_150m - c("nyc.sewer.catch_basin_reference"))))
    return rel


def sewer_rate(layer: NycLayer, doses: NycDoses) -> tuple[float, float]:
    """(n_raw, severity): relativity for the density and catch basins, cut by a backwater valve; severity is the
    basement damage from a few inches of sewage (a floor-drain loss without a basement)."""
    kind, _ = basement_kind(layer)
    sev = c("nyc.sewer.severity")
    if kind == "NONE":
        severity = float(sev["no_basement"])
    else:
        severity = basement_damage(float(sev["water_depth_ft"]), kind, layer, doses)
    severity *= 1.0 - c("nyc.sev_reduction")["elevated_mechanicals"] * doses.elevated_mechanicals
    n = sewer_density_relativity(layer) * (1.0 - c("nyc.freq_reduction")["backwater_valve"] * doses.backwater_valve)
    return n, severity


def data_missing(layer: NycLayer) -> bool:
    """True when the basement type is unknown or DEP data is absent, so the NYC bands widen and the score is
    indicative only."""
    return basement_kind(layer)[1] or not layer.dep_stormwater
