# Manhattan scene

`ManhattanScene` is a client component built with React Three Fiber 9, Drei 10,
and Three.js. Give its parent an explicit height. The containing page owns data
loading, accessible neighborhood and property lists, source attribution, and risk
assessment. The scene never contacts a backend or external map/font service.

World coordinates are east, elevation, negative north in metres around the
Manhattan origin in `lib/manhattan/geo.ts`. Actual footprint rings are triangulated
with courtyard holes and extruded by supplied roof heights. Building feet sample
the same measured DEM triangles as the ground, with supplied ground elevation
used only when a DEM observation is unavailable. Missing heights stay unextruded;
if both ground sources are missing, the footprint uses the visual zero datum.
No height inference or building replacement boxes are used.

Overview clicks select a neighborhood. Once its detail has loaded, property
clicks return the supplied `Building`. Camera bounds update with selection and
viewport aspect, with reduced motion respected. Passing a null neighborhood
resets the full-island view. Drag, wheel, pinch and two-finger gestures are
provided by Drei CameraControls. Lists outside the canvas provide keyboard access.

Buildings share one geometry draw call with a triangle-to-property lookup. Drei's
indirect BVH keeps triangle identities intact during accelerated picking. The
renderer uses demand frames and a device pixel ratio cap of 1.5. Geometries and
BVHs are disposed when replaced.

`showUnderground` makes land, parks and buildings transparent and displays the
active data's infrastructure. Cyan points are supplied storm-drain locations;
amber segments are supplied sewer lines. Missing depths use a schematic 12-metre
vertical display offset below sampled ground, not a claimed pipe/drain depth.
The containing page must display this distinction and the source's completeness
limitations. Empty sewer geometry stays empty.

## Measured terrain

`TerrainGrid.bounds` locates raster sample centers. Rows run from southwest to
northeast, with elevation in metres NAVD88. `terrainElevation` interpolates the
same SW-SE-NW and SE-NE-NW triangles that the indexed DEM surface renders. Cells
with missing observations are omitted. Source coastlines and polygon holes are
clipped exactly in raster boundary cells; no broad polygon plane covers the DEM.
Park meshes include interior raster samples, so a hill surrounded by a level park
boundary remains a hill. Source polygons are triangulated once and spatially
binned; scanline masks and clipped indexed topology are cached per raster.

`showTerrain` fades buildings and uses a low-sage `#54796b` to high-earth `#c5ae82`
ground palette over a fixed 0–100 m NAVD88 range, plus directional slope shading.
The color always describes measured elevation, even when visual scale changes.
`verticalScale` defaults to 1. It scales ground elevation only; physical building
height, pipe depth and display offsets stay in metres. Park surfaces, building
feet, borders, underground positions, hover labels and camera bounds use the
same ground scale. The containing page must label any scale above 1 explicitly.

Reusable helpers in `lib/manhattan/sceneGeometry.ts` include
`buildingGeometry(buildings, { terrain, terrainAt, verticalScale })`,
`buildingGroundElevation`, `terrainElevation`, `terrainGeometry` and
`outlineGeometry`. `terrainSurface` in `lib/manhattan/terrainSurface.ts` also
accepts exact `include`/`exclude` geometries for a selected neighborhood.

`onReady` reports a mounted WebGL renderer. `onError` reports an accessible recovery
message for renderer failure or context loss. The page's property lists remain
usable independently of WebGL. Rendering errors also have an inline fallback.
