"""Defensible-space rings around a building footprint (SPEC Prompt 1B, lines 122-128)."""

from functools import lru_cache

import numpy as np
import shapely
from pyproj import Transformer
from shapely.geometry import Polygon, mapping
from shapely.geometry.base import BaseGeometry

FT_TO_M = 0.3048
SQM_TO_SQFT = 1 / FT_TO_M**2

# (contract kind, label, inner ft, outer ft): 10 CCR 2644.9 / PRC 4291 zones.
ZONES = (
    ("zone_0_ring_0_5ft", "Zone 0 (0-5 ft)", 0, 5),
    ("zone_1_ring_5_30ft", "Zone 1 (5-30 ft)", 5, 30),
    ("zone_2_ring_30_100ft", "Zone 2 (30-100 ft)", 30, 100),
)


@lru_cache(maxsize=2)
def _transformer(src: str, dst: str) -> Transformer:
    return Transformer.from_crs(src, dst, always_xy=True)


def _reproject(geom: BaseGeometry, transformer: Transformer) -> BaseGeometry:
    return shapely.transform(geom, lambda xy: np.column_stack(transformer.transform(xy[:, 0], xy[:, 1])))


def to_metres(geom: BaseGeometry) -> BaseGeometry:
    """Project a WGS84 (lng, lat) geometry to EPSG:5070 (equal-area, metres)."""
    return _reproject(geom, _transformer("EPSG:4326", "EPSG:5070"))


def to_lnglat(geom: BaseGeometry) -> BaseGeometry:
    """Project an EPSG:5070 geometry back to WGS84 (lng, lat)."""
    return _reproject(geom, _transformer("EPSG:5070", "EPSG:4326"))


def _buffer_ft(footprint_m: BaseGeometry, feet: float) -> BaseGeometry:
    # Mitre joins keep square corners, matching the golden ring geometry.
    return footprint_m.buffer(feet * FT_TO_M, join_style="mitre")


def _round_coords(coords: list, ndigits: int = 7) -> list:
    return [_round_coords(c, ndigits) if isinstance(c[0], (list, tuple)) else [round(v, ndigits) for v in c]
            for c in coords]


def build_rings(footprint_lnglat: list[list[float]]) -> dict:
    """Return a GeoJSON FeatureCollection of the three rings; `properties.kind` follows the contract."""
    footprint_m = to_metres(Polygon(footprint_lnglat))
    if footprint_m.is_empty or not footprint_m.is_valid:
        raise ValueError("footprint must be a valid, non-empty polygon")
    features = []
    for kind, label, inner_ft, outer_ft in ZONES:
        inner = footprint_m if inner_ft == 0 else _buffer_ft(footprint_m, inner_ft)
        ring = to_lnglat(_buffer_ft(footprint_m, outer_ft).difference(inner))
        geometry = mapping(ring)
        geometry["coordinates"] = _round_coords(geometry["coordinates"])
        features.append(
            {"type": "Feature", "geometry": geometry, "properties": {"kind": kind, "label": label}}
        )
    return {"type": "FeatureCollection", "features": features}
