#!/usr/bin/env python3
"""Cache measured USGS 3DEP bare-earth elevation on one shared Manhattan grid.

Install scripts/manhattan-dem-requirements.txt in a virtual environment first.
The raw GeoTIFF, catalog and export request cache outside Git. No API is needed
at runtime. Existing source snapshots are reused unless --refresh is supplied.
"""
import argparse
import datetime
import hashlib
import json
import math
from pathlib import Path
import time
import urllib.parse
import urllib.request

import numpy as np
import rasterio
from rasterio.features import geometry_mask

SERVICE = 'https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer'
CATALOG = 'https://data.usgs.gov/datacatalog/data/USGS%3A77ae0551-c61e-4979-aedd-d797abdcde0e'
SPACING_M = 10
EARTH_RADIUS_M = 6371008.8
ORIGIN_LAT = 40.7831
SOURCE = 'USGS 3DEP one-metre bare-earth DEM; nearest-neighbor grid samples; metres NAVD88'


def write(path, value):
    path.write_text(json.dumps(value, separators=(',', ':'), ensure_ascii=False, allow_nan=False) + '\n')


def download(url):
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url, timeout=300) as response:
                return response.read()
        except Exception:
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)


def request_grid(bounds):
    """One pixel-aligned geographic grid with near-10m cells, including an edge halo."""
    dx = SPACING_M / (EARTH_RADIUS_M * math.pi / 180 * math.cos(math.radians(ORIGIN_LAT)))
    dy = SPACING_M / (EARTH_RADIUS_M * math.pi / 180)
    west = math.floor(bounds[0] / dx) * dx - dx
    south = math.floor(bounds[1] / dy) * dy - dy
    width = math.ceil((bounds[2] - west) / dx) + 1
    height = math.ceil((bounds[3] - south) / dy) + 1
    return [west, south, west + width * dx, south + height * dy], width, height


def source_rasters(cache, bounds, refresh):
    target = cache / 'catalog.json'
    if refresh or not target.exists():
        params = {'f': 'json', 'geometry': json.dumps({'xmin': bounds[0], 'ymin': bounds[1], 'xmax': bounds[2], 'ymax': bounds[3], 'spatialReference': {'wkid': 4326}}), 'geometryType': 'esriGeometryEnvelope', 'spatialRel': 'esriSpatialRelIntersects', 'where': 'Category=1', 'returnGeometry': 'false', 'outFields': 'OBJECTID,Name,DEM_Type,Source,VerticalDatum,AcquisitionDate,URL,Metadata,title,Resolution_X,Resolution_Y,Best'}
        target.write_bytes(download(SERVICE + '/query?' + urllib.parse.urlencode(params)))
    catalog = json.loads(target.read_text())
    if 'error' in catalog or catalog.get('exceededTransferLimit'):
        raise ValueError('USGS catalog could not be retrieved completely')
    sources = sorted([feature['attributes'] for feature in catalog['features'] if 'meter' in (feature['attributes']['title'] or '').lower()], key=lambda item: (item['Best'], item['OBJECTID']))
    if not sources or any(source['VerticalDatum'] != 'North American Vertical Datum of 1988 (NAVD 88)' for source in sources):
        raise ValueError('Expected USGS one-metre NAVD88 bare-earth source tiles')
    return sources


def raw_raster(cache, bounds, sources, refresh):
    path = cache / 'manhattan-10m.tif'
    request_path = cache / 'export-request.json'
    response_path = cache / 'export-response.json'
    extent, width, height = request_grid(bounds)
    params = {'f': 'json', 'bbox': ','.join(map(str, extent)), 'bboxSR': 4326, 'imageSR': 4326, 'size': f'{width},{height}', 'format': 'tiff', 'pixelType': 'F32', 'renderingRule': json.dumps({'rasterFunction': 'None'}), 'mosaicRule': json.dumps({'mosaicMethod': 'esriMosaicLockRaster', 'lockRasterIds': [source['OBJECTID'] for source in sources], 'mosaicOperation': 'MT_FIRST'}), 'interpolation': 'RSP_NearestNeighbor', 'adjustAspectRatio': 'false'}
    expected = {'params': params, 'sources': sources}
    if request_path.exists():
        previous = json.loads(request_path.read_text())
        if previous.get('params') != params and not refresh:
            raise ValueError('DEM request changed. Use a separate cache or --refresh.')
    if refresh or not path.exists():
        url = SERVICE + '/exportImage?' + urllib.parse.urlencode(params)
        write(request_path, {**expected, 'url': url})
        result = json.loads(download(url))
        if 'href' not in result:
            raise ValueError(f'USGS exportImage did not produce a raster: {result}')
        write(response_path, result)
        path.write_bytes(download(result['href']))
    if not request_path.exists() or not response_path.exists():
        raise ValueError('Raw DEM requires its export request and response metadata')
    return path, json.loads(request_path.read_text()), json.loads(response_path.read_text())


