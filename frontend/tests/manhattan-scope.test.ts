import assert from "node:assert/strict";
import test from "node:test";
import { geometryBounds, pointInGeometry } from "../src/lib/manhattan/geo";
import { sceneScope } from "../src/lib/manhattan/sceneScope";
import type { Building, Geometry, Infrastructure, LngLat, ManhattanOverview, Neighborhood, NeighborhoodDetail, Park, PolygonGeometry, TerrainGrid } from "../src/lib/manhattan/types";

const point = (east: number, north: number): LngLat => [-74 + east / 1000, 40.7 + north / 1000];
function rectangle(w: number, s: number, e: number, n: number): PolygonGeometry {
  return { type: "Polygon", coordinates: [[point(w, s), point(e, s), point(e, n), point(w, n), point(w, s)]] };
}
const geometry = rectangle(0, 0, 4, 4);
geometry.coordinates.push(rectangle(1, 1, 2, 2).coordinates[0]);
function neighborhood(id: string, geometry: Geometry): Neighborhood {
  return { id, name: id, geometry, bounds: geometryBounds(geometry), center: point(2, 2), type: "0" };
}
const selected = neighborhood("A", geometry), outside = neighborhood("B", rectangle(5, 0, 9, 4));
const neighborhoods = [selected, outside];
const terrain: TerrainGrid = { bounds: [-74, 40.7, -73.991, 40.704], width: 2, height: 2, elevationsM: [0, 10, 20, 30], source: "Measured test elevations" };
const detailTerrain: TerrainGrid = { ...terrain, source: "Detailed selected elevations" };
function building(id: string, neighborhoodId: string, center: LngLat): Building {
  return { id, neighborhoodId, center, footprint: [[center, [center[0] + 0.0001, center[1]], [center[0], center[1] + 0.0001], center]], heightM: 20, groundElevationM: 0, bin: null, bbl: null, address: null, name: null, yearBuilt: null, featureCode: "2100" };
}
const mapped = building("selected-overview", "A", point(0.5, 0.5));
// Keep exact source footprints assigned to A, including parts crossing its boundary.
const crossing = building("selected-crossing", "A", point(4.1, 3));
const other = building("outside", "B", point(7, 2));
const parks: Park[] = [
  { id: "inside", name: "Inside park", geometry: rectangle(0.2, 2.2, 0.8, 2.8) },
  { id: "shared", name: "Crossing park", geometry: rectangle(3, 2, 6, 3) },
  { id: "outside", name: "Outside park", geometry: rectangle(6, 1, 8, 3) },
  { id: "hole", name: "Excluded hole", geometry: rectangle(1.2, 1.2, 1.8, 1.8) },
];
const infrastructure: Infrastructure = {
  sewerAvailability: "partial", sewerStatus: "Historic source geometry; depths unknown",
  stormDrains: [{ id: "inside", position: point(0.5, 0.5), depthM: null }, { id: "outside", position: point(7, 2), depthM: null }, { id: "hole", position: point(1.5, 1.5), depthM: null }],
  sewerLines: [{ id: "crossing", coordinates: [point(-1, 0.5), point(5, 0.5)], depthM: null, type: "Interceptor" }, { id: "hole", coordinates: [point(-1, 1.5), point(5, 1.5)], depthM: null, type: "Interceptor" }, { id: "outside", coordinates: [point(6, 1), point(8, 2)], depthM: null, type: "Force Main" }],
};
const overview: ManhattanOverview = { buildings: [mapped, crossing, other], parks, terrain, infrastructure };
const detail: NeighborhoodDetail = { neighborhoodId: "A", buildings: [building("selected-detail", "A", point(0.5, 0.5)), crossing, other], parks, terrain: detailTerrain, infrastructure };

