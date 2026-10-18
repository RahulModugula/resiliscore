#!/usr/bin/env python3
"""Evaluate NYC 2021 LAS data, keeping the application unchanged.

Use the isolated nyc2017-evaluation-requirements.txt environment. Unpack
docs/validation/nyc2021-evidence.zip into CACHE, then run with --cache CACHE.
--fetch streams two LAS tiles (~830 MB network) without saving full LAS files.
Only ground subsets and 20 m probe windows are retained temporarily. The
compact archive is sufficient for offline replay of every reported statistic.
"""
import argparse
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import ftplib
import hashlib
import io
import json
import os
from pathlib import Path
import struct
import zipfile

os.environ.setdefault("MPLCONFIGDIR", "/private/tmp/resiliscore-matplotlib-cache")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from pyproj import CRS, Transformer
import rasterio
from rasterio.io import MemoryFile
from rasterio.warp import reproject, Resampling
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs/validation"
FT = 1200 / 3937
HOST, DIRECTORY = "ftp.gis.ny.gov", "/elevation/LIDAR/NYC_2021"
TILES = ["990210.las", "990207.las"]
BOUNDS = [-73.9784, 40.7415, -73.9717, 40.7459]
PRIOR = json.loads((DOC / "nyc2017-native-evaluation.json").read_text())
PROBES = {k: v["lonLat"] for k, v in PRIOR["probes"].items()}
PROJECT = Transformer.from_crs(4326, 6539, always_xy=True)
RECORD = np.dtype({
    "names": ["X", "Y", "Z", "intensity", "returns", "flags", "classification", "user", "angle", "source", "gps"],
    "formats": ["<i4", "<i4", "<i4", "<u2", "u1", "u1", "u1", "u1", "<i2", "<u2", "<f8"],
    "offsets": [0, 4, 8, 12, 14, 15, 16, 17, 18, 20, 22], "itemsize": 30,
})


