#!/usr/bin/env python3
"""Build the bounded Murray Hill 2021 terrain prototype from classified points.

--fetch streams two source LAS files without saving full files. Reuse the
isolated nyc2017-evaluation-requirements.txt environment. The support limits
are prototype parameters, not a survey accuracy specification.
"""
import argparse
import hashlib
import json
from pathlib import Path
import runpy

import numpy as np
from pyproj import Transformer
import rasterio
from rasterio.transform import from_bounds
from scipy.spatial import Delaunay, cKDTree

ROOT = Path(__file__).resolve().parents[2]
EVAL = runpy.run_path(str(Path(__file__).with_name("evaluate-nyc2021-terrain.py")))
FT = 1200 / 3937
MAX_EDGE_M, MAX_RADIUS_M, MAX_NEAREST_M = 10.0, 5.0, 3.0
NODATA = np.float32(-3.4028234663852886e38)
DATA = ROOT / "frontend/public/manhattan/prototypes"


def ground_points(records, scales, offsets):
    valid = np.isin(records["classification"], [2, 8]) & ((records["flags"] & 4) == 0)
    r = records[valid]
    return np.column_stack([r[k] * scales[i] + offsets[i] for i, k in enumerate(["X", "Y", "Z"])]) * FT


def interpolate(points, query):
    """Return a TIN value only inside a small, nearby, fully supported triangle."""
    query = np.atleast_2d(query)
    result = np.full(len(query), np.nan)
    distance = np.full(len(query), np.inf)
    if len(points) < 3:
        return result, distance
    # Coincident XY returns retain the observed upper median, never a synthetic mean.
    points = points[np.lexsort((points[:, 2], points[:, 1], points[:, 0]))]
    xy, start, counts = np.unique(points[:, :2], axis=0, return_index=True, return_counts=True)
    points = points[start + counts // 2]
    if len(points) < 3 or np.linalg.matrix_rank(xy - xy[0]) < 2:
        return result, distance
    triangulation = Delaunay(xy)
    simplex = triangulation.find_simplex(query)
    distance[:] = cKDTree(xy).query(query)[0]
    ids = np.flatnonzero((simplex >= 0) & (distance <= MAX_NEAREST_M))
    vertices = triangulation.simplices[simplex[ids]]
    triangles = xy[vertices]
    edges = np.linalg.norm(triangles - np.roll(triangles, 1, axis=1), axis=2)
    a, b = triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0]
    double_area = abs(a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0])
    radius = np.divide(np.prod(edges, axis=1), 2 * double_area,
                       out=np.full(len(ids), np.inf), where=double_area > 1e-12)
    valid = (edges.max(axis=1) <= MAX_EDGE_M) & (radius <= MAX_RADIUS_M)
    ids, vertices = ids[valid], vertices[valid]
    transform = triangulation.transform[simplex[ids]]
    bary = np.einsum("ijk,ik->ij", transform[:, :2], query[ids] - transform[:, 2])
    weights = np.column_stack([bary, 1 - bary.sum(axis=1)])
    result[ids] = np.sum(weights * points[vertices, 2], axis=1)
    return result, distance


