import { BufferGeometry, Color, Float32BufferAttribute, ShapeUtils, Vector2 } from "three";
import { geometryPolygons, projectLngLat } from "./geo";
import type { Bounds, Building, Geometry, LngLat, Neighborhood, Park, TerrainGrid } from "./types";

import { sampleTerrain, terrainSurface } from "./terrainSurface";
export { TERRAIN_PALETTE } from "./terrainSurface";

type Point = [number, number, number];

/** Geographic north maps to -Z. All world distances, including elevation, are metres. */
export function worldPoint(point: LngLat, elevation = 0): Point {
  const [east, north] = projectLngLat(point);
  return [east, elevation, -north];
}

export const terrainElevation = sampleTerrain;

export function buildingGroundElevation(building: Building, terrain?: TerrainGrid | null): number | null {
  return terrainElevation(building.center, terrain) ?? building.groundElevationM;
}

export interface BuildingGeometryOptions {
  terrain?: TerrainGrid | null;
  terrainAt?: (point: LngLat) => TerrainGrid | null | undefined;
  verticalScale?: number;
}

function openRing(ring: LngLat[]): LngLat[] {
  if (ring.length < 2) return ring;
  const last = ring[ring.length - 1];
  return ring[0][0] === last[0] && ring[0][1] === last[1] ? ring.slice(0, -1) : ring;
}

function polygonTriangles(rings: LngLat[][]) {
  const clean = rings.map(openRing).filter((ring) => ring.length >= 3);
  if (!clean.length) return { rings: [], points: [], faces: [] };
  const projected = clean.map((ring) => ring.map((point) => {
    const [east, north] = projectLngLat(point);
    return new Vector2(east, north);
  }));
  return { rings: clean, points: clean.flat(), faces: ShapeUtils.triangulateShape(projected[0], projected.slice(1)) };
}

function geometryFromPositions(positions: number[], colors?: number[], indices?: number[]) {
  const geometry = new BufferGeometry();
  geometry.setAttribute("position", new Float32BufferAttribute(positions, 3));
  if (colors) geometry.setAttribute("color", new Float32BufferAttribute(colors, 3));
  if (indices) geometry.setIndex(indices);
  geometry.computeVertexNormals();
  geometry.computeBoundingBox();
  geometry.computeBoundingSphere();
  return geometry;
}

function triangle(positions: number[], a: Point, b: Point, c: Point) {
  positions.push(...a, ...b, ...c);
}

/** One mesh and one draw call for real building footprints; triangle ranges retain picking IDs. */
export function buildingGeometry(buildings: Building[], options: BuildingGeometryOptions = {}) {
  const verticalScale = options.verticalScale ?? 1;
  const gridAt = (point: LngLat) => options.terrainAt?.(point) ?? options.terrain;
  const positions: number[] = [];
  const colors: number[] = [];
  const indices: number[] = [];
  const triangleEnds: number[] = [];
  const base = new Color("#c8cebf");
  const tall = new Color("#eff0d9");
  for (const building of buildings) {
    const { rings, points, faces } = polygonTriangles(building.footprint);
    const ground = buildingGroundElevation(building, gridAt(building.center)) ?? 0;
    // Missing height stays a flat footprint. Never infer a storey count or a roof height.
    const roof = ground * verticalScale + (building.heightM ?? 0) + 0.2;
    const roofStart = positions.length / 3;
    for (const point of points) positions.push(...worldPoint(point, building.heightM == null ? (terrainElevation(point, gridAt(point)) ?? ground) * verticalScale + 0.2 : roof));
    for (const [a, b, c] of faces) indices.push(roofStart + a, roofStart + b, roofStart + c);
    if (building.heightM != null && building.heightM > 0) {
      const groundStart = positions.length / 3;
      for (const point of points) positions.push(...worldPoint(point, (terrainElevation(point, gridAt(point)) ?? ground) * verticalScale));
      let ringStart = 0;
      for (const ring of rings) for (let i = 0; i < ring.length; i++) {
        const a = ringStart + i;
        const b = ringStart + (i + 1) % ring.length;
        indices.push(groundStart + a, groundStart + b, roofStart + a, groundStart + b, roofStart + b, roofStart + a);
        if (i === ring.length - 1) ringStart += ring.length;
      }
    }
    const color = base.clone().lerp(tall, Math.min((building.heightM ?? 0) / 300, 1));
    for (let i = roofStart; i < positions.length / 3; i++) colors.push(color.r, color.g, color.b);
    triangleEnds.push(indices.length / 3);
  }
  return { geometry: geometryFromPositions(positions, colors, indices), triangleEnds };
}

/** Binary lookup keeps a merged city mesh interactive without one React node per property. */
export function buildingAtFace(faceIndex: number, triangleEnds: number[]): number {
  let low = 0;
  let high = triangleEnds.length;
  while (low < high) {
    const middle = (low + high) >>> 1;
    if (faceIndex < triangleEnds[middle]) high = middle;
    else low = middle + 1;
  }
  return low < triangleEnds.length && faceIndex >= 0 ? low : -1;
}

