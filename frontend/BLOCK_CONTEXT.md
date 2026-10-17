# Selected-property block view

The Manhattan assessment opens a focused 3D block view beside the risk result. The selected building is cyan. Neighboring footprints retain the NYC source geometry, roof heights and identity. The original golden-scenario map is unchanged.

Addresses use the NYC DCP PLUTO primary tax-lot address, matched by the footprint's exact 10-digit BBL. Several structures on the same lot can share that address. A missing address stays **Address unavailable**; a landmark name or BIN is never presented as a street address. BIN and source building ID remain secondary identifiers. The backend request keeps a unique source-building identifier when its address is unknown.

With a valid BBL, the extent covers all mapped footprints in the same tax block plus 42 metres of adjoining frontage. Context includes buildings intersecting this rectangle, including buildings across neighborhood boundaries. Without a valid BBL, it uses a clearly labeled approximate 180-metre vicinity. A tax-block rectangle is a framing extent, not a surveyed parcel boundary.

The scene uses the common USGS bare-earth 10-metre DEM, cropped without inventing or flattening samples. Ground elevation is metres relative to NAVD88 and is shown separately from height above ground. Roads follow the DEM at intervals of at most five metres; cells without DEM support are omitted. The view uses true vertical scale. Source roof heights and bare-earth elevation differ from a surveyed building model and are geographic context, not certified freeboard or risk evidence.

The local assets include NYC OTI Street Centerline coordinates and names for constructed at-grade segments. Paper streets, bridges, tunnels, ferry routes and nonphysical links are excluded rather than draped onto the ground. A supplied street width is converted from feet to metres; missing widths appear as thin centerlines. These ribbons do not establish curb boundaries. Expand the view's source details for an accessible list of surrounding addresses, street names and source limitations. The list and measurements remain usable when WebGL is unavailable.

## Refresh the local context assets

Run `python3 scripts/build-manhattan-context.py` from `frontend/`. It downloads official public datasets at build time only. The app fetches bundled `/manhattan/` assets at runtime and requires no GIS token or backend.

- [NYC DCP PLUTO 26v2, 64uk-42ks](https://data.cityofnewyork.us/d/64uk-42ks), primary tax-lot addresses keyed by exact BBL.
- [NYC OTI Street Centerline, inkn-q76z](https://data.cityofnewyork.us/d/inkn-q76z), real centerline geometry, full street names and supplied widths.
- NYC OTI Building Footprints and USGS terrain source details remain in the map manifest and terrain attribution.

`public/manhattan/context/sources.json` records the retrieval date, counts and limitations for the two additional datasets. The refresh script deliberately does not edit the original footprint files or contracts.
