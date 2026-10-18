import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { blockBuildingPlacement } from "../src/lib/manhattan/blockElevation";
import { loadBuildingContext } from "../src/lib/manhattan/blockContext";
import { decodePrototypeElevation, hasPrototypeTerrain, loadPrototypeElevation } from "../src/lib/manhattan/prototypeElevation";
import { buildingGeometry, terrainElevation, terrainGeometry } from "../src/lib/manhattan/sceneGeometry";
import type { Bounds, LngLat, Neighborhood } from "../src/lib/manhattan/types";

test("2021 prototype keeps the disputed noise out of terrain and unknown ground out of building-centre measurements", async () => {
  const manifest = JSON.parse(await readFile("public/manhattan/prototypes/nyc2021-murray-hill.json", "utf8"));
  const bytes = new Uint8Array(await readFile("public/manhattan/prototypes/nyc2021-murray-hill.tif")).buffer;
  await assert.rejects(decodePrototypeElevation(bytes, { ...manifest, elevationUnit: "foot" }), /metadata/);
  const corrupt = bytes.slice(0); new Uint8Array(corrupt)[100] ^= 1;
  await assert.rejects(decodePrototypeElevation(corrupt, manifest), /checksum/);
  const terrain = await decodePrototypeElevation(bytes, manifest);
  const pit: LngLat = [-73.97495797901215, 40.7425999087431];
  assert.ok(terrainElevation(pit, terrain)! > 6 && terrainElevation(pit, terrain)! < 6.3);
  assert.equal(terrainElevation([-73.9754964, 40.7439658], terrain), null);
  assert.ok(terrain.elevationsM.some(h => h === null), "unsupported cells must remain unknown");
  assert.equal(terrain.raster?.resampling, "linear-TIN");
  assert.equal(terrain.raster?.sourceResolutionM, null, "irregular point data must not claim a native raster resolution");
  const original = globalThis.fetch, requests: string[] = [];
  globalThis.fetch = async path => { requests.push(String(path)); return new Response(await readFile(`public${path}`)); };
  try {
    const context = await loadBuildingContext({ id: "1112075", neighborhoodId: "MN0603" });
    const loaded = await loadPrototypeElevation(context.terrain.bounds);
    const count = requests.length;
    assert.equal(await loadPrototypeElevation(context.terrain.bounds), loaded);
    assert.equal(requests.length, count, "revisiting prototype terrain must reuse its decoded grid");
    await assert.rejects(loadPrototypeElevation([-74.1, 40.7, -74, 40.8]), /does not cover/);
    const cancelled = new AbortController(); cancelled.abort();
    await assert.rejects(loadPrototypeElevation(context.terrain.bounds, cancelled.signal), { name: "AbortError" });
    const before = structuredClone(context.selected);
    const placement = blockBuildingPlacement(context.selected, loaded);
    assert.ok(placement.range.known > 0);
    assert.equal(placement.range.known, 43);
    assert.equal(placement.range.total, 191);
    assert.equal(placement.conflict, false);
    assert.deepEqual(context.selected, before);
    const geometry = buildingGeometry([placement.geometryBuilding], { terrain: loaded, groundAt: () => placement.groundM }).geometry;
    assert.ok(Math.abs(geometry.getAttribute("position").getY(0) - (placement.groundM! + before.heightM! + .2)) < 1e-4);
    assert.ok(Array.from(geometry.getAttribute("position").array).every(Number.isFinite)); geometry.dispose();
    const bounds: Bounds = loaded.bounds, [w,s,e,n] = bounds;
    const rectangle: Neighborhood = { id:"prototype", name:"Prototype", type:"0", bounds, center:[(w+e)/2,(s+n)/2],
      geometry:{type:"Polygon",coordinates:[[[w,s],[e,s],[e,n],[w,n],[w,s]]]}};
    const land = terrainGeometry(loaded, [rectangle]);
    assert.ok(land.getIndex()!.count > 0);
    assert.ok(Array.from(land.getAttribute("position").array).every(Number.isFinite)); land.dispose();
    assert.equal(hasPrototypeTerrain("1112075"), true);
    assert.equal(hasPrototypeTerrain("441"), false);
    assert.equal(context.buildings.length, 54);
    const originalBuildings = structuredClone(context.buildings);
    const sourceGroundFallback: string[] = [];
    for (const building of context.buildings) {
      const placed = blockBuildingPlacement(building, loaded);
      if (!placed.range.known) { sourceGroundFallback.push(building.id); assert.equal(placed.groundM, building.groundElevationM); assert.notEqual(placed.groundM, null); }
      if (!placed.conflict) assert.equal(placed.geometryBuilding.heightM, building.heightM);
      if (placed.roofM !== null && building.heightM !== null) assert.ok(Math.abs(placed.roofM - placed.groundM! - .2 - building.heightM) < 1e-10);
    }
    assert.deepEqual(sourceGroundFallback.sort(), ["147888", "333955", "582861", "624579", "803801"]);
    assert.deepEqual(context.buildings, originalBuildings);
  } finally { globalThis.fetch = original; }
});