def decode(path, study_geometries):
    """Read exact pixel centres. Reverse raster north-first rows to south-first rows."""
    with rasterio.open(path) as dataset:
        if dataset.crs.to_epsg() != 4326 or dataset.count != 1 or dataset.dtypes != ('float32',):
            raise ValueError('Expected one-band Float32 EPSG:4326 raster')
        transform = dataset.transform
        if transform.b != 0 or transform.d != 0 or transform.a <= 0 or transform.e >= 0:
            raise ValueError('Expected north-up, unrotated raster')
        data = dataset.read(1, masked=True)
        values = np.asarray(data.data, dtype=np.float64)
        # ArcGIS Float32 NoData can be encoded as the minimum float without a GDAL tag.
        unknown = np.ma.getmaskarray(data) | ~np.isfinite(values) | (np.abs(values) > 100000)
        study = geometry_mask(study_geometries, out_shape=values.shape, transform=transform, all_touched=True, invert=True)
        unknown |= ~study
        values[unknown] = np.nan
        west, south = dataset.xy(dataset.height - 1, 0)
        east, north = dataset.xy(0, dataset.width - 1)
        return np.flipud(values), [float(west), float(south), float(east), float(north)], {'extent': list(dataset.bounds), 'cellSizeDegrees': [transform.a, -transform.e], 'width': dataset.width, 'height': dataset.height, 'sourceNoDataValue': dataset.nodata, 'northUpTransform': list(transform)[:6]}


def crop(values, sample_bounds, bounds, stride=1):
    """Crop shared samples without resampling. Bounds always describe sample centres."""
    dx = (sample_bounds[2] - sample_bounds[0]) / (values.shape[1] - 1)
    dy = (sample_bounds[3] - sample_bounds[1]) / (values.shape[0] - 1)
    if bounds is None:
        x0 = y0 = 0
        x1, y1 = values.shape[1] - 1, values.shape[0] - 1
    else:
        x0 = max(0, math.floor((bounds[0] - sample_bounds[0]) / dx) - 1)
        y0 = max(0, math.floor((bounds[1] - sample_bounds[1]) / dy) - 1)
        x1 = min(values.shape[1] - 1, math.ceil((bounds[2] - sample_bounds[0]) / dx) + 1)
        y1 = min(values.shape[0] - 1, math.ceil((bounds[3] - sample_bounds[1]) / dy) + 1)
    selected = values[y0:y1 + 1:stride, x0:x1 + 1:stride]
    xlast = x0 + (selected.shape[1] - 1) * stride
    ylast = y0 + (selected.shape[0] - 1) * stride
    centers = [sample_bounds[0] + x0 * dx, sample_bounds[1] + y0 * dy, sample_bounds[0] + xlast * dx, sample_bounds[1] + ylast * dy]
    spacing = [dx * stride, dy * stride]
    return {'bounds': centers, 'width': selected.shape[1], 'height': selected.shape[0], 'elevationsM': [round(float(value), 2) if np.isfinite(value) else None for value in selected.flat], 'source': SOURCE, 'raster': {'dataset': 'USGS_3DEP_1M', 'horizontalCrs': 'EPSG:4326', 'verticalDatum': 'NAVD88', 'elevationUnit': 'metre', 'sourceResolutionM': 1, 'nominalSpacingM': SPACING_M * stride, 'cellSizeDegrees': spacing, 'extent': [centers[0] - spacing[0] / 2, centers[1] - spacing[1] / 2, centers[2] + spacing[0] / 2, centers[3] + spacing[1] / 2], 'sampleLocation': 'pixel-center', 'rowOrder': 'south-to-north', 'resampling': 'nearest-neighbor', 'quantizationM': 0.01}}