def build(cache, output=DATA):
    source_files = json.loads((cache / "stream-manifest.json").read_text())["tiles"]
    evaluated = json.loads((ROOT / "docs/validation/nyc2021-evaluation.json").read_text())["source"]["tiles"]
    assert {f["tile"]: f["sha256"] for f in source_files} == {f["tile"]: f["sha256"] for f in evaluated}, "Source LAS files differ from the evaluated survey"
    crop_files = [cache / (tile + ".ground.npz") for tile in EVAL["TILES"]]
    if not all(p.exists() for p in crop_files):
        raise ValueError("Ground crops are missing; use --fetch to stream the two source tiles")
    chunks = []
    for path in crop_files:
        with np.load(path) as d:
            chunks.append(ground_points(d["records"], d["scales"], d["offsets"]))
    points = np.concatenate(chunks)
    prior = json.loads((ROOT / "docs/validation/nyc2017-native-evaluation.json").read_text())
    height, width = prior["matchedGridShape"]
    extent = prior["matchedExtent"]
    affine = from_bounds(*extent, width, height)
    rows, cols = np.indices((height, width))
    lon, lat = rasterio.transform.xy(affine, rows.ravel(), cols.ravel())
    project = Transformer.from_crs(4326, 6539, always_xy=True)
    x, y = project.transform(lon, lat)
    query = np.column_stack([x, y]) * FT
    elevations, distances = np.full(height * width, np.nan), np.full(height * width, np.inf)
    # A 10m halo contains all points capable of affecting an accepted triangle
    # with circumradius <=5m. Bounded patches avoid a city-scale triangulation.
    for row in range(0, height, 64):
        for col in range(0, width, 64):
            ids = (rows >= row) & (rows < row + 64) & (cols >= col) & (cols < col + 64)
            indices = np.flatnonzero(ids)
            q = query[indices]
            low, high = q.min(axis=0) - 10.01, q.max(axis=0) + 10.01
            mask = ((points[:, :2] >= low) & (points[:, :2] <= high)).all(axis=1)
            elevations[indices], distances[indices] = interpolate(points[mask], q)
    valid = np.isfinite(elevations)
    assert valid.any() and (distances[valid] <= MAX_NEAREST_M).all()
    raster = np.where(valid, elevations, NODATA).astype("float32").reshape(height, width)
    output.mkdir(parents=True, exist_ok=True)
    tif = output / "nyc2021-murray-hill.tif"
    with rasterio.open(tif, "w", driver="GTiff", width=width, height=height, count=1,
                       dtype="float32", crs="EPSG:4326+5703", transform=affine, nodata=float(NODATA),
                       compress="deflate", predictor=3) as dst:
        dst.write(raster, 1)
        dst.set_band_unit(1, "metre")
    bounds = [affine.c + affine.a / 2, affine.f + affine.e * (height - .5),
              affine.c + affine.a * (width - .5), affine.f + affine.e / 2]
    manifest = {
        "version": 1, "dataset": "NYC_2021_PROTOTYPE", "buildingId": "1112075",
        "rasterUrl": "/manhattan/prototypes/nyc2021-murray-hill.tif",
        "sha256": hashlib.sha256(tif.read_bytes()).hexdigest(),
        "width": width, "height": height, "bounds": bounds,
        "horizontalCrs": "EPSG:4326", "verticalDatum": "NAVD88", "geoid": "GEOID18",
        "elevationUnit": "metre", "nominalSpacingM": 1,
        "collectionDates": ["2021-05-12", "2021-05-21"],
        "source": "NYC 2021 classified LiDAR; prototype TIN from ground and model-key points; metres NAVD88/GEOID18",
        "interpolation": {"method": "linear-TIN", "classes": [2, 8], "excludeWithheld": True,
                          "maxTriangleEdgeM": MAX_EDGE_M, "maxCircumradiusM": MAX_RADIUS_M,
                          "maxNearestPointM": MAX_NEAREST_M, "outsideSupport": "NoData",
                          "coincidentXY": "observed upper median height"},
        "coverage": {"supportedCells": int(valid.sum()), "totalCells": len(valid),
                     "supportedPercent": float(valid.mean() * 100)},
        "limits": ["Experimental historical terrain, not surveyed current ground or first-floor elevation.",
                   "Short gaps are interpolated. Unsupported ground remains unknown.",
                   "Support thresholds are prototype parameters, not an accuracy specification."],
    }
    EVAL["save_json"](output / "nyc2021-murray-hill.json", manifest)
    report = {"manifest": manifest, "retainedGroundPoints": len(points), "rasterBytes": tif.stat().st_size,
              "probes": {}, "sourceFiles": source_files}
    for label, location in EVAL["PROBES"].items():
        q = np.array(project.transform(*location)) * FT
        mask = (abs(points[:, :2] - q) <= 20).all(axis=1)
        z, d = interpolate(points[mask], q)
        report["probes"][label] = {"lonLat": location, "prototypeTINHeightM": float(z[0]) if np.isfinite(z[0]) else None,
                                   "nearestGroundDistanceM": float(d[0])}
    report["scratchBytesBeforeCleanup"] = sum(p.stat().st_size for p in cache.iterdir() if p.is_file())
    EVAL["save_json"](ROOT / "docs/validation/nyc2021-prototype.json", report)
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cache", type=Path, required=True)
    p.add_argument("--fetch", action="store_true")
    args = p.parse_args(); args.cache.mkdir(parents=True, exist_ok=True)
    if args.fetch:
        lo, hi = EVAL["xy_bounds"]()
        entries = [EVAL["stream_tile"](args.cache, tile) for tile in EVAL["TILES"]]
        EVAL["save_json"](args.cache / "stream-manifest.json", {"boundsLngLat": EVAL["BOUNDS"],
                          "boundsStatePlaneFeet": [lo.tolist(), hi.tolist()], "tiles": entries})
    result = build(args.cache)
    for tile in EVAL["TILES"]:
        (args.cache / (tile + ".ground.npz")).unlink()
    print(json.dumps({"coverage": result["manifest"]["coverage"], "rasterBytes": result["rasterBytes"],
                      "scratchBytesBeforeCleanup": result["scratchBytesBeforeCleanup"], "probes": result["probes"]}))


if __name__ == "__main__":
    main()
