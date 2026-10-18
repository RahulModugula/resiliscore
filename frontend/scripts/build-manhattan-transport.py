#!/usr/bin/env python3
"""Build the bounded tunnel-crossing decks from NYC's 2022 Polygon Z data.

Use the existing manhattan-dem-requirements.txt environment. --fetch requests
only this small extent. For offline replay, unpack the committed evidence ZIP
into --cache. Ground rasters and building observations are never modified.
"""
import argparse
import hashlib
import json
from pathlib import Path
import urllib.parse
import urllib.request
import zipfile

from pyproj import Transformer

ROOT = Path(__file__).resolve().parents[2]
BASE = "https://services6.arcgis.com/yG5s3afENB5iO9fj/ArcGIS/rest/services/"
RULES = "https://raw.githubusercontent.com/CityOfNewYork/nyc-planimetrics/main/Capture_Rules.md"
LAYERS = [("Transport_Structure_2022", 25), ("Elevation_2022", 6)]
EXTENT = [-73.976, 40.745, -73.9727, 40.7474]
ASSOCIATIONS = {12230000009: ["79426:0", "79430:0"],
                12230000010: ["2208:0", "2207:0", "2114:0", "2113:0"]}
FT = 1200 / 3937


def save(path, data):
    path.write_text(json.dumps(data, separators=(",", ":"), allow_nan=False) + "\n")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cache", type=Path, required=True)
    p.add_argument("--fetch", action="store_true")
    args = p.parse_args(); args.cache.mkdir(parents=True, exist_ok=True)
    if args.fetch:
        for name, layer in LAYERS:
            service = BASE + name + "/FeatureServer/" + str(layer)
            params = dict(f="json", where="1=1", geometry=",".join(map(str, EXTENT)),
                          geometryType="esriGeometryEnvelope", inSR=4326, outSR=2263,
                          spatialRel="esriSpatialRelIntersects", outFields="*", returnGeometry="true",
                          returnZ="true", resultRecordCount=2000)
            url = service + "/query?" + urllib.parse.urlencode(params)
            with urllib.request.urlopen(service + "?f=json", timeout=40) as r: metadata = json.load(r)
            with urllib.request.urlopen(url, timeout=40) as r: response = json.load(r)
            save(args.cache / (name + "-2ave.json"), dict(url=url, metadata=metadata, response=response))
        with urllib.request.urlopen(RULES, timeout=40) as r:
            (args.cache / "Capture_Rules.md").write_bytes(r.read())
    rules = (args.cache / "Capture_Rules.md").read_text()
    assert "The vertical datum for all features is NAVD88" in rules and "NAD83, US foot" in rules
    records = [json.loads((args.cache / (name + "-2ave.json")).read_text()) for name, _ in LAYERS]
    for record in records:
        assert record["metadata"]["hasZ"] is True
        assert record["response"]["spatialReference"]["latestWkid"] == 2263
        assert not record["response"].get("exceededTransferLimit") and "error" not in record["response"]
    project = Transformer.from_crs(2263, 4326, always_xy=True)
    decks = []
    for feature in records[0]["response"]["features"]:
        a = feature["attributes"]
        # Portal polygons (2310) do not define a road deck or a tunnel interior.
        if a["FEATURE_CODE"] not in [2300, 2350]: continue
        assert a["SOURCE_ID"] in ASSOCIATIONS
        rings = [[[*(project.transform(v[0], v[1])), v[2] * FT] for v in ring]
                 for ring in feature["geometry"]["rings"]]
        assert all(len(ring) >= 4 and ring[0] == ring[-1] for ring in rings)
        points = [v for ring in rings for v in ring]
        bounds = [min(v[0] for v in points), min(v[1] for v in points), max(v[0] for v in points), max(v[1] for v in points)]
        decks.append(dict(id=str(a["OBJECTID"]), sourceId=str(a["SOURCE_ID"]), status=a["STATUS"],
                          streetIds=ASSOCIATIONS[a["SOURCE_ID"]], bounds=bounds, rings=rings))
    assert len(decks) == 2
    bundle = dict(version=1, horizontalCrs="EPSG:4326", verticalDatum="NAVD88", elevationUnit="metre",
                  source="NYC 2022 planimetric release, Transport Structure Polygon Z; unchanged historical features",
                  sourceUrl=BASE + "Transport_Structure_2022/FeatureServer/25", captureRulesUrl=RULES,
                  queryBounds=EXTENT, sourceVerticalUnit="US survey foot", conversionToMetres=FT, decks=decks)
    target = ROOT / "frontend/public/manhattan/context/transport-decks.json"
    save(target, bundle)
    archive = ROOT / "docs/validation/2ave-transport-evidence.zip"
    names = [name + "-2ave.json" for name, _ in LAYERS] + ["Capture_Rules.md"]
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
        for name in names: z.write(args.cache / name, name)
    print(json.dumps(dict(decks=len(decks), bundleBytes=target.stat().st_size,
                          sha256=hashlib.sha256(target.read_bytes()).hexdigest(), evidenceBytes=archive.stat().st_size)))


if __name__ == "__main__": main()