def build(output, cache, refresh=False):
    cache.mkdir(parents=True, exist_ok=True)
    neighborhoods = json.loads((output / 'neighborhoods.json').read_text())
    bounds = [min(n['bounds'][0] for n in neighborhoods), min(n['bounds'][1] for n in neighborhoods), max(n['bounds'][2] for n in neighborhoods), max(n['bounds'][3] for n in neighborhoods)]
    sources = source_rasters(cache, bounds, refresh)
    path, request, response = raw_raster(cache, bounds, sources, refresh)
    values, sample_bounds, metadata = decode(path, [n['geometry'] for n in neighborhoods])
    if values.shape != (response['height'], response['width']):
        raise ValueError('Export metadata and decoded raster dimensions disagree')
    provenance = {'source': SOURCE, 'service': SERVICE, 'catalogUrl': CATALOG, 'license': 'Public domain USGS 3DEP data', 'retrievedAt': datetime.datetime.fromtimestamp(path.stat().st_mtime, datetime.timezone.utc).isoformat(), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'catalogSha256': hashlib.sha256((cache / 'catalog.json').read_bytes()).hexdigest(), 'request': request, 'response': response, 'decoded': metadata, 'sampleBounds': sample_bounds, 'nativeSources': sources, 'notes': ['The service is explicitly locked to one-metre source tiles. Native source grids are reprojected to WGS84 and nearest-neighbor sampled at approximately 10 metres.', 'Grid bounds describe exact first/last pixel centers. TIFF north-first rows are reversed to southwest-first row-major arrays.', 'Source NoData, nonfinite values, ArcGIS Float32 sentinel values and cells outside the Manhattan study area remain null. No building-ground interpolation, extrapolation or hillshade is used.', 'One-metre source products are NAVD88 metres; they can have project-boundary differences and are not live surveys.']}
    for neighborhood in neighborhoods:
        target = output / 'neighborhoods' / (neighborhood['id'] + '.json')
        detail = json.loads(target.read_text())
        detail['terrain'] = crop(values, sample_bounds, neighborhood['bounds'])
        write(target, detail)
        known = [value for value in detail['terrain']['elevationsM'] if value is not None]
        print(neighborhood['id'], detail['terrain']['width'], detail['terrain']['height'], 'relief', round(max(known) - min(known), 2) if known else None, flush=True)
    overview_path = output / 'overview.json'
    overview = json.loads(overview_path.read_text())
    overview['terrain'] = crop(values, sample_bounds, None, stride=5)
    write(overview_path, overview)
    write(output / 'terrain-10m.json', crop(values, sample_bounds, None))
    write(output / 'dem-provenance.json', provenance)
    manifest_path = output / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    manifest['version'] = 2
    manifest['terrainUrl'] = '/manhattan/terrain-10m.json'
    manifest['sources'] = [source for source in manifest['sources'] if source['url'] != SERVICE]
    manifest['sources'].append({'name': 'USGS 3DEP one-metre bare-earth DEM, sampled at 10m detail / 50m overview', 'url': SERVICE, 'retrievedAt': provenance['retrievedAt'][:10], 'license': 'Public domain. USGS National Map 3D Elevation Program.'})
    manifest['limitations'] = [limitation for limitation in manifest['limitations'] if not ('Terrain is interpolation' in limitation or 'building-base elevation interpolation' in limitation)]
    terrain_note = 'Terrain uses USGS 3DEP one-metre bare-earth sources sampled at about 10m in neighborhood detail and 50m in the overview. Elevations are NAVD88 metres; source NoData and cells outside Manhattan remain unknown. Historical source tiles can differ at project boundaries; this is not an engineering survey.'
    if terrain_note not in manifest['limitations']:
        manifest['limitations'].append(terrain_note)
    write(manifest_path, manifest)
    checksums_path = output / 'source-checksums.json'
    checksums = json.loads(checksums_path.read_text())
    checksums['usgs-3dep-dem'] = {'sha256': provenance['sha256'], 'rasterWidth': values.shape[1], 'rasterHeight': values.shape[0], 'nativeSourceCount': len(sources)}
    write(checksums_path, checksums)
    print('Measured DEM complete', values.shape, 'known cells', np.isfinite(values).sum(), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', type=Path, default=Path('/tmp/resiliscore-manhattan-dem'))
    parser.add_argument('--refresh', action='store_true')
    args = parser.parse_args()
    build(Path(__file__).resolve().parent.parent / 'public' / 'manhattan', args.cache, args.refresh)


if __name__ == '__main__':
    main()
