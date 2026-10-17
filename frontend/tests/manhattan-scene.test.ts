import assert from "node:assert/strict";
import test from "node:test";
import { unprojectMeters } from "../src/lib/manhattan/geo";
import { buildingAtFace, buildingGeometry, cameraFrame, polygonGeometry, terrainElevation, terrainGeometry, worldPoint } from "../src/lib/manhattan/sceneGeometry";
import type { Building, Geometry, LngLat, Neighborhood, TerrainGrid } from "../src/lib/manhattan/types";

const ring = (points: [number, number][]) => points.map((point) => unprojectMeters(point));
const outer = ring([[0, 0], [100, 0], [100, 100], [0, 100], [0, 0]]);
const courtyard = ring([[25, 25], [25, 75], [75, 75], [75, 25], [25, 25]]);
const geometry: Geometry = { type: "Polygon", coordinates: [outer, courtyard] };
const building: Building = { id: "42", bin: "1000042", bbl: null, address: null, name: null, center: unprojectMeters([50, 50]), footprint: [outer, courtyard], heightM: 80, groundElevationM: 12, neighborhoodId: "MN01", yearBuilt: null, featureCode: "2100" };

test("geographic north is -Z and elevations remain in metres", () => {
  const point = worldPoint(unprojectMeters([20, 30]), 12);
  assert.ok(Math.abs(point[0] - 20) < 1e-6);
  assert.equal(point[1], 12);
  assert.ok(Math.abs(point[2] + 30) < 1e-6);
});

test("polygon roofs preserve courtyard holes instead of filling their area", () => {
  const result = polygonGeometry(geometry, () => 0);
  const positions = result.getAttribute("position");
  let area = 0;
  for (let i = 0; i < positions.count; i += 3) {
    const ax = positions.getX(i), az = positions.getZ(i);
    const bx = positions.getX(i + 1), bz = positions.getZ(i + 1);
    const cx = positions.getX(i + 2), cz = positions.getZ(i + 2);
    area += Math.abs((bx - ax) * (cz - az) - (bz - az) * (cx - ax)) / 2;
  }
  assert.ok(Math.abs(area - 7500) < 0.1);
  result.dispose();
});

test("merged building triangles retain property selection and supplied height", () => {
  const unknown = { ...building, id: "43", heightM: null, groundElevationM: 6 };
  const result = buildingGeometry([building, unknown]);
  assert.equal(result.geometry.boundingBox?.min.y, 6.199999809265137);
  assert.ok(Math.abs((result.geometry.boundingBox?.max.y ?? 0) - 92.2) < 0.001);
  assert.equal(buildingAtFace(0, result.triangleEnds), 0);
  assert.equal(buildingAtFace(result.triangleEnds[0] - 1, result.triangleEnds), 0);
  assert.equal(buildingAtFace(result.triangleEnds[0], result.triangleEnds), 1);
  assert.equal(buildingAtFace(result.triangleEnds[1], result.triangleEnds), -1);
  assert.equal(buildingAtFace(-1, result.triangleEnds), -1);
  result.geometry.dispose();
});

test("terrain interpolation does not invent observations in unsupported cells", () => {
  const bounds: [number, number, number, number] = [...unprojectMeters([0, 0]), ...unprojectMeters([100, 100])];
  const center = unprojectMeters([50, 50]);
  const grid: TerrainGrid = { bounds, width: 2, height: 2, elevationsM: [0, 10, 20, 30], source: "test observations" };
  assert.ok(Math.abs((terrainElevation(center, grid) ?? -1) - 15) < 0.001);
  assert.equal(terrainElevation(unprojectMeters([200, 200]), grid), null);
  const missing = { ...grid, elevationsM: [0, 10, null, 30] };
  assert.equal(terrainElevation(center, missing), null);
  const neighborhood: Neighborhood = { id: "MN01", name: "Test", geometry: { type: "Polygon", coordinates: [outer] }, bounds, center, type: "0" };
  const result = terrainGeometry(missing, [neighborhood]);
  assert.equal(result.getAttribute("position").count, 0);
  result.dispose();
});

test("camera bounds include portrait and landscape viewports with finite positions", () => {
  const a: LngLat = unprojectMeters([0, 0]);
  const b: LngLat = unprojectMeters([1000, 2000]);
  const landscape = cameraFrame([a[0], a[1], b[0], b[1]], 1.8);
  const portrait = cameraFrame([a[0], a[1], b[0], b[1]], 0.5);
  assert.ok(portrait.distance > landscape.distance);
  assert.ok(portrait.position.every(Number.isFinite));
  assert.ok(Math.abs(landscape.target[0] - 500) < 0.001);
  assert.ok(Math.abs(landscape.target[2] + 1000) < 0.001);
});
