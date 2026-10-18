#!/usr/bin/env python3
"""Evaluate historical NYC terrain without modifying the application's data.

Install nyc2017-evaluation-requirements.txt in a separate Python environment.
Unpack docs/validation/nyc2017-native-evidence.zip into CACHE, then run:
  python frontend/scripts/evaluate-nyc2017-terrain.py --cache CACHE
Use --fetch to reacquire the native raster window and full-resolution COPC
returns. Downloads remain in CACHE; only small spatial subsets are requested.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import zipfile

os.environ.setdefault("MPLCONFIGDIR", "/private/tmp/resiliscore-matplotlib-cache")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from pyproj import Transformer
import rasterio
from rasterio.warp import reproject, Resampling, transform_bounds
from rasterio.windows import from_bounds

ROOT = Path(__file__).resolve().parents[2]
VALIDATION = ROOT / "docs/validation"
BASE = "https://noaa-nos-coastal-lidar-pds.s3.amazonaws.com/"
RASTER = BASE + "dem/NYC_topobathy_BE_DEM_2017_9307/be_NYC_025.tif"
TILES = ["20170504_990210.copc", "20170504_990207.copc"]
BOUNDS = [-73.9779, 40.7419, -73.9722, 40.7456]
GROUND_BOUNDS = [-73.9784, 40.7415, -73.9717, 40.7459]
FT_TO_M = 1200 / 3937  # Exact US survey foot, for horizontal AND vertical units.
PROBES = {
    "older_usgs_pit": [-73.97249300533004, 40.74487191784359],
    "2017_depression": [-73.97495797901215, 40.7425999087431],
    "selected_building": [-73.9754964, 40.7439658],
}
PROBE_FILES = {
    "older_usgs_pit": "20170504_990210.copc-usgs_pit-returns.npz",
    "2017_depression": "20170504_990207.copc-nys_pit-returns.npz",
    "selected_building": "20170504_990210.copc-selected-returns.npz",
}


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def fetch(cache):
    """Read the original raster's native cells and class-2, non-withheld points."""
    import laspy
    from laspy.copc import Bounds
    from scipy.spatial import cKDTree

    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", GDAL_HTTP_TIMEOUT="45",
                      CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif"):
        with rasterio.open(RASTER) as src:
            assert src.units == ("US survey foot",), "Unexpected source elevation unit"
            window = from_bounds(*transform_bounds(4326, src.crs, *BOUNDS, densify_pts=21),
                                 transform=src.transform).round_offsets().round_lengths()
            data = src.read(1, window=window)
            profile = src.profile
            profile.update(width=data.shape[1], height=data.shape[0],
                           transform=src.window_transform(window))
            with rasterio.open(cache / "native2017-feet.tif", "w", **profile) as dst:
                dst.write(data, 1)
                dst.set_band_unit(1, src.units[0])

    project = Transformer.from_crs(4326, 6347, always_xy=True)
    xs, ys = project.transform([GROUND_BOUNDS[0], GROUND_BOUNDS[0], GROUND_BOUNDS[2], GROUND_BOUNDS[2]],
                               [GROUND_BOUNDS[1], GROUND_BOUNDS[3], GROUND_BOUNDS[1], GROUND_BOUNDS[3]])
    bounds = Bounds(np.array([min(xs), min(ys)]), np.array([max(xs), max(ys)]))
    manifest, ground_parts = [], []
    for tile in TILES:
        url = BASE + f"laz/geoid18/9306/{tile}.laz"
        with laspy.CopcReader.open(url, http_num_threads=4) as reader:
            crs = reader.header.parse_crs()
            assert crs.sub_crs_list[0].to_epsg() == 6347, "Unexpected point-cloud CRS"
            assert crs.sub_crs_list[1].to_epsg() == 5703, "Unexpected point-cloud height datum"
            points = reader.query(bounds=bounds)  # No resolution/LOD downsampling.
            cls = np.asarray(points.classification)
            valid = np.asarray(points.withheld) == 0
            xyz = np.column_stack([points.x, points.y, points.z])
            ground_parts.append(xyz[(cls == 2) & valid])
            classes, counts = np.unique(cls, return_counts=True)
            manifest.append({"id": tile, "url": url, "crs": str(crs),
                             "classCounts": dict(zip(map(str, classes), map(int, counts))),
                             "groundPoints": int(((cls == 2) & valid).sum()),
                             "withheld": int((~valid).sum())})
            for label, point in PROBES.items():
                if not PROBE_FILES[label].startswith(tile):
                    continue
                centre = np.array(project.transform(*point))
                radius = 12 if label == "selected_building" else 8
                mask = ((xyz[:, :2] - centre) ** 2).sum(axis=1) <= radius ** 2
                np.savez_compressed(cache / PROBE_FILES[label], x=xyz[mask, 0], y=xyz[mask, 1],
                                    z=xyz[mask, 2], classification=cls[mask],
                                    withheld=np.array(points.withheld)[mask],
                                    source=np.array(points.point_source_id)[mask])
    ground = np.concatenate(ground_parts)
    with rasterio.open(cache / "usgs.tif") as grid:
        rows, cols = np.indices(grid.shape)
        lon, lat = rasterio.transform.xy(grid.transform, rows.ravel(), cols.ravel())
        x, y = project.transform(lon, lat)
        distance, index = cKDTree(ground[:, :2]).query(np.column_stack([x, y]), workers=-1)
        np.savez_compressed(cache / "ground-support.npz", distanceM=distance.reshape(grid.shape),
                            nearestZ=ground[index, 2].reshape(grid.shape))
    write_json(cache / "ground-manifest.json", {"queryBoundsUTM": {
        "min": bounds.mins.tolist(), "max": bounds.maxs.tolist()}, "tiles": manifest})


