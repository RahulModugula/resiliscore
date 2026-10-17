import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { DynamicDrawUsage, Mesh, MeshBasicMaterial, Raycaster, Vector3, DoubleSide, BufferAttribute } from "three";
import { CENTER, MeshBVH, acceleratedRaycast } from "three-mesh-bvh";
import { buildingAtFace, buildingGeometry, outlineGeometry, terrainGeometry, worldPoint } from "../src/lib/manhattan/sceneGeometry";
import { updateGroundScale } from "../src/lib/manhattan/geometryUpdates";
import { terrainSurface, updateTerrainColors } from "../src/lib/manhattan/terrainSurface";
import type { Neighborhood, NeighborhoodDetail } from "../src/lib/manhattan/types";

const detail = JSON.parse(readFileSync(new URL("../public/manhattan/neighborhoods/MN0101.json", import.meta.url), "utf8")) as NeighborhoodDetail;
const neighborhoods = JSON.parse(readFileSync(new URL("../public/manhattan/neighborhoods.json", import.meta.url), "utf8")) as Neighborhood[];
const neighborhood = neighborhoods.find(n => n.id === detail.neighborhoodId)!;

function sameGeometry(actual: ReturnType<typeof terrainSurface>, expected: ReturnType<typeof terrainSurface>) {
  for (const name of ["position", "normal", "color"]) {
    if (actual.getAttribute(name)) assert.deepEqual(actual.getAttribute(name).array, expected.getAttribute(name).array, `${name} changed from reference`);
  }
  assert.deepEqual(actual.index?.array, expected.index?.array);
  expected.dispose();
}

test("terrain modes and relief reuse attributes and match newly generated reference geometry", () => {
  const geometry = terrainGeometry(detail.terrain, [neighborhood]);
  const attributes = { ...geometry.attributes }, index = geometry.index;
  geometry.boundsTree = new MeshBVH(geometry, { ...{ indirect: true }, strategy: CENTER });
  const tree = geometry.boundsTree;
  for (const scale of [3, 1, 3, 1]) {
    updateGroundScale(geometry, scale);
    for (const mode of [true, false]) {
      updateTerrainColors(geometry, mode);
      sameGeometry(geometry, terrainGeometry(detail.terrain, [neighborhood], { verticalScale: scale, showTerrain: mode }));
    }
  }
  for (const [name, attribute] of Object.entries(attributes)) assert.equal(geometry.getAttribute(name), attribute);
  assert.equal(geometry.index, index);
  assert.equal(geometry.boundsTree, tree);
  assert.equal((geometry.getAttribute("position") as BufferAttribute).usage, DynamicDrawUsage);
  assert.equal((geometry.getAttribute("color") as BufferAttribute).usage, DynamicDrawUsage);
  geometry.dispose();
});

test("building relief retains heights, triangle order, buffers and accelerated picking", () => {
  const result = buildingGeometry(detail.buildings, { terrain: detail.terrain });
  const geometry = result.geometry;
  const position = geometry.getAttribute("position"), normal = geometry.getAttribute("normal"), index = geometry.index;
  geometry.boundsTree = new MeshBVH(geometry, { ...{ indirect: true }, strategy: CENTER });
  const tree = geometry.boundsTree;
  const tower = detail.buildings.reduce((a, b) => (a.heightM ?? 0) > (b.heightM ?? 0) ? a : b);
  const material = new MeshBasicMaterial({ side: DoubleSide });
  const mesh = new Mesh(geometry, material);
  mesh.raycast = acceleratedRaycast;
  const raycaster = new Raycaster(); raycaster.firstHitOnly = true;
  for (const scale of [3, 1]) {
    updateGroundScale(geometry, scale);
    sameGeometry(geometry, buildingGeometry(detail.buildings, { terrain: detail.terrain, verticalScale: scale }).geometry);
    raycaster.set(new Vector3(...worldPoint(tower.center, 5000)), new Vector3(0, -1, 0));
    const hit = raycaster.intersectObject(mesh)[0];
    assert.ok(hit && hit.faceIndex != null, "roof could not be picked after BVH refit");
    assert.equal(detail.buildings[buildingAtFace(hit.faceIndex, result.triangleEnds)].id, tower.id);
  }
  assert.equal(geometry.getAttribute("position"), position);
  assert.equal(geometry.getAttribute("normal"), normal);
  assert.equal(geometry.index, index);
  assert.equal(geometry.boundsTree, tree);
  geometry.dispose(); material.dispose();
});

test("park lift and neighborhood boundary lift survive repeated ground scale changes", () => {
  const geometries = detail.parks.map(p => p.geometry);
  const parks = terrainSurface(detail.terrain, geometries, { color: "#4d8066", lift: .06, include: neighborhood.geometry });
  const border = outlineGeometry(neighborhood.geometry, detail.terrain);
  for (const scale of [3, 1]) {
    updateGroundScale(parks, scale); updateTerrainColors(parks, true, "#4d8066");
    sameGeometry(parks, terrainSurface(detail.terrain, geometries, { color: "#4d8066", lift: .06, include: neighborhood.geometry, verticalScale: scale, showTerrain: true }));
    for (const lift of [7, 4]) {
      updateGroundScale(border, scale, lift);
      sameGeometry(border, outlineGeometry(neighborhood.geometry, detail.terrain, lift, scale));
    }
  }
  parks.dispose(); border.dispose();
});