def save_json(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def xy_bounds():
    x, y = PROJECT.transform([BOUNDS[0], BOUNDS[0], BOUNDS[2], BOUNDS[2]],
                             [BOUNDS[1], BOUNDS[3], BOUNDS[1], BOUNDS[3]])
    return np.array([min(x), min(y)]), np.array([max(x), max(y)])


def decode(header):
    assert len(header) == 375 and header[:4] == b"LASF" and header[24:26] == bytes([1, 4])
    assert header[104] == 6 and struct.unpack_from("<H", header, 105)[0] == 30
    assert struct.unpack_from("<I", header, 96)[0] == 375, "Unexpected point-data offset"
    scales = np.array(struct.unpack_from("<3d", header, 131))
    offsets = np.array(struct.unpack_from("<3d", header, 155))
    assert np.isfinite(scales).all() and (scales > 0).all() and np.isfinite(offsets).all()
    return scales, offsets, struct.unpack_from("<Q", header, 247)[0]


def evlr_metadata(tail, header):
    pos, records, wkt = 0, [], None
    for _ in range(struct.unpack_from("<I", header, 243)[0]):
        h = tail[pos:pos + 60]
        assert len(h) == 60, "Truncated EVLR header"
        n = struct.unpack_from("<Q", h, 20)[0]
        body = tail[pos + 60:pos + 60 + n]
        assert len(body) == n, "Truncated EVLR body"
        user = h[2:18].decode().strip("\0 ")
        record_id = struct.unpack_from("<H", h, 18)[0]
        records.append({"user": user, "recordId": record_id, "bytes": n,
                        "description": h[28:60].decode().strip("\0 ")})
        if user == "LASF_Projection" and record_id == 2112:
            wkt = body.decode().rstrip("\0")
        pos += 60 + n
    assert pos == len(tail) and wkt is not None
    crs = CRS.from_wkt(wkt)
    assert crs.sub_crs_list[0].to_epsg() == 6539
    assert crs.sub_crs_list[1].to_epsg() == 6360 and "2018" in wkt
    return records, wkt


def stream_tile(cache, name):
    """Decode the declared point section only; trailing EVLRs are metadata."""
    low, high = xy_bounds()
    ftp = ftplib.FTP(HOST, timeout=45)
    ftp.login()
    ftp.cwd(DIRECTORY)
    ftp.voidcmd("TYPE I")
    size, mdtm = ftp.size(name), ftp.sendcmd("MDTM " + name)
    conn = ftp.transfercmd("RETR " + name)
    header = b""
    while len(header) < 375:
        chunk = conn.recv(375 - len(header))
        assert chunk, "Truncated LAS header"
        header += chunk
    scales, offsets, count = decode(header)
    (cache / (name + ".header.bin")).write_bytes(header)
    assert struct.unpack_from("<Q", header, 235)[0] == 375 + count * 30
    integer_low, integer_high = (low - offsets[:2]) / scales[:2], (high - offsets[:2]) / scales[:2]
    centres = {k: np.array(PROJECT.transform(*p)) for k, p in PROBES.items()}
    kept, probes, histogram = [], {k: [] for k in PROBES}, np.zeros(256, dtype=np.int64)

    def consume(raw):
        p = np.frombuffer(raw, dtype=RECORD)
        histogram[:] += np.bincount(p["classification"], minlength=256)
        inside = ((p["X"] >= integer_low[0]) & (p["X"] <= integer_high[0])
                  & (p["Y"] >= integer_low[1]) & (p["Y"] <= integer_high[1]))
        valid = (p["flags"] & 4) == 0
        mask = inside & valid & np.isin(p["classification"], [2, 8])
        if mask.any():
            kept.append(p[mask].copy())
        for label, centre in centres.items():
            dx = p["X"] * scales[0] + offsets[0] - centre[0]
            dy = p["Y"] * scales[1] + offsets[1] - centre[1]
            mask = inside & (dx * dx + dy * dy <= (20 / FT) ** 2)
            if mask.any():
                probes[label].append(p[mask].copy())

    sha, received, decoded, buffer = hashlib.sha256(header), 375, 0, b""
    while True:
        chunk = conn.recv(1 << 20)
        if not chunk:
            break
        sha.update(chunk)
        received += len(chunk)
        buffer += chunk
        if len(buffer) >= 4_000_000 and decoded < count:
            n = min(len(buffer) // 30, count - decoded)
            consume(buffer[:n * 30])
            buffer = buffer[n * 30:]
            decoded += n
    conn.close()
    ftp.voidresp()
    ftp.quit()
    if decoded < count:
        n = count - decoded
        assert len(buffer) >= n * 30
        consume(buffer[:n * 30])
        buffer = buffer[n * 30:]
        decoded += n
    assert decoded == count and received == size and histogram.sum() == count
    evlrs, wkt = evlr_metadata(buffer, header)
    (cache / (name + ".wkt")).write_text(wkt)
    save_json(cache / (name + ".evlr-index.json"), evlrs)
    ground = np.concatenate(kept)
    np.savez_compressed(cache / (name + ".ground.npz"), records=ground, scales=scales, offsets=offsets)
    for label, chunks in probes.items():
        if chunks:
            np.savez_compressed(cache / (name + "." + label + ".npz"),
                                records=np.concatenate(chunks), scales=scales, offsets=offsets)
    encoding = struct.unpack_from("<H", header, 6)[0]
    assert encoding & 1, "Expected adjusted standard GPS time"
    times = [float(ground["gps"].min()), float(ground["gps"].max())]
    # GPS-UTC offset was 18 seconds throughout the observed 2021 dates.
    epoch = datetime(1980, 1, 6, tzinfo=timezone.utc)
    dates = [(epoch + timedelta(seconds=t + 1e9 - 18)).isoformat() for t in times]
    assert all(d.startswith("2021-05-") for d in dates)
    entry = {"tile": name, "url": f"ftp://{HOST}{DIRECTORY}/{name}", "sizeBytes": size,
             "mdtm": mdtm, "sha256": sha.hexdigest(), "headerSha256": hashlib.sha256(header).hexdigest(),
             "pointCount": count, "classCounts": {str(k): int(v) for k, v in enumerate(histogram) if v},
             "retainedGroundAndKeyPoints": len(ground), "scales": scales.tolist(), "offsets": offsets.tolist(),
             "boundsMaxMinXYZFeet": list(struct.unpack_from("<6d", header, 179)),
             "gpsRangeInRetainedPoints": times, "globalEncoding": encoding,
             "creationDayYear": list(struct.unpack_from("<HH", header, 90)),
             "retainedGroundGPSDatesUTC": dates, "pointDataEnd": 375 + count * 30,
             "trailingBytes": len(buffer), "evlrStart": struct.unpack_from("<Q", header, 235)[0],
             "evlrCount": len(evlrs)}
    print(json.dumps({"tile": name, "streamedBytes": size, "retainedGroundAndKeyPoints": len(ground)}), flush=True)
    return entry


def load_points(path):
    with np.load(path) as d:
        a = d["records"]
        assert a.dtype == RECORD
        xyz = np.column_stack([a[k] * d["scales"][i] + d["offsets"][i]
                               for i, k in enumerate(["X", "Y", "Z"])]) * FT
        assert np.isfinite(xyz).all()
        return a, xyz


@contextmanager
def comparison_grid():
    with zipfile.ZipFile(DOC / "elevation-audit-1112075.zip") as z:
        with MemoryFile(z.read("usgs.tif")) as mem, mem.open() as grid:
            yield grid


def queries(grid):
    rows, cols = np.indices(grid.shape)
    lon, lat = rasterio.transform.xy(grid.transform, rows.ravel(), cols.ravel())
    x, y = PROJECT.transform(lon, lat)
    return np.column_stack([x, y]) * FT


def build_support(cache):
    parts, classes = [], []
    for tile in TILES:
        a, xyz = load_points(cache / (tile + ".ground.npz"))
        assert ((a["flags"] & 4) == 0).all()
        parts.append(xyz)
        classes.append(a["classification"])
    xyz, classes = np.concatenate(parts), np.concatenate(classes)
    result = {}
    with comparison_grid() as grid:
        q = queries(grid)
        for name, mask in [("groundOnly", classes == 2), ("groundAndKey", np.isin(classes, [2, 8]))]:
            ground = xyz[mask]
            distance, index = cKDTree(ground[:, :2]).query(q, workers=-1)
            result[name + "DistanceM"] = distance.reshape(grid.shape)
            result[name + "NearestZM"] = ground[index, 2].reshape(grid.shape)
    np.savez_compressed(cache / "ground-support2021.npz", **result)


def distribution(a):
    a = np.asarray(a)
    assert a.size and np.isfinite(a).all()
    return {"count": int(a.size), "percentiles_0_1_5_50_95_99_100":
            np.percentile(a, [0, 1, 5, 50, 95, 99, 100]).tolist(),
            "absolutePercentiles_50_90_95_99": np.percentile(abs(a), [50, 90, 95, 99]).tolist(),
            "absoluteOver1m": int((abs(a) > 1).sum()), "absoluteOver3m": int((abs(a) > 3).sum())}


def evaluate(cache, output):
    manifest = json.loads((cache / "stream-manifest.json").read_text())
    assert [t["tile"] for t in manifest["tiles"]] == TILES
    for t in manifest["tiles"]:
        header = (cache / (t["tile"] + ".header.bin")).read_bytes()
        assert hashlib.sha256(header).hexdigest() == t["headerSha256"]
        _, _, count = decode(header)
        assert count == t["pointCount"] == sum(t["classCounts"].values())
        assert t["evlrStart"] == t["pointDataEnd"] == 375 + count * 30
        assert t["sizeBytes"] == t["pointDataEnd"] + t["trailingBytes"]
        crs = CRS.from_wkt((cache / (t["tile"] + ".wkt")).read_text())
        assert crs.sub_crs_list[0].to_epsg() == 6539 and crs.sub_crs_list[1].to_epsg() == 6360
    support = dict(np.load(cache / "ground-support2021.npz"))
    with zipfile.ZipFile(DOC / "nyc2017-native-evidence.zip") as z:
        for name in ["ground-support.npz", "native2017-feet.tif"]:
            assert hashlib.sha256(z.read(name)).hexdigest() == PRIOR["inputSha256"][name], \
                f"2017 comparison source changed: {name}"
        prior_support = dict(np.load(io.BytesIO(z.read("ground-support.npz"))))
        with MemoryFile(z.read("native2017-feet.tif")) as mem, mem.open() as native, comparison_grid() as grid:
            prior = np.full(grid.shape, np.nan)
            reproject(native.read(1).astype(float) * FT, prior, src_transform=native.transform, src_crs=native.crs,
                      dst_transform=grid.transform, dst_crs=grid.crs, dst_nodata=np.nan, resampling=Resampling.nearest)
            q = queries(grid)
            lo, hi = xy_bounds()
            halo = min(np.min(q - lo * FT), np.min(hi * FT - q))
            result = {"date": "2026-10-18", "selectedBuildingId": "1112075",
                      "scope": "Murray Hill historical-source comparison; no application source change",
                      "matchedSamples": int(prior.size), "queryHaloM": float(halo),
                      "retainedGroundAndKeyPoints": sum(t["retainedGroundAndKeyPoints"] for t in manifest["tiles"]),
                      "sourceFilesTotalBytes": sum(t["sizeBytes"] for t in manifest["tiles"]),
                      "source": manifest, "support": {}, "probes": {},
                      "sourceDocumentation": {"path": "nyc2021-provenance.json",
                                              "sha256": digest(DOC / "nyc2021-provenance.json")},
                      "comparisonArchivesSha256": {
                          name: digest(DOC / name) for name in ["nyc2017-native-evidence.zip", "elevation-audit-1112075.zip"]},
                      "limits": [
                          "A classification difference does not establish physical ground change or independent survey accuracy.",
                          "The 2021 support grid contains nearest observed point heights, not a released or validated DEM. No unsupported interpolation is displayed as ground.",
                          "Class 8 is retained as a separate sensitivity case because the survey report validates classes 2 and 8 together.",
                          "The 2017 and 2021 point distributions use NAVD88/GEOID18; the native 2017 DEM uses GEOID12B. No geoid-realization correction was applied to the DEM comparison.",
                          "The sampled 2021 data dates from May 2021 and is not a present-day survey. Building-centre ground remains unobserved.",
                          "Public FTP access does not establish a redistribution license. No unambiguous 2021 raw-data license was found.",
                      ]}
            for name in ["groundOnly", "groundAndKey"]:
                d, h = support[name + "DistanceM"], support[name + "NearestZM"]
                assert d.shape == h.shape == grid.shape and np.isfinite(h).all()
                assert np.isfinite(d).all() and (d >= 0).all() and halo > d.max()
                both = (d <= .5) & (prior_support["distanceM"] <= .5)
                result["support"][name] = {
                    "withinM_percent": {str(r): float((d <= r).mean() * 100) for r in [.5, 1, 2, 5, 10]},
                    "maxDistanceM": float(d.max()),
                    "changeFrom2017PointCloud_bothWithinHalfMetre": distribution((h - prior_support["nearestZ"])[both]),
                    "changeFrom2017DEM_2021WithinHalfMetre": distribution((h - prior)[d <= .5])}
            assert np.all(support["groundAndKeyDistanceM"] <= support["groundOnlyDistanceM"] + 1e-9)
            for label, point in PROBES.items():
                all_records, all_xyz = [], []
                for tile in TILES:
                    file = cache / (tile + "." + label + ".npz")
                    if file.exists():
                        a, xyz = load_points(file)
                        all_records.append(a); all_xyz.append(xyz)
                records, xyz = np.concatenate(all_records), np.concatenate(all_xyz)
                centre = np.array(PROJECT.transform(*point)) * FT
                distance = np.linalg.norm(xyz[:, :2] - centre, axis=1)
                assert distance.max() <= 20.001
                valid = (records["flags"] & 4) == 0
                entry = {"lonLat": point, "native2017M": PRIOR["probes"][label]["native2017M"], "classes": {}}
                for name, classes in [("groundOnly", [2]), ("groundAndKey", [2, 8]), ("lowNoise", [7])]:
                    mask = valid & np.isin(records["classification"], classes)
                    p = {"radiiM": {}}
                    if mask.any():
                        ids = np.flatnonzero(mask); i = ids[np.argmin(distance[ids])]
                        p.update(nearestDistanceM=float(distance[i]), nearestHeightM=float(xyz[i, 2]))
                    for radius in [1, 2, 5]:
                        ids = mask & (distance <= radius); heights = xyz[ids, 2]
                        p["radiiM"][str(radius)] = {
                            "count": int(ids.sum()), "heightPercentiles_0_50_100M":
                            np.percentile(heights, [0, 50, 100]).tolist() if heights.size else None,
                            "pointSourceIds": dict(Counter(map(str, records["source"][ids])))}
                    entry["classes"][name] = p
                result["probes"][label] = entry
            b = result["probes"]["2017_depression"]["classes"]
            assert b["groundAndKey"]["radiiM"]["2"]["count"] == 0
            assert b["lowNoise"]["radiiM"]["1"]["count"] == 29
            assert b["lowNoise"]["radiiM"]["1"]["heightPercentiles_0_50_100M"][1] < -4
            assert b["groundAndKey"]["nearestHeightM"] > 6
            assert result["probes"]["selected_building"]["classes"]["groundAndKey"]["nearestDistanceM"] > 10
            result["inputSha256"] = {p.name: digest(p) for p in sorted(cache.iterdir())
                                      if p.suffix in [".npz", ".wkt", ".bin"] and not p.name.endswith(".ground.npz")}
            result["inputSha256"]["stream-manifest.json"] = digest(cache / "stream-manifest.json")
            save_json(output.with_suffix(".json"), result)
            plot(cache, output.with_suffix(".png"), grid, prior, support)
            print(json.dumps({"checks": "passed", "retainedGroundAndKeyPoints": result["retainedGroundAndKeyPoints"],
                              "matchedSamples": result["matchedSamples"], "output": str(output.with_suffix('.json'))}))


def plot(cache, path, grid, prior, support):
    fig, axes = plt.subplots(2, 3, figsize=(17, 10), layout="constrained")
    extent = [grid.bounds.left, grid.bounds.right, grid.bounds.bottom, grid.bounds.top]
    d, z = support["groundAndKeyDistanceM"], support["groundAndKeyNearestZM"]
    layers = [prior, np.where(d <= 1, z, np.nan), d]
    titles = ["Native 2017 DEM · continuous, partly interpolated",
              "2021 classes 2 + 8 · nearest point within 1 m only", "2021 distance to nearest ground/key point"]
    for i, (ax, a, title) in enumerate(zip(axes[0], layers, titles)):
        im = ax.imshow(a, extent=extent, origin="upper", interpolation="nearest",
                       cmap="terrain" if i < 2 else "magma", vmin=-5 if i < 2 else 0, vmax=12 if i < 2 else 25)
        for label, point in PROBES.items():
            ax.plot(*point, "o", color="white", markeredgecolor="black", markersize=4)
            ax.annotate({"older_usgs_pit": "A", "2017_depression": "B", "selected_building": "S"}[label],
                        point, xytext=(5, 5), textcoords="offset points", bbox={"facecolor": "white", "edgecolor": "none"})
        ax.set_aspect(1 / np.cos(np.deg2rad(40.744))); ax.set_title(title, fontsize=10)
        ax.ticklabel_format(useOffset=False, style="plain"); ax.tick_params(labelsize=7)
        fig.colorbar(im, ax=ax, label="metres", shrink=.8, extend="max" if i == 2 else "neither")
    with zipfile.ZipFile(DOC / "nyc2017-native-evidence.zip") as z:
        old_files = {"older_usgs_pit": "20170504_990210.copc-usgs_pit-returns.npz",
                     "2017_depression": "20170504_990207.copc-nys_pit-returns.npz",
                     "selected_building": "20170504_990210.copc-selected-returns.npz"}
        to_utm = Transformer.from_crs(4326, 6347, always_xy=True)
        for ax, label in zip(axes[1], PROBES):
            ux, uy = to_utm.transform(*PROBES[label])
            old = np.load(io.BytesIO(z.read(old_files[label])))
            radial = label == "selected_building"
            old_x = np.hypot(old["x"] - ux, old["y"] - uy) if radial else old["x"] - ux
            mask = (old["classification"] == 2) & (old["withheld"] == 0)
            if not radial: mask &= abs(old["y"] - uy) <= 1
            ax.scatter(old_x[mask], old["z"][mask], s=8, color="#368957", alpha=.65, label="2017 ground")
            for tile in TILES:
                file = cache / (tile + "." + label + ".npz")
                if not file.exists(): continue
                a, xyz = load_points(file)
                x, y = Transformer.from_crs(6539, 6347, always_xy=True).transform(xyz[:, 0] / FT, xyz[:, 1] / FT)
                strip = (a["flags"] & 4) == 0
                if not radial: strip &= abs(y - uy) <= 1
                plot_x = np.hypot(x - ux, y - uy) if radial else x - ux
                for classes, color, name in [([2, 8], "#275aaf", "2021 ground + key"), ([7], "#b33232", "2021 low/noise")]:
                    mask = strip & np.isin(a["classification"], classes)
                    ax.scatter(plot_x[mask], xyz[mask, 2], s=8, color=color, alpha=.65, label=name)
            # Ground-return gaps remain gaps; no TIN or filled terrain is implied.
            ax.axvline(0, color="gray", linewidth=.6); ax.set_xlim((0, 20) if radial else (-8, 8))
            ax.set_title({"older_usgs_pit": "A · newer ground supports the higher surface",
                          "2017_depression": "B · low returns remain, classification changes",
                          "selected_building": "S · no direct ground observation at centre"}[label], fontsize=10)
            ax.set_xlabel("Distance from building centre, metres" if radial else "UTM east/west distance, metres")
            ax.set_ylabel("NAVD88 elevation, metres")
            handles, labels = ax.get_legend_handles_labels()
            unique = dict(zip(labels, handles)); ax.legend(unique.values(), unique.keys(), fontsize=7)
            ax.grid(alpha=.2)
    fig.suptitle("Murray Hill · 2017 versus 2021 classified LiDAR\n"
                 "Classification affects the derived surface. Neither source certifies current ground beneath buildings.", fontsize=14)
    fig.savefig(path, dpi=160); plt.close(fig)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cache", type=Path, required=True)
    p.add_argument("--fetch", action="store_true", help="Stream ~830 MB over FTP; full LAS files are never saved")
    p.add_argument("--output", type=Path, default=DOC / "nyc2021-evaluation")
    args = p.parse_args(); args.cache.mkdir(parents=True, exist_ok=True); args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.fetch:
        lo, hi = xy_bounds()
        tiles = [stream_tile(args.cache, name) for name in TILES]
        save_json(args.cache / "stream-manifest.json", {"boundsLngLat": BOUNDS,
                  "boundsStatePlaneFeet": [lo.tolist(), hi.tolist()], "tiles": tiles})
        build_support(args.cache)
        for name in TILES:
            (args.cache / (name + ".ground.npz")).unlink()
    elif (args.cache / "sha256.json").exists():
        for name, expected in json.loads((args.cache / "sha256.json").read_text()).items():
            assert Path(name).name == name and digest(args.cache / name) == expected, f"Evidence checksum mismatch: {name}"
    evaluate(args.cache, args.output)


if __name__ == "__main__":
    main()
