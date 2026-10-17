import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";
import { pointInGeometry, projectLngLat } from "../src/lib/manhattan/geo";
import type { LngLat, ManhattanManifest, ManhattanOverview, Neighborhood, NeighborhoodDetail, TerrainGrid } from "../src/lib/manhattan/types";

const directory = join(process.cwd(), "public", "manhattan");
const read = <T>(path: string): T => JSON.parse(readFileSync(join(directory, path), "utf8"));
const full = read<TerrainGrid>("terrain-10m.json");
const neighborhoods = read<Neighborhood[]>("neighborhoods.json");
const epsilon = (actual: number, expected: number) => assert.ok(Math.abs(actual - expected) < 1e-8, `${actual} differs from ${expected}`);

function position(grid: TerrainGrid, col: number, row: number): LngLat {
  return [grid.bounds[0] + col * (grid.bounds[2] - grid.bounds[0]) / (grid.width - 1), grid.bounds[1] + row * (grid.bounds[3] - grid.bounds[1]) / (grid.height - 1)];
}

test("DEM metadata uses exact pixel centers, metre units and one common geographic grid", () => {
  assert.ok(full.raster);
  assert.equal(full.raster.dataset, "USGS_3DEP_1M");
  assert.equal(full.raster.verticalDatum, "NAVD88");
  assert.equal(full.raster.elevationUnit, "metre");
  assert.equal(full.raster.sourceResolutionM, 1);
  assert.equal(full.raster.nominalSpacingM, 10);
  assert.equal(full.raster.sampleLocation, "pixel-center");
  assert.equal(full.raster.rowOrder, "south-to-north");
  assert.equal(full.elevationsM.length, full.width * full.height);
  const [dx, dy] = full.raster.cellSizeDegrees;
  epsilon(full.bounds[0], full.raster.extent[0] + dx / 2);
  epsilon(full.bounds[1], full.raster.extent[1] + dy / 2);
  epsilon(full.bounds[2], full.raster.extent[2] - dx / 2);
  epsilon(full.bounds[3], full.raster.extent[3] - dy / 2);
  const southwest = projectLngLat(position(full, 0, 0));
  const adjacent = projectLngLat(position(full, 1, 1));
  epsilon(adjacent[0] - southwest[0], 10);
  epsilon(adjacent[1] - southwest[1], 10);
  assert.ok(full.elevationsM.some(value => value === null));
  assert.ok(full.elevationsM.every(value => value === null || Number.isFinite(value)));
});

test("every neighborhood crop and the overview retain shared DEM samples without seams", () => {
  const [dx, dy] = full.raster!.cellSizeDegrees;
  for (const neighborhood of neighborhoods) {
    const { terrain } = read<NeighborhoodDetail>(`neighborhoods/${neighborhood.id}.json`);
    assert.equal(terrain.raster?.nominalSpacingM, 10);
    const col = Math.round((terrain.bounds[0] - full.bounds[0]) / dx);
    const row = Math.round((terrain.bounds[1] - full.bounds[1]) / dy);
    epsilon(terrain.bounds[0], full.bounds[0] + col * dx);
    epsilon(terrain.bounds[1], full.bounds[1] + row * dy);
    assert.ok(terrain.bounds[0] <= neighborhood.bounds[0] && terrain.bounds[1] <= neighborhood.bounds[1]);
    assert.ok(terrain.bounds[2] >= neighborhood.bounds[2] && terrain.bounds[3] >= neighborhood.bounds[3]);
    for (let y = 0; y < terrain.height; y += 11) for (let x = 0; x < terrain.width; x += 13) {
      assert.equal(terrain.elevationsM[y * terrain.width + x], full.elevationsM[(row + y) * full.width + col + x]);
    }
  }
  const overview = read<ManhattanOverview>("overview.json").terrain;
  assert.equal(overview.raster?.nominalSpacingM, 50);
  for (let y = 0; y < overview.height; y++) for (let x = 0; x < overview.width; x++) {
    assert.equal(overview.elevationsM[y * overview.width + x], full.elevationsM[y * 5 * full.width + x * 5]);
  }
});

for (const [name, minimumRelief, minimumInteriorSamples] of [["Central Park", 30, 30000], ["Inwood Hill Park", 60, 8000]] as const) {
  test(`${name} preserves measured interior relief independent of building observations`, () => {
    const neighborhood = neighborhoods.find(item => item.name === name)!;
    const { terrain } = read<NeighborhoodDetail>(`neighborhoods/${neighborhood.id}.json`);
    const elevations: number[] = [];
    for (let row = 0; row < terrain.height; row++) for (let col = 0; col < terrain.width; col++) {
      const value = terrain.elevationsM[row * terrain.width + col];
      if (value !== null && pointInGeometry(position(terrain, col, row), neighborhood.geometry)) elevations.push(value);
    }
    assert.ok(elevations.length > minimumInteriorSamples);
    assert.ok(Math.max(...elevations) - Math.min(...elevations) > minimumRelief);
    assert.match(terrain.source, /USGS 3DEP.*bare-earth/);
    assert.doesNotMatch(terrain.source, /IDW|building-base/);
  });
}

test("DEM provenance pins raw source raster, native NAVD88 tiles and unrendered elevations", () => {
  const manifest = read<ManhattanManifest>("manifest.json");
  assert.equal(manifest.terrainUrl, "/manhattan/terrain-10m.json");
  const provenance = read<{ sha256: string; nativeSources: { VerticalDatum: string; title: string }[]; request: { params: { renderingRule: string; pixelType: string; interpolation: string } } }>("dem-provenance.json");
  assert.match(provenance.sha256, /^[a-f0-9]{64}$/);
  assert.ok(provenance.nativeSources.length > 0);
  assert.ok(provenance.nativeSources.every(source => source.VerticalDatum === "North American Vertical Datum of 1988 (NAVD 88)" && /meter/i.test(source.title)));
  assert.deepEqual(JSON.parse(provenance.request.params.renderingRule), { rasterFunction: "None" });
  assert.equal(provenance.request.params.pixelType, "F32");
  assert.equal(provenance.request.params.interpolation, "RSP_NearestNeighbor");
});
