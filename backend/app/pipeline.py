"""Score a parcel that is not one of the golden demo addresses (SPEC Prompt 1D, item 1).

Federal layers come from SpatialIngestionEngine, rings and verification from the vision package, and the
score from actuarial.optimizer.simulate, so there is one scoring path. Hazard inputs are live or a marked
national default (see `input_provenance`); nothing is borrowed from a golden parcel unless the request is the
demo parcel itself. Fields with no source for an arbitrary address (RCV, year built) take a documented default
unless the caller sets them, and are marked DEFAULT. The base response is only a template that `simulate`
recomputes.
"""

import hashlib

from shapely.geometry import Point, box

from app import http
from app.ingestion import rasters
from app.ingestion.engine import PIN_RADIUS_M, HazardResult, SpatialIngestionEngine
from app.ingestion.geocode import Geocode
from app.models.schemas import (
    Ca26449Factors,
    HitlStatus,
    InputProvenance,
    ParcelIdentity,
    ParcelScoreResponse,
    RegulatoryCompliance,
)
from app.vision.cv_inspector import AerialCVInspector
from app.vision.footprints import fetch_footprint
from app.vision.parcel_rings import FT_TO_M, build_rings, to_lnglat, to_metres

DEFAULT_FOOTPRINT_FT = (40.0, 30.0)  # assessor footprint is unknown without a parcel feed: a typical house
DEFAULT_RCV_USD = 350_000.0  # no valuation source: a national-median-order replacement cost, marked DEFAULT
DEFAULT_YEAR_BUILT = 1990


def default_footprint(lat: float, lng: float) -> list[list[float]]:
    """Closed WGS84 ring for a house-sized rectangle centred on the point."""
    p = to_metres(Point(lng, lat))
    half_x, half_y = (d * FT_TO_M / 2 for d in DEFAULT_FOOTPRINT_FT)
    rect = to_lnglat(box(p.x - half_x, p.y - half_y, p.x + half_x, p.y + half_y))
    return [list(c) for c in rect.exterior.coords]


def synthetic_apn(address: str) -> str:
    """Stable 14-digit id for an address with no assessor record."""
    return str(int(hashlib.sha256(address.strip().casefold().encode()).hexdigest(), 16) % 10**14).zfill(14)


def _caller_or_default(name: str, given: float | None, default: float, what: str) -> tuple[float, InputProvenance]:
    if given is not None:
        return given, InputProvenance(field=name, value_source="LIVE", source_name="Caller supplied", vintage=None)
    return default, InputProvenance(field=name, value_source="DEFAULT", source_name=what, vintage=None)


async def build_parcel_for_address(
    address: str,
    *,
    footprint: list[list[float]] | None = None,
    rcv_usd: float | None = None,
    year_built: int | None = None,
) -> ParcelScoreResponse:
    """An address alone is enough: the Census Geocoder supplies the point and FIPS codes."""
    g: Geocode = await SpatialIngestionEngine().geocode(address)
    return await build_parcel(
        address, g.lat, g.lng, g.county_fips, g.state, tract_fips=g.tract_fips,
        footprint=footprint, rcv_usd=rcv_usd, year_built=year_built,
    )  # fmt: skip


async def build_parcel(
    address: str,
    lat: float,
    lng: float,
    county_fips: str,
    state: str,
    *,
    tract_fips: str | None = None,
    footprint: list[list[float]] | None = None,
    rcv_usd: float | None = None,
    year_built: int | None = None,
) -> ParcelScoreResponse:
    """Assemble an unscored response for the point; the caller runs `simulate` on it."""
    site = rasters.nearest_site(lat, lng, county_fips)
    template = site.response
    result: HazardResult = await SpatialIngestionEngine().fetch(address, lat, lng, county_fips, state, tract_fips)
    pinned = rasters.distance_m(lat, lng, site.lat, site.lng) <= PIN_RADIUS_M
    shared = http.get_client()
    if footprint:
        ring = footprint
        footprint_prov = InputProvenance(
            field="footprint", value_source="LIVE", source_name="Caller supplied", vintage=None
        )
    else:
        ring, footprint_prov = await fetch_footprint(lat, lng, shared)
    # Only the demo parcel may hit the golden verification; any other apn gets the UNVERIFIED zero-confidence layer.
    apn = template.parcel_identity.apn_uid if pinned else synthetic_apn(address)
    inspection = await AerialCVInspector().ainspect(apn, ring, None, client=shared)
    verification, detections = inspection.layer, inspection.detections
    features = [
        {
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [ring]},
            "properties": {"kind": "building_footprint", "label": "Building footprint"},
        },
        *build_rings(ring)["features"],
        *detections["features"],
    ]
    rcv, rcv_prov = _caller_or_default("rcv_usd", rcv_usd, DEFAULT_RCV_USD, "National default replacement cost")
    built, built_prov = _caller_or_default("year_built", year_built, DEFAULT_YEAR_BUILT, "National default year built")
    identity = ParcelIdentity.model_validate(
        {
            "apn_uid": synthetic_apn(address),
            "address": address,
            "county_fips": county_fips,
            "state": state,
            # No H3 library is installed: another parcel's cells would be wrong, so only the demo parcel has them.
            "h3_res11": template.parcel_identity.h3_res11 if pinned else "",
            "h3_res13": template.parcel_identity.h3_res13 if pinned else "",
            "rcv_usd": template.parcel_identity.rcv_usd if pinned and rcv_usd is None else rcv,
            "year_built": template.parcel_identity.year_built if pinned and year_built is None else int(built),
            "centroid": [lng, lat],
            "geometries": {"type": "FeatureCollection", "features": features},
        }
    )
    prior = result.tract_prior_lcr if result.tract_prior_lcr is not None else template.actuarial_breakdown.tract_prior_lcr
    return template.model_copy(
        update={
            "parcel_identity": identity,
            "public_hazard_layer": result.layer,
            "private_verification_layer": verification,
            "actuarial_breakdown": template.actuarial_breakdown.model_copy(update={"tract_prior_lcr": prior}),
            "prescriptive_mitigations": [],
            "hitl_status": HitlStatus(
                escalated=False, trigger_code="NONE", trigger_reason=None, recommended_underwriter_action=None
            ),
            "regulatory_compliance": RegulatoryCompliance(
                monotonicity_verified=False,
                ny_dfs_cl7_ecdis_free=True,
                ca_2644_9_factors=Ca26449Factors(**dict.fromkeys(Ca26449Factors.model_fields, False)),
                dataset_vintages=result.vintages,
            ),
            "input_provenance": (
                result.provenance if pinned else [*result.provenance, rcv_prov, built_prov]
            )
            + [footprint_prov, *inspection.provenance],
            "indicative_only": result.indicative_only
            or any(p.value_source != "LIVE" for p in (footprint_prov, *inspection.provenance)),
        }
    )
