"""Input provenance for the v2 contract: where each scoring input came from.

LIVE means a live request or a caller-supplied value, DEFAULT a hard-coded fallback, UNAVAILABLE no value,
and REFERENCE_PARCEL a value borrowed from the nearest reference (golden) parcel. The raster layers are lookup
tables keyed to the reference parcels, so they are REFERENCE_PARCEL even though they carry real dataset names.
"""

from app.models.schemas import InputProvenance, ParcelScoreResponse, PrivateVerificationLayer

# hazard field -> (dataset key in dataset_vintages, display name, live-flag key or None)
_HAZARD = {
    "fema_flood_zone": ("FEMA_NFHL", "FEMA NFHL", None),
    "bfe_ft_navd88": ("FEMA_NFHL", "FEMA NFHL", None),
    "usgs_lag_ft": ("USGS_3DEP", "USGS 3DEP EPQS", "usgs_3dep"),
    "est_ffe_ft": ("USGS_3DEP", "USGS 3DEP EPQS", "usgs_3dep"),
    "freeboard_delta_h_ft": ("USGS_3DEP", "USGS 3DEP EPQS", "usgs_3dep"),
    "hand_rel_elev_ft": ("USGS_HAND", "USGS HAND", None),
    "twi_index": ("USGS_3DEP", "USGS 3DEP derived TWI", None),
    "noaa_atlas15_p24h_100yr_in": ("NOAA_PFDS", "NOAA Atlas 15", None),
    "atlas15_cmip6_mult": ("NOAA_PFDS", "NOAA Atlas 15 CMIP6 multiplier", None),
    "landfire_fbfm40_code": ("LANDFIRE", "LANDFIRE FBFM40", None),
    "slope_deg": ("LANDFIRE", "LANDFIRE slope", None),
    "wui_class": ("CAL_FIRE_FHSZ", "WUI classification", None),
    "openfema_tract_claim_count": ("OpenFEMA", "OpenFEMA NFIP claims (context only, not scored)", "openfema"),
    "openfema_tract_mean_lcr": ("OpenFEMA", "OpenFEMA NFIP claims (context only, not scored)", "openfema"),
}


NRI_VINTAGE = "v1.20 (December 2025)"


def _entry(field: str, source: str, name: str, vintage: str | None) -> InputProvenance:
    return InputProvenance(field=field, value_source=source, source_name=name, vintage=vintage)


def build(
    r: ParcelScoreResponse,
    flags: dict[str, str] | None = None,
    *,
    rcv_supplied: bool = False,
    year_supplied: bool = False,
) -> list[InputProvenance]:
    """Provenance rows for a response. `flags` are the ingestion engine's live/cache flags; without them
    (the golden reference parcels) every input is REFERENCE_PARCEL."""
    vintages = r.regulatory_compliance.dataset_vintages
    flags = flags or {}
    rows = []
    for field, (key, name, flag) in _HAZARD.items():
        live = flag is not None and flags.get(flag) == "live"
        source = "UNAVAILABLE" if getattr(r.public_hazard_layer, field) is None else "LIVE" if live else "REFERENCE_PARCEL"
        rows.append(_entry(f"public_hazard_layer.{field}", source, name, vintages.get(key)))
    for field in PrivateVerificationLayer.model_fields:
        rows.append(_entry(
            f"private_verification_layer.{field}", "REFERENCE_PARCEL", "Reference parcel verification record", None
        ))
    rows.append(_entry(
        "parcel_identity.rcv_usd", "LIVE" if rcv_supplied else "DEFAULT",
        "caller-supplied" if rcv_supplied else "nearest reference parcel", None,
    ))
    rows.append(_entry(
        "parcel_identity.year_built", "LIVE" if year_supplied else "DEFAULT",
        "caller-supplied" if year_supplied else "nearest reference parcel", None,
    ))
    nri = "FEMA National Risk Index building loss rates (reference tract for this golden parcel)"
    for field, what in (
        ("actuarial_breakdown.tract_prior_lcr", "tract-wide sum of NRI building loss rates"),
        ("actuarial_breakdown.base_rates", "per-peril exposed-building loss rates behind the frequency intercepts"),
    ):
        rows.append(_entry(field, "REFERENCE_PARCEL", f"{nri}: {what}", NRI_VINTAGE))
    return rows


def is_indicative(rows: list[InputProvenance]) -> bool:
    """A score is indicative only unless every scoring input is LIVE."""
    return any(row.value_source != "LIVE" for row in rows)
