# Manhattan basemap cache

This directory is a static snapshot for the frontend's Manhattan explorer. It requires no backend, map API key or runtime connection to NYC Open Data. All coordinates use longitude/latitude in WGS84. Heights and elevations use metres.

`manifest.json` lists the snapshot sources, exact counts, detail URLs and limitations. `neighborhoods.json` contains the 38 Manhattan NTA2020 polygons, including park and island areas. `overview.json` contains every matched real footprint for the city view. Each file under `neighborhoods/` contains every matched, non-placeholder building footprint for that area, overlapping NYC Parks properties, and a local elevation grid. Roof and courtyard rings remain intact.

## Sources

- [NYC Department of City Planning 2020 Neighborhood Tabulation Areas](https://data.cityofnewyork.us/d/9nt8-h7nd). NTA boundaries are statistical areas. They are useful neighborhood selections but do not define legal or universally accepted neighborhood limits.
- [NYC OTI Building Footprints](https://data.cityofnewyork.us/d/5zhs-2jue). The cache retains the OTI `doitt_id`, BIN and BBL. Multipart footprints receive a part suffix. The source describes `height_roof` as height above ground, not elevation above sea level, and `ground_elevation` as the lowest ground level at the building base. [Official metadata](https://github.com/CityOfNewYork/nyc-geo-metadata/blob/main/Metadata/Metadata_BuildingFootprints.md) describes collection, excluded structures and vertical accuracy. Feet become metres with factor 0.3048. These are footprint extrusions, without measured facade details or roof shapes. Permit placeholder triangles are excluded. Unknown heights remain null. Zero ground values are conservatively treated as unknown.
- [NYC Parks Properties](https://data.cityofnewyork.us/d/enfh-gkve). This includes land managed partly or entirely by NYC Parks. The cache retains actual property polygons, names and `gisobjid` identifiers, falling back to the source global or object identifier where missing. Separate acquisitions may overlap or share a name. It is not a census of every private park, tree or garden.

The sources are published under [NYC Open Data Terms of Use](https://opendata.cityofnewyork.us/overview/#termsofuse). They may contain errors, changes or omissions. The exact retrieval dates appear in the manifest. `source-checksums.json` records SHA-256 hashes and row counts of the raw source snapshots used to build this cache.

## Drainage infrastructure

[NYC DEP Citywide Catch Basins](https://data.cityofnewyork.us/d/2w2g-fk3i) supplies actual storm drain inlet point locations and `unitid` identifiers. Every bundled point falls within a Manhattan NTA polygon. It does not supply pipe connections, invert elevations, depth, diameter, capacity or condition. All `depthM` values remain null. Any underground display offset is a visual offset, not a measured depth.

[DEP's Stormwater Management Program chapter 4](https://www.nyc.gov/assets/dep/downloads/pdf/water/stormwater/ms4/nyc-swmp-report-ch4.pdf) describes its detailed Sewer Network Geodatabase as maintained for internal use. [DEP's records request process](https://www.nyc.gov/site/dep/about/request-records.page) offers GIS data cuts, sewer maps and as-built records. The bundled sewer lines come from [Open Sewer Atlas NYC's author-published KML](https://openseweratlas.tumblr.com/data), not a third-party mirror. Credit: Open Sewer Atlas NYC. The author permits illustrative and educational use with attribution and warns that the files combine outdated DEP shapefiles and manually traced public planning documents. They are unofficial, incomplete and unsuitable for planning. `sewerAvailability` is `partial`; depths remain null. Lines represent major interceptors and force mains, not every street sewer or building lateral. Full line geometries overlapping Manhattan NTA bounds are retained, so some extend into rivers or other boroughs. No connections are inferred between neighboring drains or buildings.

## Measured ground elevation

Terrain comes from the [USGS 3DEP Bare Earth DEM service](https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer), explicitly locked to the official catalog's one-metre bare-earth source tiles. [USGS's one-metre DEM product metadata](https://data.usgs.gov/datacatalog/data/USGS%3A77ae0551-c61e-4979-aedd-d797abdcde0e) specifies metre elevations referenced to NAVD88 and public-domain access. The exported raster uses WGS84 longitude/latitude horizontally. It has no hillshade, color ramp, building-base inference or synthetic hills.

A single common raster supplies every neighborhood. Neighborhood detail uses approximately 10 metre spacing, the city overview takes every fifth source sample for approximately 50 metre spacing, and `terrain-10m.json` provides the complete common 10 metre grid for block context across neighborhood boundaries. Native one-metre source data are nearest-neighbor sampled onto this geographic grid. This is a display resolution, not a claim that every rendered point is an original one-metre observation. The source projects have different acquisition vintages and may differ at project boundaries. They do not describe live construction or an engineering survey.

`TerrainGrid.bounds` describes the centers of the southwest and northeast samples, not the raster's outer pixel edges. Rows run south to north and columns west to east. The optional `raster` metadata records the pixel-edge extent, exact degree spacing, native and display resolution, datum and row orientation. Float32 north-first TIFF rows are reversed once when caching. Heights round to 0.01 metre for JSON storage; rounding does not increase measurement accuracy.

Source NoData, nonfinite values, ArcGIS Float32 NoData sentinels and cells outside the Manhattan study area remain null. The study mask includes cells whose pixel footprint touches an NTA polygon, so shoreline sampling retains real nearby observations. Missing cells are not interpolated or extrapolated. Zero elevation in the DEM is a valid measurement. The separate building `groundElevationM` attributes retain their original NYC source treatment and are not overwritten by this rebuild.

The measured interior of Central Park contains over 35,000 supported grid samples and approximately 39 metres of relief. Inwood Hill Park contains over 9,000 supported samples and approximately 72 metres of relief. These ranges refer to samples inside their NTA polygons, rather than extrema from neighboring buildings. Unit tests check both areas and shared grid alignment.

`dem-provenance.json` records the raw GeoTIFF checksum, request parameters, exact decoded affine transform, source IDs, catalog metadata, retrieval time and export response. `source-checksums.json` also pins the raw DEM checksum. The raw source GeoTIFF stays in the rebuild cache outside Git; the locally bundled JSON grids need no USGS connection at runtime.

Ground elevation is separate from building height. Neither bare-earth terrain nor a building-base elevation is first-floor elevation, flood freeboard, catastrophe hazard, or underwriting evidence. No risk scores are stored here.

## Rebuild

Use Python 3.9 through 3.12 in a virtual environment. From `frontend/`:

```sh
python3 -m venv /tmp/resiliscore-dem-venv
/tmp/resiliscore-dem-venv/bin/pip install -r scripts/manhattan-dem-requirements.txt
/tmp/resiliscore-dem-venv/bin/python scripts/build-manhattan-dem.py
```

The DEM-only command updates terrain in the existing basemap files. To rebuild the complete basemap and measured terrain together, run `scripts/build-manhattan-data.py` with the same Python environment. This first rebuilds the four NYC public datasets and the attributed Open Sewer Atlas KML, then runs the measured DEM stage. It never estimates terrain from building-base elevations.

NYC source snapshots cache in `/tmp/resiliscore-manhattan-sources`; the USGS GeoTIFF, source catalog and export metadata cache in `/tmp/resiliscore-manhattan-dem`. Subsequent builds reuse those exact snapshots. The DEM command accepts `--cache <directory>`. The complete basemap command accepts `--cache <NYC directory>` and `--dem-cache <USGS directory>`. Use `--refresh` to retrieve new source snapshots. The USGS export can take several minutes. Do not edit generated JSON by hand.

Verify rebuilt data with:

```sh
/tmp/resiliscore-dem-venv/bin/python -m unittest discover -s scripts -p 'test_manhattan_dem.py'
npm test
npm run lint
npm run build
```

Building, neighborhood and park coordinates round to seven decimal places, roughly one centimetre at this latitude. DEM sample bounds retain the decoded raster precision. Source precision and accuracy remain the limiting factors. Building centers are footprint bounding-box centers, which can fall outside irregular footprints. Assignment tests the center against NTA polygons, then samples real exterior vertices for footprints crossing shorelines or boundaries. Footprints outside all Manhattan NTAs are excluded and counted in the manifest.
