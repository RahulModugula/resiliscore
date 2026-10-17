# Manhattan scene

`ManhattanScene` is a client component built with React Three Fiber 9, Drei 10,
and Three.js. Give its parent an explicit height. The containing page owns data
loading, accessible neighborhood and property lists, source attribution, and risk
assessment. The scene never contacts a backend or external map/font service.

World coordinates are east, elevation, negative north in metres around the
Manhattan origin in `lib/manhattan/geo.ts`. Actual footprint rings are triangulated
with courtyard holes and extruded by supplied roof heights. Missing heights stay
flat; missing ground elevations use the visual zero datum. No height inference
or building replacement boxes are used.

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

`onReady` reports a mounted WebGL renderer. `onError` reports an accessible recovery
message for renderer failure or context loss. The page's property lists remain
usable independently of WebGL. Rendering errors also have an inline fallback.
