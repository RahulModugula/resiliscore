"""Score a parcel that is not one of the golden demo addresses (SPEC Prompt 1D, item 1).

Federal layers come from SpatialIngestionEngine, rings and verification from the vision package, and the
score from actuarial.optimizer.simulate, so there is one scoring path. Where no live signal exists the
ingestion and vision packages serve their nearest-golden-site fallback, and so does this module:
h3 cells, RCV, year built and base premium default to that nearest site's values unless the caller sets them.
"""

import hashlib

from shapely.geometry import Point, box

from app.ingestion import rasters
from app.ingestion.engine import SpatialIngestionEngine
from app.models.schemas import (
    Ca26449Factors,
    HitlStatus,
    ParcelIdentity,
    ParcelScoreResponse,
    RegulatoryCompliance,
)
from app.vision.cv_inspector import AerialCVInspector
from app.vision.parcel_rings import FT_TO_M, build_rings, to_lnglat, to_metres

DEFAULT_FOOTPRINT_FT = (40.0, 30.0)  # assessor footprint is unknown without a parcel feed: a typical house


def default_footprint(lat: float, lng: float) -> list[list[float]]:
    """Closed WGS84 ring for a house-sized rectangle centred on the point."""
    p = to_metres(Point(lng, lat))
    half_x, half_y = (d * FT_TO_M / 2 for d in DEFAULT_FOOTPRINT_FT)
    rect = to_lnglat(box(p.x - half_x, p.y - half_y, p.x + half_x, p.y + half_y))
    return [list(c) for c in rect.exterior.coords]


def synthetic_apn(address: str) -> str:
    """Stable 14-digit id for an address with no assessor record."""
    return str(int(hashlib.sha256(address.strip().casefold().encode()).hexdigest(), 16) % 10**14).zfill(14)


async def build_parcel(
    address: str,
    lat: float,
    lng: float,
    county_fips: str,
    state: str,
    *,
    footprint: list[list[float]] | None = None,
    rcv_usd: float | None = None,
    year_built: int | None = None,
) -> ParcelScoreResponse:
    """Assemble an unscored response for the point; the caller runs `simulate` on it."""
    site = rasters.nearest_site(lat, lng, county_fips).response
    hazard, vintages, flags = await SpatialIngestionEngine().fetch(address, lat, lng, county_fips, state)
    ring = footprint or default_footprint(lat, lng)
    verification, detections = AerialCVInspector().inspect(site.parcel_identity.apn_uid, ring, None)
    features = [
        {
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [ring]},
            "properties": {"kind": "building_footprint", "label": "Building footprint"},
        },
        *build_rings(ring)["features"],
        *detections["features"],
    ]
    identity = ParcelIdentity.model_validate(
        {
            "apn_uid": synthetic_apn(address),
            "address": address,
            "county_fips": county_fips,
            "state": state,
            "h3_res11": site.parcel_identity.h3_res11,
            "h3_res13": site.parcel_identity.h3_res13,
            "rcv_usd": rcv_usd if rcv_usd is not None else site.parcel_identity.rcv_usd,
            "year_built": year_built if year_built is not None else site.parcel_identity.year_built,
            "centroid": [lng, lat],
            "geometries": {"type": "FeatureCollection", "features": features},
        }
    )
    prior = hazard.openfema_tract_mean_lcr if flags["openfema"] == "live" else site.actuarial_breakdown.tract_prior_lcr
    return site.model_copy(
        update={
            "parcel_identity": identity,
            "public_hazard_layer": hazard,
            "private_verification_layer": verification,
            "actuarial_breakdown": site.actuarial_breakdown.model_copy(update={"tract_prior_lcr": prior}),
            "prescriptive_mitigations": [],
            "hitl_status": HitlStatus(
                escalated=False, trigger_code="NONE", trigger_reason=None, recommended_underwriter_action=None
            ),
            "regulatory_compliance": RegulatoryCompliance(
                monotonicity_verified=False,
                ny_dfs_cl7_ecdis_free=True,
                ca_2644_9_factors=Ca26449Factors(**dict.fromkeys(Ca26449Factors.model_fields, False)),
                dataset_vintages=vintages,
            ),
        }
    )
