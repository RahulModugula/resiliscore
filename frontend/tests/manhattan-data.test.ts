import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";
import { MANHATTAN_ORIGIN, boundsCenter, geometryBounds, pointInGeometry, projectLngLat, unprojectMeters } from "../src/lib/manhattan/geo";
import type { Geometry, ManhattanManifest, ManhattanOverview, Neighborhood, NeighborhoodDetail } from "../src/lib/manhattan/types";

const directory = join(process.cwd(), "public");
function read<T>(url: string): T { return JSON.parse(readFileSync(join(directory, url), "utf8")); }

test("Manhattan coordinate projection preserves real coordinates and metre scale", () => {
  assert.deepEqual(projectLngLat(MANHATTAN_ORIGIN), [0, 0]);
  for (const point of [[-74.0134, 40.7116], [-73.9286, 40.8677]] as [number, number][]) {
    const roundtrip = unprojectMeters(projectLngLat(point));
    assert.ok(Math.abs(roundtrip[0] - point[0]) < 1e-10);
    assert.ok(Math.abs(roundtrip[1] - point[1]) < 1e-10);
  }
  const [east, north] = projectLngLat([-73.9702, 40.7841]);
  assert.ok(east > 80 && east < 90);
  assert.ok(north > 110 && north < 112);
});

test("polygon containment excludes holes and supports detached islands", () => {
  const geometry: Geometry = { type: "MultiPolygon", coordinates: [[[[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]], [[1, 1], [2, 1], [2, 2], [1, 2], [1, 1]]], [[[8, 8], [9, 8], [9, 9], [8, 9], [8, 8]]]] };
  assert.equal(pointInGeometry([0.5, 0.5], geometry), true);
  assert.equal(pointInGeometry([1.5, 1.5], geometry), false);
  assert.equal(pointInGeometry([8.5, 8.5], geometry), true);
  assert.deepEqual(geometryBounds(geometry), [0, 0, 9, 9]);
  assert.deepEqual(boundsCenter([0, 0, 9, 9]), [4.5, 4.5]);
});

test("the bundled source cache covers every Manhattan NTA with real unique footprints", () => {
  const manifest = read<ManhattanManifest>("/manhattan/manifest.json");
  const neighborhoods = read<Neighborhood[]>(manifest.neighborhoodsUrl);
  assert.equal(neighborhoods.length, 38);
  assert.equal(manifest.counts.neighborhoods, neighborhoods.length);
  assert.ok(manifest.counts.buildings > 40000);
  assert.ok(manifest.counts.parks > 250);
  assert.equal(manifest.sources.length, 6);
  const ids = new Set<string>();
  let count = 0;
  for (const neighborhood of neighborhoods) {
    assert.match(neighborhood.id, /^MN/);
    assert.deepEqual(geometryBounds(neighborhood.geometry), neighborhood.bounds);
    const detail = read<NeighborhoodDetail>(manifest.details[neighborhood.id]);
    assert.equal(detail.neighborhoodId, neighborhood.id);
    assert.equal(detail.terrain.elevationsM.length, detail.terrain.width * detail.terrain.height);
    assert.ok(detail.terrain.elevationsM.every((value) => value === null || Number.isFinite(value)));
    for (const building of detail.buildings) {
      assert.equal(building.neighborhoodId, neighborhood.id);
      assert.equal(ids.has(building.id), false);
      ids.add(building.id);
      assert.ok(building.footprint[0].length >= 4);
      assert.notEqual(building.featureCode, "1003");
      assert.ok(building.heightM === null || building.heightM > 0);
      assert.ok(building.groundElevationM === null || Number.isFinite(building.groundElevationM));
      assert.equal(building.address, null);
    }
    count += detail.buildings.length;
  }
  assert.equal(count, manifest.counts.buildings);
  const overview = read<ManhattanOverview>(manifest.overviewUrl);
  assert.equal(overview.buildings.length, count);
  assert.ok(overview.buildings.every((building) => ids.has(building.id)));
  assert.ok(overview.terrain.elevationsM.some((value) => value === null));
  const known = overview.terrain.elevationsM.filter((value): value is number => value !== null);
  assert.ok(Math.max(...known) - Math.min(...known) > 40, "Measured terrain must preserve Manhattan elevation variation");
  assert.ok(overview.infrastructure && overview.infrastructure.stormDrains.length > 5000);
  assert.equal(overview.infrastructure.sewerAvailability, "partial");
  assert.ok(overview.infrastructure.sewerLines.length > 5);
  assert.ok(overview.infrastructure.sewerLines.every((line) => line.depthM === null && line.coordinates.length >= 2));
  assert.ok(overview.infrastructure.stormDrains.every((drain) => drain.depthM === null));
  assert.ok(overview.parks.some((park) => /Central Park/i.test(park.name)));
});
