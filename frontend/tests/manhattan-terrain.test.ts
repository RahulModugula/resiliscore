import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { unprojectMeters } from "../src/lib/manhattan/geo";
import { buildingGeometry, buildingGroundElevation, outlineGeometry, parkGeometry, terrainElevation } from "../src/lib/manhattan/sceneGeometry";
import { terrainSurface } from "../src/lib/manhattan/terrainSurface";
import type { Building, NeighborhoodDetail, Park, TerrainGrid } from "../src/lib/manhattan/types";

const southwest = unprojectMeters([0, 0]);
const northeast = unprojectMeters([100, 100]);
const hill: TerrainGrid = { bounds: [...southwest, ...northeast], width: 3, height: 3, elevationsM: [0, 0, 0, 0, 20, 0, 0, 0, 0], source: "regression fixture" };
const park = { id: "hill-park", name: "Hill park", geometry: { type: "Polygon", coordinates: [[southwest, unprojectMeters([100, 0]), northeast, unprojectMeters([0, 100]), southwest]] } } satisfies Park;

test("park surfaces preserve a supplied interior hill even when all boundary elevations are zero", () => {
  const mesh = parkGeometry([park], hill);
  assert.ok((mesh.boundingBox?.max.y ?? 0) >= 20, `interior hill disappeared: maximum rendered height ${mesh.boundingBox?.max.y}`);
  mesh.dispose();
});

test("DEM cell clipping preserves a hole smaller than one raster cell", () => {
  const geometry = { ...park.geometry, coordinates: [...park.geometry.coordinates, [[30, 30], [40, 30], [40, 40], [30, 40], [30, 30]].map((point) => unprojectMeters(point as [number, number]))] };
  const mesh = terrainSurface(hill, [geometry]);
  const positions = mesh.getAttribute("position");
  let area = 0;
  for (let i = 0; i < mesh.index!.count; i += 3) {
    const [a, b, c] = [mesh.index!.getX(i), mesh.index!.getX(i + 1), mesh.index!.getX(i + 2)];
    area += Math.abs((positions.getX(b) - positions.getX(a)) * (positions.getZ(c) - positions.getZ(a)) - (positions.getZ(b) - positions.getZ(a)) * (positions.getX(c) - positions.getX(a))) / 2;
  }
  assert.ok(Math.abs(area - 9900) < 0.1, `a small hole was lost: rendered area ${area}`);
  assert.ok(mesh.index!.count > positions.count, "surface should reuse indexed DEM vertices");
  mesh.dispose();
});

test("unsupported DEM cells stay absent instead of filling with zero-height land", () => {
  const mesh = parkGeometry([park], { ...hill, elevationsM: [0, 0, 0, 0, null, 0, 0, 0, 0] });
  assert.equal(mesh.index?.count, 0);
  mesh.dispose();
});

test("buildings use the same DEM base and preserve physical height when ground is exaggerated", () => {
  const building: Building = { id: "hill-building", bin: null, bbl: null, address: null, name: null, center: unprojectMeters([50, 50]), footprint: [[[40, 40], [60, 40], [60, 60], [40, 60], [40, 40]].map((point) => unprojectMeters(point as [number, number]))], heightM: 30, groundElevationM: 999, neighborhoodId: "test", yearBuilt: null, featureCode: "2100" };
  assert.equal(buildingGroundElevation(building, hill), 20);
  const actual = buildingGeometry([building], { terrain: hill }).geometry;
  const exaggerated = buildingGeometry([building], { terrain: hill, verticalScale: 3 }).geometry;
  assert.ok(Math.abs(actual.getAttribute("position").getY(0) - 50.2) < 0.001);
  assert.ok(Math.abs(exaggerated.getAttribute("position").getY(0) - 90.2) < 0.001);
  assert.ok(Math.abs((exaggerated.boundingBox?.max.y ?? 0) - 60.2 - 30) < 0.001, "building height was exaggerated with the ground");
  const groundStart = 4;
  for (let i = 0; i < 4; i++) assert.ok(Math.abs(exaggerated.getAttribute("position").getY(groundStart + i) - terrainElevation(building.footprint[0][i], hill)! * 3) < 0.001);
  actual.dispose(); exaggerated.dispose();
});

test("boundary lines sample hills between original polygon vertices", () => {
  const geometry = { type: "Polygon" as const, coordinates: [[[0, 50], [100, 50], [100, 60], [0, 60], [0, 50]].map((point) => unprojectMeters(point as [number, number]))] };
  const mesh = outlineGeometry(geometry, hill, 4, 3);
  assert.ok((mesh.boundingBox?.max.y ?? 0) >= 64);
  mesh.dispose();
});

test("the measured Central Park cache produces interior park relief and slope normals", () => {
  const detail = JSON.parse(readFileSync(new URL("../public/manhattan/neighborhoods/MN6491.json", import.meta.url), "utf8")) as NeighborhoodDetail;
  const mesh = parkGeometry(detail.parks, detail.terrain);
  assert.ok((mesh.boundingBox?.max.y ?? 0) - (mesh.boundingBox?.min.y ?? 0) > 25, "measured park relief was flattened");
  assert.ok(mesh.getAttribute("position").count > 1000);
  const normals = mesh.getAttribute("normal");
  assert.ok(Array.from({ length: normals.count }, (_, i) => Math.abs(normals.getX(i))).some((x) => x > 0.05));
  mesh.dispose();
});