def stats(values):
    v = values[np.isfinite(values)]
    assert v.size > 0
    return {"count": int(v.size), "percentiles_0_1_5_50_95_99_100":
            np.percentile(v, [0, 1, 5, 50, 95, 99, 100]).tolist(),
            "absolutePercentiles_50_90_95_99": np.percentile(abs(v), [50, 90, 95, 99]).tolist(),
            "absoluteOver1m": int((abs(v) > 1).sum()),
            "absoluteOver3m": int((abs(v) > 3).sum())}


def evaluate(cache, output):
    with rasterio.open(cache / "native2017-feet.tif") as native, \
            rasterio.open(cache / "usgs.tif") as old, \
            rasterio.open(cache / "nys2017.tif") as nys:
        assert native.crs.to_epsg() == 6539
        assert native.res == (1.0, 1.0) and native.units == ("US survey foot",)
        assert old.crs.to_epsg() == nys.crs.to_epsg() == 4326
        assert old.shape == nys.shape and old.transform == nys.transform
        feet = native.read(1).astype(np.float64)
        assert np.isfinite(feet).all() and (feet != native.nodata).all()
        metres = feet * FT_TO_M
        matched = np.full(old.shape, np.nan)
        reproject(metres, matched, src_transform=native.transform, src_crs=native.crs,
                  dst_transform=old.transform, dst_crs=old.crs, dst_nodata=np.nan,
                  resampling=Resampling.nearest)
        assert np.isfinite(matched).all(), "Incomplete native coverage"
        usgs, service = old.read(1), nys.read(1)
        support = np.load(cache / "ground-support.npz")
        distance, nearest = support["distanceM"], support["nearestZ"]
        assert distance.shape == nearest.shape == old.shape
        assert np.isfinite(distance).all() and (distance >= 0).all()
        assert np.isfinite(nearest).all()
        close = distance <= .5
        native_delta = stats((matched - nearest)[close])
        # Same-acquisition consistency checks, not independent accuracy tests.
        assert native_delta["absolutePercentiles_50_90_95_99"][0] < .1
        assert abs(np.median(matched - service)) < .1
        manifest = json.loads((cache / "ground-manifest.json").read_text())
        rows, cols = np.indices(old.shape)
        lon, lat = rasterio.transform.xy(old.transform, rows.ravel(), cols.ravel())
        x, y = Transformer.from_crs(4326, 6347, always_xy=True).transform(lon, lat)
        query = manifest["queryBoundsUTM"]
        halo = min(np.min(x) - query["min"][0], np.min(y) - query["min"][1],
                   query["max"][0] - np.max(x), query["max"][1] - np.max(y))
        assert halo > distance.max(), "Expand query halo to avoid truncated nearest-ground distances"
        results = {
            "date": "2026-10-18", "selectedBuildingId": "1112075",
            "scope": "One Murray Hill block; historical source evaluation, not current ground certification",
            "assessment": "Preferred historical terrain candidate; conditional adoption, not a validated present-day ground replacement",
            "limits": [
                "The 2017 DEM and 2017 classified points share an acquisition. Their agreement is an internal consistency check, not independent accuracy.",
                "Ground-class returns can represent real lower surfaces or classification errors. No current survey or imagery establishes today's surface at the disputed probes.",
                "DEM metadata specifies GEOID12B; the NOAA point-cloud distribution specifies GEOID18. Both are NAVD88, but no geoid-realization correction was applied. Centimetre residuals are not an absolute accuracy claim.",
                "Nearest-neighbour reprojection, finite pixel spacing, registration and real vertical boundaries affect the largest residuals.",
                "Ground-support percentages describe all matched cells, including building interiors. A nearby return alone does not prove a cell's height is correct.",
                "No smoothing, depression filling, source switching, or application rendering changes were applied.",
            ],
            "nativeUrl": RASTER, "nativeCRS": str(native.crs),
            "nativePixelSpacingM": FT_TO_M, "nativeCropShape": list(native.shape),
            "nativeCropRangeM": [float(metres.min()), float(metres.max())],
            "verticalConversion": "NAVD88 US survey feet multiplied by exactly 1200/3937",
            "matchedGridShape": list(old.shape), "matchedSamples": int(matched.size),
            "matchedExtent": list(old.bounds),
            "nativeMinusUSGS": stats(matched - usgs),
            "nativeMinusNYS2017Service": stats(matched - service),
            "groundPointsQueried": sum(t["groundPoints"] for t in manifest["tiles"]),
            "minimumGroundQueryHaloM": float(halo),
            "groundSupportWithinM_percent": {str(r): float((distance <= r).mean() * 100)
                                             for r in [.5, 1, 2, 5, 10]},
            "groundDistancePercentiles_0_50_90_95_99_100M":
                np.percentile(distance, [0, 50, 90, 95, 99, 100]).tolist(),
            "sameAcquisitionNearestGroundConsistency_withinHalfMetre": {
                "native2017": native_delta, "usgs2013_14": stats((usgs - nearest)[close]),
                "nys2017Service": stats((service - nearest)[close])},
            "probes": {},
        }
        to_native = Transformer.from_crs(4326, native.crs, always_xy=True)
        to_ground = Transformer.from_crs(4326, 6347, always_xy=True)
        for label, lonlat in PROBES.items():
            record = np.load(cache / PROBE_FILES[label])
            centre = np.array(to_ground.transform(*lonlat))
            points = np.column_stack([record["x"], record["y"]])
            d = np.linalg.norm(points - centre, axis=1)
            ground = (record["classification"] == 2) & (record["withheld"] == 0)
            rows, cols = old.index(*lonlat)
            p = {"lonLat": lonlat,
                 "native2017M": float(next(native.sample([to_native.transform(*lonlat)]))[0]) * FT_TO_M,
                 "usgsM": float(usgs[rows, cols]), "nys2017ServiceM": float(service[rows, cols]),
                 "nearbyGround": {}}
            for radius in [1, 2, 5]:
                mask = ground & (d <= radius)
                z = record["z"][mask]
                sources, counts = np.unique(record["source"][mask], return_counts=True)
                p["nearbyGround"][str(radius)] = {
                    "count": int(mask.sum()), "rangeM": [float(z.min()), float(z.max())] if z.size else None,
                    "sourceIds": dict(zip(map(str, sources), map(int, counts)))}
            assert np.any(ground), "Probe window does not contain ground support"
            indices = np.flatnonzero(ground)
            i = indices[np.argmin(d[indices])]
            p["nearestGroundDistanceM"] = float(d[i])
            p["nearestGroundHeightM"] = float(record["z"][i])
            results["probes"][label] = p

        overview = json.loads((ROOT / "frontend/public/manhattan/overview.json").read_text())
        nearby = [b for b in overview["buildings"] if BOUNDS[0] <= b["center"][0] <= BOUNDS[2]
                  and BOUNDS[1] <= b["center"][1] <= BOUNDS[3]]
        selected = next(b for b in nearby if b["id"] == "1112075")
        perimeter = np.array([to_native.transform(*q) for q in selected["footprint"][0]])
        points = []
        for a, b in zip(perimeter[:-1], perimeter[1:]):
            points.extend(a + (b - a) * f for f in np.linspace(0, 1, max(2, int(np.linalg.norm(b - a)))))
        z = np.array([v[0] for v in native.sample(points)], dtype=float) * FT_TO_M
        results["selectedBuildingPerimeter"] = {"samples": len(z), "rangeM": [float(z.min()), float(z.max())],
                                                 "sourceHeightM": selected["heightM"]}
        # All probe locations must be the same retained source pixels, not hand-adjusted fixtures.
        assert results["probes"]["2017_depression"]["native2017M"] < -4
        assert results["probes"]["2017_depression"]["nearbyGround"]["1"]["count"] >= 40
        assert results["probes"]["older_usgs_pit"]["native2017M"] > 2
        assert results["probes"]["selected_building"]["nearbyGround"]["5"]["count"] == 0
        results["inputSha256"] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                  for p in sorted(cache.iterdir()) if p.name in {
                                      "native2017-feet.tif", "usgs.tif", "nys2017.tif", "ground-support.npz",
                                      "ground-manifest.json", *PROBE_FILES.values()}}
        write_json(output.with_suffix(".json"), results)
        plot(output.with_suffix(".png"), old, matched, usgs, distance, nearby, cache)
        print(json.dumps({"checks": "passed", "groundPoints": results["groundPointsQueried"],
                          "matchedSamples": results["matchedSamples"],
                          "output": str(output.with_suffix('.json'))}))