export function polygonGeometry(geometry: Geometry, elevation: (point: LngLat) => number) {
  const positions: number[] = [];
  for (const polygon of geometryPolygons(geometry)) {
    const { points, faces } = polygonTriangles(polygon);
    for (const [a, b, c] of faces) triangle(positions, worldPoint(points[a], elevation(points[a])), worldPoint(points[b], elevation(points[b])), worldPoint(points[c], elevation(points[c])));
  }
  return geometryFromPositions(positions);
}

export function outlineGeometry(geometry: Geometry, terrain?: TerrainGrid | null, lift = 4, verticalScale = 1) {
  const positions: number[] = [];
  const stepM = terrain ? Math.max(1, Math.min(Math.abs(projectLngLat([terrain.bounds[2], terrain.bounds[1]])[0] - projectLngLat([terrain.bounds[0], terrain.bounds[1]])[0]) / (terrain.width - 1), Math.abs(projectLngLat([terrain.bounds[0], terrain.bounds[3]])[1] - projectLngLat([terrain.bounds[0], terrain.bounds[1]])[1]) / (terrain.height - 1))) : Infinity;
  for (const polygon of geometryPolygons(geometry)) for (const sourceRing of polygon) {
    const ring = openRing(sourceRing);
    for (let i = 0; i < ring.length; i++) {
      const a = ring[i], b = ring[(i + 1) % ring.length];
      const pa = projectLngLat(a), pb = projectLngLat(b);
      const steps = Math.max(1, Math.ceil(Math.hypot(pa[0] - pb[0], pa[1] - pb[1]) / stepM));
      for (let j = 0; j < steps; j++) {
        const first: LngLat = [a[0] + (b[0] - a[0]) * j / steps, a[1] + (b[1] - a[1]) * j / steps];
        const second: LngLat = [a[0] + (b[0] - a[0]) * (j + 1) / steps, a[1] + (b[1] - a[1]) * (j + 1) / steps];
        const h1 = terrain ? terrainElevation(first, terrain) : 0, h2 = terrain ? terrainElevation(second, terrain) : 0;
        if (h1 != null && h2 != null) positions.push(...worldPoint(first, h1 * verticalScale + lift), ...worldPoint(second, h2 * verticalScale + lift));
      }
    }
  }
  return geometryFromPositions(positions);
}

export function parkGeometry(parks: Park[], terrain?: TerrainGrid | null, verticalScale = 1) {
  if (!terrain) return geometryFromPositions([]);
  return terrainSurface(terrain, parks.map((park) => park.geometry), { verticalScale, lift: 0.06, color: "#4d8066" });
}

export function terrainGeometry(terrain: TerrainGrid, neighborhoods: Neighborhood[], options: { verticalScale?: number; showTerrain?: boolean } = {}) {
  return terrainSurface(terrain, neighborhoods.map((neighborhood) => neighborhood.geometry), options);
}

export function combineBounds(neighborhoods: Neighborhood[]): Bounds {
  if (!neighborhoods.length) return [-74.03, 40.68, -73.9, 40.89];
  return neighborhoods.reduce<Bounds>((bounds, { bounds: next }) => [Math.min(bounds[0], next[0]), Math.min(bounds[1], next[1]), Math.max(bounds[2], next[2]), Math.max(bounds[3], next[3])], [Infinity, Infinity, -Infinity, -Infinity]);
}

/** Fit the complete bounds at any viewport aspect, with an oblique south-east viewpoint. */
export function cameraFrame(bounds: Bounds, aspect: number, maxElevation = 0) {
  const a = worldPoint([bounds[0], bounds[1]]);
  const b = worldPoint([bounds[2], bounds[3]]);
  const center: Point = [(a[0] + b[0]) / 2, maxElevation / 2, (a[2] + b[2]) / 2];
  const vertical = 38 * Math.PI / 180;
  const horizontal = 2 * Math.atan(Math.tan(vertical / 2) * Math.max(aspect, 0.2));
  const offset = [0.35, 0.8, 0.75];
  const length = Math.hypot(...offset);
  const toward = offset.map((value) => value / length);
  const groundLength = Math.hypot(toward[0], toward[2]);
  const right = [toward[2] / groundLength, 0, -toward[0] / groundLength];
  const up = [-toward[1] * toward[0] / groundLength, groundLength, -toward[1] * toward[2] / groundLength];
  const dot = (point: number[], axis: number[]) => point.reduce((sum, value, index) => sum + value * axis[index], 0);
  let distance = 300;
  // Fit the actual oblique bounding box rather than a loose bounding sphere.
  // Include the supplied skyline height so towers remain inside the camera frame.
  for (const x of [a[0], b[0]]) for (const y of [0, maxElevation]) for (const z of [a[2], b[2]]) {
    const point = [x - center[0], y - center[1], z - center[2]];
    const depth = dot(point, toward);
    distance = Math.max(distance, depth + Math.abs(dot(point, right)) / Math.tan(horizontal / 2), depth + Math.abs(dot(point, up)) / Math.tan(vertical / 2));
  }
  distance *= 1.1;
  return { target: center, position: offset.map((value, index) => center[index] + value / length * distance) as Point, distance };
}
