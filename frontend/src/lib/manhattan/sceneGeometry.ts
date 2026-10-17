import { BufferGeometry, Color, Float32BufferAttribute, ShapeUtils, Vector2 } from "three";
import { geometryPolygons, pointInGeometry, projectLngLat } from "./geo";
import type { Bounds, Building, Geometry, LngLat, Neighborhood, Park, TerrainGrid } from "./types";

type Point = [number, number, number];

/** Geographic north maps to -Z. All world distances, including elevation, are metres. */
export function worldPoint(point: LngLat, elevation = 0): Point {
  const [east, north] = projectLngLat(point);
  return [east, elevation, -north];
}

export function terrainElevation(point: LngLat, terrain?: TerrainGrid | null): number | null {
  if (!terrain || terrain.width < 2 || terrain.height < 2) return null;
  const [w, s, e, n] = terrain.bounds;
  const x = (point[0] - w) / (e - w) * (terrain.width - 1);
  const y = (point[1] - s) / (n - s) * (terrain.height - 1);
  if (x < 0 || y < 0 || x > terrain.width - 1 || y > terrain.height - 1) return null;
  const x0 = Math.min(Math.floor(x), terrain.width - 2);
  const y0 = Math.min(Math.floor(y), terrain.height - 2);
  const samples = [terrain.elevationsM[y0 * terrain.width + x0], terrain.elevationsM[y0 * terrain.width + x0 + 1], terrain.elevationsM[(y0 + 1) * terrain.width + x0], terrain.elevationsM[(y0 + 1) * terrain.width + x0 + 1]];
  if (samples.some((sample) => sample == null)) return null;
  const [a, b, c, d] = samples as number[];
  return a * (1 - (x - x0)) * (1 - (y - y0)) + b * (x - x0) * (1 - (y - y0)) + c * (1 - (x - x0)) * (y - y0) + d * (x - x0) * (y - y0);
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
export function buildingGeometry(buildings: Building[]) {
  const positions: number[] = [];
  const colors: number[] = [];
  const indices: number[] = [];
  const triangleEnds: number[] = [];
  const base = new Color("#c8cebf");
  const tall = new Color("#eff0d9");
  for (const building of buildings) {
    const { rings, points, faces } = polygonTriangles(building.footprint);
    const ground = building.groundElevationM ?? 0;
    // Missing height stays a flat footprint. Never infer a storey count or a roof height.
    const roof = ground + (building.heightM ?? 0) + 0.2;
    const roofStart = positions.length / 3;
    for (const point of points) positions.push(...worldPoint(point, roof));
    for (const [a, b, c] of faces) indices.push(roofStart + a, roofStart + b, roofStart + c);
    if (building.heightM != null && building.heightM > 0) {
      const groundStart = positions.length / 3;
      for (const point of points) positions.push(...worldPoint(point, ground));
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

export function outlineGeometry(geometry: Geometry, terrain?: TerrainGrid | null, lift = 4) {
  const positions: number[] = [];
  for (const polygon of geometryPolygons(geometry)) for (const sourceRing of polygon) {
    const ring = openRing(sourceRing);
    for (let i = 0; i < ring.length; i++) {
      const a = ring[i];
      const b = ring[(i + 1) % ring.length];
      positions.push(...worldPoint(a, (terrainElevation(a, terrain) ?? 0) + lift), ...worldPoint(b, (terrainElevation(b, terrain) ?? 0) + lift));
    }
  }
  return geometryFromPositions(positions);
}

export function parkGeometry(parks: Park[], terrain?: TerrainGrid | null) {
  const positions: number[] = [];
  for (const park of parks) {
    const geometry = polygonGeometry(park.geometry, (point) => (terrainElevation(point, terrain) ?? 0) + 0.7);
    for (const coordinate of geometry.getAttribute("position").array) positions.push(coordinate);
    geometry.dispose();
  }
  return geometryFromPositions(positions);
}

/** Unsupported grid cells are omitted, and coastline masking keeps water at the datum. */
export function terrainGeometry(terrain: TerrainGrid, neighborhoods: Neighborhood[]) {
  const positions: number[] = [];
  const [w, s, e, n] = terrain.bounds;
  const lngLat = (x: number, y: number): LngLat => [w + x / (terrain.width - 1) * (e - w), s + y / (terrain.height - 1) * (n - s)];
  const isLand = (point: LngLat) => neighborhoods.some(({ bounds, geometry }) => point[0] >= bounds[0] && point[0] <= bounds[2] && point[1] >= bounds[1] && point[1] <= bounds[3] && pointInGeometry(point, geometry));
  for (let y = 0; y < terrain.height - 1; y++) for (let x = 0; x < terrain.width - 1; x++) {
    const points = [lngLat(x, y), lngLat(x + 1, y), lngLat(x, y + 1), lngLat(x + 1, y + 1)];
    const heights = [terrain.elevationsM[y * terrain.width + x], terrain.elevationsM[y * terrain.width + x + 1], terrain.elevationsM[(y + 1) * terrain.width + x], terrain.elevationsM[(y + 1) * terrain.width + x + 1]];
    if (heights.some((height) => height == null)) continue;
    for (const face of [[0, 1, 2], [1, 3, 2]]) {
      const center: LngLat = [face.reduce((sum, i) => sum + points[i][0], 0) / 3, face.reduce((sum, i) => sum + points[i][1], 0) / 3];
      if (!isLand(center) || !face.every((index) => isLand(points[index]))) continue;
      triangle(positions, worldPoint(points[face[0]], heights[face[0]]!), worldPoint(points[face[1]], heights[face[1]]!), worldPoint(points[face[2]], heights[face[2]]!));
    }
  }
  return geometryFromPositions(positions);
}

export function combineBounds(neighborhoods: Neighborhood[]): Bounds {
  if (!neighborhoods.length) return [-74.03, 40.68, -73.9, 40.89];
  return neighborhoods.reduce<Bounds>((bounds, { bounds: next }) => [Math.min(bounds[0], next[0]), Math.min(bounds[1], next[1]), Math.max(bounds[2], next[2]), Math.max(bounds[3], next[3])], [Infinity, Infinity, -Infinity, -Infinity]);
}

/** Fit the complete bounds at any viewport aspect, with an oblique south-east viewpoint. */
export function cameraFrame(bounds: Bounds, aspect: number) {
  const a = worldPoint([bounds[0], bounds[1]]);
  const b = worldPoint([bounds[2], bounds[3]]);
  const center: Point = [(a[0] + b[0]) / 2, 0, (a[2] + b[2]) / 2];
  const radius = Math.max(Math.hypot(a[0] - b[0], a[2] - b[2]) / 2, 130);
  const vertical = 38 * Math.PI / 180;
  const horizontal = 2 * Math.atan(Math.tan(vertical / 2) * Math.max(aspect, 0.2));
  const distance = radius / Math.sin(Math.min(vertical, horizontal) / 2) * 1.07;
  const offset = [0.35, 0.8, 0.75];
  const length = Math.hypot(...offset);
  return { target: center, position: offset.map((value, index) => center[index] + value / length * distance) as Point, distance };
}