def plot(path, grid, native, old, distance, buildings, cache):
    fig, axes = plt.subplots(2, 3, figsize=(17, 10), layout="constrained")
    extent = [grid.bounds.left, grid.bounds.right, grid.bounds.bottom, grid.bounds.top]
    layers = [old, native, native - old, distance]
    titles = ["USGS 2013–14 · current source", "Native NYC 2017 · nearest sample at matched grid",
              "2017 minus 2013–14 · historical difference", "Distance to nearest 2017 class-2 return"]
    for i, (ax, a, title) in enumerate(zip(axes.ravel(), layers, titles)):
        kw = {"vmin": -5, "vmax": 12, "cmap": "terrain"} if i < 2 else (
            {"vmin": -11, "vmax": 11, "cmap": "RdBu_r"} if i == 2 else
            {"vmin": 0, "vmax": 20, "cmap": "magma"})
        im = ax.imshow(a, extent=extent, origin="upper", interpolation="nearest", **kw)
        for b in buildings:
            for ring in b["footprint"]:
                x, y = np.array(ring).T
                ax.plot(x, y, color="black", linewidth=.35, alpha=.55)
        for label, point in PROBES.items():
            marker = {"older_usgs_pit": "A", "2017_depression": "B", "selected_building": "S"}[label]
            ax.plot(*point, "o", color="white", markersize=4, markeredgecolor="black")
            ax.annotate(marker, point, xytext=(5, 5), textcoords="offset points", fontsize=10,
                        bbox={"facecolor": "white", "alpha": .85, "edgecolor": "none", "pad": 1})
        ax.set_xlim(extent[:2]); ax.set_ylim(extent[2:])
        ax.set_aspect(1 / np.cos(np.deg2rad(40.744)))
        ax.set_title(title, fontsize=11)
        ax.ticklabel_format(useOffset=False, style="plain")
        ax.tick_params(labelsize=7)
        fig.colorbar(im, ax=ax, label="metres", shrink=.8)
    for ax, label in zip(axes.ravel()[4:], ["older_usgs_pit", "2017_depression"]):
        record = np.load(cache / PROBE_FILES[label])
        x, y = Transformer.from_crs(4326, 6347, always_xy=True).transform(*PROBES[label])
        mask = ((record["classification"] == 2) & (record["withheld"] == 0)
                & (abs(record["y"] - y) <= 1.0))
        ax.scatter(record["x"][mask] - x, record["z"][mask], s=5, c="#236b49", alpha=.7,
                   label="Class-2 returns within ±1m north/south")
        offsets = np.linspace(-8, 8, 321)
        lon, lat = Transformer.from_crs(6347, 4326, always_xy=True).transform(x + offsets, y + offsets * 0)
        to_native = Transformer.from_crs(4326, 6539, always_xy=True)
        nx, ny = to_native.transform(lon, lat)
        with rasterio.open(cache / "native2017-feet.tif") as n:
            h = np.array([v[0] for v in n.sample(zip(nx, ny))]) * FT_TO_M
        with rasterio.open(cache / "usgs.tif") as u:
            z = np.array([v[0] for v in u.sample(zip(lon, lat))])
        ax.plot(offsets, z, color="#b2601b", label="USGS 2013–14", linewidth=1.5)
        ax.plot(offsets, h, color="#204d96", label="Native NYC 2017", linewidth=1.5)
        ax.axvline(0, color="gray", linewidth=.6)
        ax.set_title("A · older USGS pit" if label == "older_usgs_pit" else "B · low returns present in 2017", fontsize=11)
        ax.set_xlabel("East/west distance from probe, metres")
        ax.set_ylabel("NAVD88 elevation, metres")
        ax.legend(fontsize=7, loc="best")
        ax.grid(alpha=.2)
    fig.suptitle("Murray Hill terrain source evaluation · building 1112075\n"
                 "A and B are disputed samples; S is the selected building. Historical consistency is not current accuracy.",
                 fontsize=14)
    fig.savefig(path, dpi=160)
    plt.close(fig)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--output", type=Path, default=VALIDATION / "nyc2017-native-evaluation")
    args = parser.parse_args()
    args.cache.mkdir(parents=True, exist_ok=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Original service responses are retained with their exact grids and checksums.
    with zipfile.ZipFile(VALIDATION / "elevation-audit-1112075.zip") as archive:
        for name in ["usgs.tif", "nys2017.tif"]:
            if not (args.cache / name).exists():
                (args.cache / name).write_bytes(archive.read(name))
    earlier = json.loads((VALIDATION / "elevation-audit.json").read_text())["matchedBlockComparison"]
    for name, source in [("usgs.tif", "usgs"), ("nys2017.tif", "nys2017")]:
        assert hashlib.sha256((args.cache / name).read_bytes()).hexdigest() == earlier[source]["sha256"], \
            f"Original comparison input changed: {name}"
    if args.fetch:
        fetch(args.cache)
    elif (args.cache / "sha256.json").exists():
        for name, expected in json.loads((args.cache / "sha256.json").read_text()).items():
            assert Path(name).name == name, "Evidence manifest must contain flat filenames"
            assert hashlib.sha256((args.cache / name).read_bytes()).hexdigest() == expected, \
                f"Evidence input checksum mismatch: {name}"
    evaluate(args.cache, args.output)
