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

## Elevation limitations

The terrain grid uses actual NYC building-base ground elevations with inverse distance weighting over the nearest eight observations within 600 metres. It is a regional ground context estimate, not a bare-earth digital elevation model or an engineering terrain survey. Grid points outside Manhattan NTA polygons or without nearby observations remain null. Park interiors can have sparse support, so their terrain should not imply measured local hills or rock outcrops. Rows run from south to north, columns west to east.

Ground elevation is separate from building height. Neither the terrain estimate nor the building-base value is first-floor elevation, flood freeboard, catastrophe hazard, or underwriting evidence. No risk scores are stored here. Missing address, height, construction year and elevation values remain null; consumers must label any visual placeholder as an estimate.

## Rebuild

From `frontend/` run:

```sh
python3 scripts/build-manhattan-data.py
```

The script uses only Python 3's standard library. It downloads four NYC public datasets and the attributed Open Sewer Atlas KML with ordered, paginated queries and caches the raw snapshots in `/tmp/resiliscore-manhattan-sources`. Subsequent builds reuse those exact snapshots. Use `--cache <directory>` to keep them elsewhere, or `--refresh` to download a new snapshot. Run `npm test`, `npm run lint` and `npm run build` after rebuilding. Do not edit generated JSON by hand.

Coordinates round to seven decimal places, roughly one centimetre at this latitude. Source precision and accuracy remain the limiting factors. Building centers are footprint bounding-box centers, which can fall outside irregular footprints. Assignment tests the center against NTA polygons, then samples real exterior vertices for footprints crossing shorelines or boundaries. Footprints outside all Manhattan NTAs are excluded and counted in the manifest.