test("selection immediately hides all other scene layers while detail loads", () => {
  const scope = sceneScope(neighborhoods, overview, null, "A");
  assert.deepEqual(scope.neighborhoods.map(item => item.id), ["A"]);
  assert.deepEqual(scope.buildings.map(item => item.id), [mapped.id, crossing.id]);
  assert.deepEqual(scope.parks.map(item => item.id), ["inside", "shared"]);
  assert.deepEqual(scope.infrastructure?.stormDrains.map(item => item.id), ["inside"]);
  assert.equal(scope.clip, selected.geometry);
  assert.equal(scope.terrain, overview.terrain);
  assert.deepEqual(scope.bounds, selected.bounds);
});

test("detail replaces assigned footprints and stale detail cannot reveal the previous neighborhood", () => {
  const scope = sceneScope(neighborhoods, overview, detail, "A");
  assert.deepEqual(scope.buildings.map(item => item.id), ["selected-detail", crossing.id]);
  assert.equal(scope.terrain, detailTerrain);
  assert.equal(scope.buildings.find(item => item.id === crossing.id)?.footprint, crossing.footprint);
  const next = sceneScope(neighborhoods, overview, detail, "B");
  assert.equal(next.detail, null);
  assert.deepEqual(next.neighborhoods, [outside]);
  assert.deepEqual(next.buildings, [other]);
  assert.equal(next.terrain, overview.terrain);
  const unloaded = sceneScope(neighborhoods, null, detail, "B");
  assert.deepEqual(unloaded.buildings, []);
  assert.deepEqual(unloaded.parks, []);
});

test("drainage clips to the real selection polygon and holes without inventing depth", () => {
  const scope = sceneScope(neighborhoods, overview, null, "A");
  const lines = scope.infrastructure!.sewerLines;
  assert.equal(lines.length, 3);
  assert.ok(lines.every(line => line.depthM === null && line.type === "Interceptor"));
  for (const line of lines) for (let i = 1; i < line.coordinates.length; i++) {
    const a = line.coordinates[i - 1], b = line.coordinates[i];
    assert.equal(pointInGeometry([(a[0] + b[0]) / 2, (a[1] + b[1]) / 2], selected.geometry), true);
  }
  assert.ok(lines.flatMap(line => line.coordinates).every(([lng]) => lng >= selected.bounds[0] - 1e-10 && lng <= selected.bounds[2] + 1e-10));
  assert.equal(scope.infrastructure?.sewerStatus, infrastructure.sewerStatus);
});

test("island view restores the complete overview and ignores old detail", () => {
  const scope = sceneScope(neighborhoods, overview, detail, null);
  assert.equal(scope.detail, null);
  assert.equal(scope.neighborhoods, neighborhoods);
  assert.equal(scope.buildings, overview.buildings);
  assert.equal(scope.parks, overview.parks);
  assert.equal(scope.infrastructure, overview.infrastructure);
  assert.equal(scope.clip, undefined);
  assert.deepEqual(scope.bounds, [-74, 40.7, -73.991, 40.704]);
});


test("detached islands split a crossing source line without a connector through the water", () => {
  const islands: Geometry = { type: "MultiPolygon", coordinates: [rectangle(0, 0, 1, 1).coordinates, rectangle(3, 0, 4, 1).coordinates] };
  const area = neighborhood("islands", islands);
  const source: ManhattanOverview = { ...overview, infrastructure: { ...infrastructure, stormDrains: [], sewerLines: [{ id: "island-line", coordinates: [point(-1, 0.5), point(5, 0.5)], depthM: 4, type: "Force Main" }] } };
  const lines = sceneScope([area], source, null, area.id).infrastructure!.sewerLines;
  assert.equal(lines.length, 2);
  assert.ok(lines.every(line => line.depthM === 4 && line.type === "Force Main"));
  assert.ok(lines[0].coordinates.every(([lng]) => lng <= point(1, 0)[0] + 1e-10));
  assert.ok(lines[1].coordinates.every(([lng]) => lng >= point(3, 0)[0] - 1e-10));
});
