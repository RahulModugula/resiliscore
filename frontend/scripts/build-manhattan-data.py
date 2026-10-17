#!/usr/bin/env python3
"""Download NYC public basemap data and cache a standalone Manhattan map.

Requires scripts/manhattan-dem-requirements.txt for the USGS DEM stage.
Source snapshots cache outside Git. Existing
snapshots are reused; use --refresh to retrieve a new snapshot.
"""
import argparse
import datetime
import hashlib
import json
import runpy
import math
from pathlib import Path
import time
import urllib.parse
import urllib.request
from xml.etree import ElementTree

BASE = 'https://data.cityofnewyork.us/resource/'
FEET_TO_METERS = 0.3048


def polygons(geometry):
    return [geometry['coordinates']] if geometry['type'] == 'Polygon' else geometry['coordinates']


def bounds(geometry):
    points = [point for polygon in polygons(geometry) for ring in polygon for point in ring]
    return [min(p[0] for p in points), min(p[1] for p in points), max(p[0] for p in points), max(p[1] for p in points)]


def center(bb):
    return [(bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2]


def inside_ring(point, ring):
    inside = False
    lng, lat = point
    for i, (xi, yi) in enumerate(ring):
        xj, yj = ring[i - 1]
        if (yi > lat) != (yj > lat) and lng < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            inside = not inside
    return inside


def contains(point, geometry):
    return any(inside_ring(point, polygon[0]) and not any(inside_ring(point, hole) for hole in polygon[1:]) for polygon in polygons(geometry))


def in_bounds(point, bb):
    return bb[0] <= point[0] <= bb[2] and bb[1] <= point[1] <= bb[3]


def overlap(a, b):
    return a[0] <= b[2] and a[2] >= b[0] and a[1] <= b[3] and a[3] >= b[1]


def rounded(value):
    if isinstance(value, list):
        return [rounded(item) for item in value]
    if isinstance(value, float):
        return round(value, 7)
    return value


def geometry(value):
    return {'type': value['type'], 'coordinates': rounded(value['coordinates'])}


def number(value, positive=False):
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(result) or (positive and result <= 0):
        return None
    return result


def fetch(dataset, where, order, cache, refresh):
    target = cache / (dataset + '.json')
    if target.exists() and not refresh:
        return json.loads(target.read_text())
    records = []
    offset = 0
    while True:
        params = urllib.parse.urlencode({'$where': where, '$order': order, '$limit': 10000, '$offset': offset})
        url = BASE + dataset + '.json?' + params
        for attempt in range(4):
            try:
                with urllib.request.urlopen(url, timeout=120) as response:
                    page = json.load(response)
                break
            except Exception:
                if attempt == 3:
                    raise
                time.sleep(2 ** attempt)
        records.extend(page)
        print(dataset, len(records), flush=True)
        if len(page) < 10000:
            break
        offset += len(page)
    target.write_text(json.dumps(records, separators=(',', ':')))
    return records


def write(path, data):
    path.write_text(json.dumps(data, separators=(',', ':'), ensure_ascii=False) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', type=Path, default=Path('/tmp/resiliscore-manhattan-sources'))
    parser.add_argument('--refresh', action='store_true')
    parser.add_argument('--dem-cache', type=Path, default=Path('/tmp/resiliscore-manhattan-dem'))
    args = parser.parse_args()
    args.cache.mkdir(parents=True, exist_ok=True)
    output = Path(__file__).resolve().parent.parent / 'public' / 'manhattan'
    (output / 'neighborhoods').mkdir(parents=True, exist_ok=True)
    ntas = fetch('9nt8-h7nd', "borocode='1'", 'nta2020', args.cache, args.refresh)
    footprints = fetch('5zhs-2jue', "(bin >= 1000000 AND bin < 2000000) OR base_bbl like '1%'", 'doitt_id', args.cache, args.refresh)
    properties = fetch('enfh-gkve', "borough='M' AND retired=false", 'gisobjid', args.cache, args.refresh)
    catch_basins = fetch('2w2g-fk3i', 'longitude > -74.06 AND longitude < -73.90 AND latitude > 40.68 AND latitude < 40.89', 'unitid', args.cache, args.refresh)
    neighborhoods = []
    for nta in ntas:
        geom = geometry(nta['the_geom'])
        bb = bounds(geom)
        neighborhoods.append({'id': nta['nta2020'], 'name': nta['ntaname'], 'geometry': geom, 'center': rounded(center(bb)), 'bounds': rounded(bb), 'type': nta['ntatype']})
    buildings = []
    unassigned = 0
    skipped_placeholders = 0
    for record in footprints:
        if record.get('feature_code') == '1003':
            skipped_placeholders += 1
            continue
        for part, polygon in enumerate(polygons(record['the_geom'])):
            poly_geom = {'type': 'Polygon', 'coordinates': polygon}
            position = center(bounds(poly_geom))
            candidates = [n for n in neighborhoods if in_bounds(position, n['bounds'])]
            neighborhood = next((n for n in candidates if contains(position, n['geometry'])), None)
            if neighborhood is None:
                # Border footprints can have bounding-box centres offshore. Try an actual exterior vertex.
                neighborhood = next((n for n in neighborhoods if any(in_bounds(p, n['bounds']) and contains(p, n['geometry']) for p in polygon[0][::max(1, len(polygon[0]) // 8)])), None)
            if neighborhood is None:
                unassigned += 1
                continue
            roof = number(record.get('height_roof'), positive=True)
            ground = number(record.get('ground_elevation'))
            # Dataset zero grounds are ambiguous missing values, retained unknown for inland buildings.
            if ground == 0:
                ground = None
            year = number(record.get('construction_year'), positive=True)
            bin_value = record.get('bin')
            if bin_value == '1000000':
                bin_value = None
            buildings.append({'id': str(record['doitt_id']) + (f'-{part}' if part else ''), 'bin': bin_value, 'bbl': record.get('base_bbl'), 'address': record.get('address'), 'name': record.get('name'), 'center': rounded(position), 'footprint': rounded(polygon), 'heightM': round(roof * FEET_TO_METERS, 2) if roof is not None else None, 'groundElevationM': round(ground * FEET_TO_METERS, 2) if ground is not None else None, 'neighborhoodId': neighborhood['id'], 'yearBuilt': int(year) if year is not None else None, 'featureCode': record.get('feature_code', '')})
    parks = [{'id': str(p.get('gisobjid') or p.get('globalid') or p['objectid']), 'name': p.get('signname') or p.get('name311') or 'NYC Parks property', 'geometry': geometry(p['multipolygon'])} for p in properties if p.get('multipolygon')]
    drains = []
    for record in catch_basins:
        position = record['the_geom']['coordinates']
        neighborhood = next((n for n in neighborhoods if in_bounds(position, n['bounds']) and contains(position, n['geometry'])), None)
        if neighborhood:
            drains.append({'id': record['unitid'], 'position': rounded(position), 'depthM': None, 'neighborhoodId': neighborhood['id']})
    kml_path = args.cache / 'interceptors_force_mains.kml'
    if args.refresh or not kml_path.exists():
        with urllib.request.urlopen('https://drive.google.com/uc?export=download&id=195COqssN1bjxwf87RZhq4IEFUKlBLx0u', timeout=120) as response:
            kml_path.write_bytes(response.read())
    kml = ElementTree.parse(kml_path)
    namespace = {'k': 'http://www.opengis.net/kml/2.2'}
    sewer_lines = []
    for index, placemark in enumerate(kml.findall('.//k:Placemark', namespace)):
        attrs = {item.attrib['name']: item.text for item in placemark.findall('.//k:SimpleData', namespace)}
        for part, line in enumerate(placemark.findall('.//k:LineString/k:coordinates', namespace)):
            coordinates = [[float(v) for v in point.split(',')[:2]] for point in line.text.split()]
            bb = [min(p[0] for p in coordinates), min(p[1] for p in coordinates), max(p[0] for p in coordinates), max(p[1] for p in coordinates)]
            if not any(overlap(bb, n['bounds']) for n in neighborhoods):
                continue
            sewer_lines.append({'id': 'osa-' + str(attrs.get('cartodb_id', index)) + '-' + str(part), 'coordinates': rounded(coordinates), 'depthM': None, 'type': attrs.get('type')})
    def line_bounds(line):
        points = line['coordinates']
        return [min(p[0] for p in points), min(p[1] for p in points), max(p[0] for p in points), max(p[1] for p in points)]
    def infrastructure(selected, bb=None):
        lines = [line for line in sewer_lines if bb is None or overlap(line_bounds(line), bb)]
        return {'stormDrains': [{'id': d['id'], 'position': d['position'], 'depthM': None} for d in selected], 'sewerLines': lines, 'sewerAvailability': 'partial', 'sewerStatus': 'Open Sewer Atlas NYC historic illustrative interceptors and force mains. Unofficial, incomplete and not for planning. All depths and catch-basin connectivity are unknown.'}
    def pending_terrain(bb):
        return {'bounds': bb, 'width': 2, 'height': 2, 'elevationsM': [None] * 4, 'source': 'Pending measured USGS 3DEP DEM rebuild'}
    details = {}
    for neighborhood in neighborhoods:
        ident = neighborhood['id']
        detail = {'neighborhoodId': ident, 'buildings': [b for b in buildings if b['neighborhoodId'] == ident], 'parks': [p for p in parks if overlap(bounds(p['geometry']), neighborhood['bounds'])], 'terrain': pending_terrain(neighborhood['bounds']), 'infrastructure': infrastructure([d for d in drains if d['neighborhoodId'] == ident], neighborhood['bounds'])}
        write(output / 'neighborhoods' / (ident + '.json'), detail)
        details[ident] = '/manhattan/neighborhoods/' + ident + '.json'
        print(ident, neighborhood['name'], len(detail['buildings']), flush=True)
    whole = [min(n['bounds'][0] for n in neighborhoods), min(n['bounds'][1] for n in neighborhoods), max(n['bounds'][2] for n in neighborhoods), max(n['bounds'][3] for n in neighborhoods)]
    overview = buildings
    write(output / 'neighborhoods.json', neighborhoods)
    write(output / 'overview.json', {'buildings': overview, 'parks': parks, 'terrain': pending_terrain(whole), 'infrastructure': infrastructure(drains)})
    retrieved = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    source_defs = [('9nt8-h7nd', 'NYC Department of City Planning 2020 Neighborhood Tabulation Areas'), ('5zhs-2jue', 'NYC OTI Building Footprints'), ('enfh-gkve', 'NYC Parks Properties'), ('2w2g-fk3i', 'NYC DEP Citywide Catch Basins')]
    sources = [{'name': name, 'url': 'https://data.cityofnewyork.us/d/' + ident, 'retrievedAt': datetime.datetime.fromtimestamp((args.cache / (ident + '.json')).stat().st_mtime, datetime.timezone.utc).date().isoformat(), 'license': 'NYC Open Data Terms of Use https://opendata.cityofnewyork.us/overview/#termsofuse'} for ident, name in source_defs]
    sources.append({'name': 'Open Sewer Atlas NYC illustrative interceptors and force mains', 'url': 'https://openseweratlas.tumblr.com/data', 'retrievedAt': datetime.datetime.fromtimestamp(kml_path.stat().st_mtime, datetime.timezone.utc).date().isoformat(), 'license': 'Author permits illustrative/educational use with credit to Open Sewer Atlas NYC. Unofficial, incomplete, not for planning.'})
    limitations = ['Footprint extrusions represent measured plan perimeter and roof height, not facade, roof shape or photorealistic models.', 'NTA2020 boundaries are statistical areas, not legal neighborhood boundaries.', 'Height, address, construction year and ground elevation remain null when unavailable; zero roof and ground source values are treated as unknown.', 'Overview and neighborhood details contain every matched non-placeholder source footprint; neighborhood details are available separately for focused loading.', f'{unassigned} footprint parts outside Manhattan NTA polygons were excluded; {skipped_placeholders} permit placeholders were excluded.', 'Basemap observations are not catastrophe hazard, first-floor elevation or underwriting evidence.', 'Catch basins are mapped surface inlet positions with unknown depth and connectivity. Historic Open Sewer Atlas NYC interceptors and force mains are unofficial, incomplete, illustrative only and not for planning. Depths are unknown; no drain connections are inferred.']
    write(output / 'manifest.json', {'version': 1, 'neighborhoodsUrl': '/manhattan/neighborhoods.json', 'overviewUrl': '/manhattan/overview.json', 'details': details, 'counts': {'neighborhoods': len(neighborhoods), 'buildings': len(buildings), 'parks': len(parks)}, 'sources': sources, 'limitations': limitations})
    write(output / 'source-checksums.json', {ident: {'sha256': hashlib.sha256((args.cache / (ident + '.json')).read_bytes()).hexdigest(), 'recordCount': len(records)} for ident, records in [('9nt8-h7nd', ntas), ('5zhs-2jue', footprints), ('enfh-gkve', properties), ('2w2g-fk3i', catch_basins)]})
    checksums_path = output / 'source-checksums.json'
    checksums = json.loads(checksums_path.read_text())
    checksums['open-sewer-atlas-kml'] = {'sha256': hashlib.sha256(kml_path.read_bytes()).hexdigest(), 'recordCount': len(kml.findall('.//k:Placemark', namespace))}
    write(checksums_path, checksums)
    dem_builder = runpy.run_path(str(Path(__file__).with_name('build-manhattan-dem.py')))['build']
    dem_builder(output, args.dem_cache, args.refresh)
    print('Complete', len(neighborhoods), len(buildings), len(parks), 'overview', len(overview), 'retrieved', retrieved, flush=True)


if __name__ == '__main__':
    main()
