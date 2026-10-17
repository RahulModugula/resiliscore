import { BufferGeometry, Color, Float32BufferAttribute, ShapeUtils, Vector2 } from "three";
import { difference, intersection, union, type MultiPolygon } from "polygon-clipping";
import { geometryPolygons, projectLngLat } from "./geo";
import type { Geometry, LngLat, TerrainGrid } from "./types";

export const TERRAIN_PALETTE = { low: "#54796b", high: "#c5ae82", minM: 0, maxM: 100 } as const;

/** Matches the SW-SE-NW / SE-NE-NW triangles used by the visible DEM mesh. */
export function sampleTerrain(point: LngLat, terrain?: TerrainGrid | null): number | null {
  if (!terrain || terrain.width < 2 || terrain.height < 2) return null;
  const [w, s, e, n] = terrain.bounds;
  let x = (point[0] - w) / (e - w) * (terrain.width - 1);
  let y = (point[1] - s) / (n - s) * (terrain.height - 1);
  if (x < -1e-7 || y < -1e-7 || x > terrain.width - 1 + 1e-7 || y > terrain.height - 1 + 1e-7) return null;
  x = Math.max(0, Math.min(x, terrain.width - 1));
  y = Math.max(0, Math.min(y, terrain.height - 1));
  if (Math.abs(x - Math.round(x)) < 1e-8 && Math.abs(y - Math.round(y)) < 1e-8) return terrain.elevationsM[Math.round(y) * terrain.width + Math.round(x)] ?? null;
  const x0 = Math.min(Math.floor(x), terrain.width - 2);
  const y0 = Math.min(Math.floor(y), terrain.height - 2);
  const values = [terrain.elevationsM[y0 * terrain.width + x0], terrain.elevationsM[y0 * terrain.width + x0 + 1], terrain.elevationsM[(y0 + 1) * terrain.width + x0], terrain.elevationsM[(y0 + 1) * terrain.width + x0 + 1]];
  if (values.some((value) => value == null)) return null;
  return interpolateTriangle(x - x0, y - y0, values as number[]);
}

function interpolateTriangle(u: number, v: number, [a, b, c, d]: number[]) {
  return u + v <= 1 ? a + (b - a) * u + (c - a) * v : d + (c - d) * (1 - u) + (b - d) * (1 - v);
}

interface SurfaceOptions {
  verticalScale?: number;
  lift?: number;
  color?: string;
  showTerrain?: boolean;
  exclude?: Geometry[];
  include?: Geometry;
}
interface SurfaceLayout { positions: number[]; indices: number[] }
const geometryIds = new WeakMap<Geometry, number>();
let nextGeometryId = 0;
const layouts = new WeakMap<TerrainGrid, Map<string, SurfaceLayout>>();
function id(geometry: Geometry) { let value = geometryIds.get(geometry); if (value == null) { value = ++nextGeometryId; geometryIds.set(geometry, value); } return value; }

function clipSource(geometries: Geometry[], options: SurfaceOptions): MultiPolygon {
  if (!geometries.length) return [];
  const inputs = geometries.map((geometry) => geometryPolygons(geometry));
  let source = union(inputs[0], ...inputs.slice(1));
  if (options.exclude?.length) source = difference(source, ...options.exclude.map(geometryPolygons));
  if (options.include) source = intersection(source, geometryPolygons(options.include));
  return source;
}

/** Build a shared-vertex DEM mesh, clipping only source-boundary cells. NoData stays absent. */
function buildLayout(terrain: TerrainGrid, geometries: Geometry[], options: SurfaceOptions): SurfaceLayout {
  const positions: number[] = [], indices: number[] = [];
  if (terrain.width < 2 || terrain.height < 2) return { positions, indices };
  const source = clipSource(geometries, options);
  if (!source.length) return { positions, indices };
  const [w, s, e, n] = terrain.bounds;
  const dx = (e - w) / (terrain.width - 1), dy = (n - s) / (terrain.height - 1);
  const bounds = source.flat(2).reduce((bounds, point) => [Math.min(bounds[0], (point[0] - w) / dx), Math.min(bounds[1], (point[1] - s) / dy), Math.max(bounds[2], (point[0] - w) / dx), Math.max(bounds[3], (point[1] - s) / dy)], [Infinity, Infinity, -Infinity, -Infinity]);
  const minX = Math.max(0, Math.floor(bounds[0]));
  const maxX = Math.min(terrain.width - 1, Math.ceil(bounds[2]));
  const minY = Math.max(0, Math.floor(bounds[1]));
  const maxY = Math.min(terrain.height - 1, Math.ceil(bounds[3]));
  if (minX >= maxX || minY >= maxY) return { positions, indices };
  const width = maxX - minX + 1, height = maxY - minY + 1;
  const inside = new Uint8Array(width * height);
  const boundary = new Set<number>();
  const rows: number[][] = Array.from({ length: height }, () => []);
  const cellKey = (x: number, y: number) => y * terrain.width + x;
  // Scanline rasterization computes each grid-vertex mask once, rather than point-in-polygon per face.
  for (const polygon of source) for (const ring of polygon) for (let i = 1; i < ring.length; i++) {
    const [ax, ay] = [(ring[i - 1][0] - w) / dx, (ring[i - 1][1] - s) / dy];
    const [bx, by] = [(ring[i][0] - w) / dx, (ring[i][1] - s) / dy];
    for (let y = Math.max(minY, Math.ceil(Math.min(ay, by))); y <= Math.min(maxY, Math.floor(Math.max(ay, by))); y++) {
      if ((ay > y) !== (by > y)) rows[y - minY].push(ax + (y - ay) * (bx - ax) / (by - ay));
    }
    const steps = Math.max(1, Math.ceil(Math.max(Math.abs(bx - ax), Math.abs(by - ay)) * 2));
    for (let step = 0; step <= steps; step++) {
      const x = Math.floor(ax + (bx - ax) * step / steps), y = Math.floor(ay + (by - ay) * step / steps);
      for (let oy = -1; oy <= 1; oy++) for (let ox = -1; ox <= 1; ox++) if (x + ox >= minX && x + ox < maxX && y + oy >= minY && y + oy < maxY) boundary.add(cellKey(x + ox, y + oy));
    }
  }
  for (let y = minY; y <= maxY; y++) {
    const crossings = rows[y - minY].sort((a, b) => a - b);
    for (let i = 0; i + 1 < crossings.length; i += 2) for (let x = Math.max(minX, Math.ceil(crossings[i] - 1e-8)); x <= Math.min(maxX, Math.floor(crossings[i + 1] + 1e-8)); x++) inside[(y - minY) * width + x - minX] = 1;
  }
  const vertexIds = new Map<string, number>();
  function vertex(point: LngLat, elevation: number) {
    const key = `${Math.round((point[0] - w) / dx * 1e8)},${Math.round((point[1] - s) / dy * 1e8)}`;
    let index = vertexIds.get(key);
    if (index == null) {
      index = positions.length / 3;
      vertexIds.set(key, index);
      const [east, north] = projectLngLat(point);
      positions.push(east, elevation, -north);
    }
    return index;
  }
  const tileSize = 16, tiles = new Map<string, MultiPolygon>();
  const coordinate = (x: number, y: number): LngLat => [w + x * dx, s + y * dy];
  function tile(x: number, y: number) {
    const tx = Math.floor(x / tileSize), ty = Math.floor(y / tileSize), key = `${tx},${ty}`;
    let clipped = tiles.get(key);
    if (!clipped) {
      const left = tx * tileSize, bottom = ty * tileSize;
      const ring = [coordinate(left, bottom), coordinate(left + tileSize, bottom), coordinate(left + tileSize, bottom + tileSize), coordinate(left, bottom + tileSize), coordinate(left, bottom)];
      clipped = intersection(source, [ring]);
      tiles.set(key, clipped);
    }
    return clipped;
  }
  for (let y = minY; y < maxY; y++) for (let x = minX; x < maxX; x++) {
    const values = [terrain.elevationsM[y * terrain.width + x], terrain.elevationsM[y * terrain.width + x + 1], terrain.elevationsM[(y + 1) * terrain.width + x], terrain.elevationsM[(y + 1) * terrain.width + x + 1]];
    if (values.some((value) => value == null)) continue;
    const points = [coordinate(x, y), coordinate(x + 1, y), coordinate(x, y + 1), coordinate(x + 1, y + 1)];
    const gridIndices = [0, 1, width, width + 1].map((offset) => (y - minY) * width + x - minX + offset);
    for (const face of [[0, 1, 2], [1, 3, 2]]) {
      if (!boundary.has(cellKey(x, y))) {
        if (face.every((i) => inside[gridIndices[i]])) indices.push(...face.map((i) => vertex(points[i], values[i]!)));
        continue;
      }
      const ring = [...face.map((i) => points[i]), points[face[0]]];
      for (const polygon of intersection(tile(x, y), [ring])) {
        const clean = polygon.map((ring) => ring.slice(0, -1));
        const flat = clean.flat();
        const vectors = clean.map((ring) => ring.map(([lng, lat]) => new Vector2((lng - w) / dx, (lat - s) / dy)));
        for (const triangle of ShapeUtils.triangulateShape(vectors[0], vectors.slice(1))) indices.push(...triangle.map((i) => vertex(flat[i], interpolateTriangle((flat[i][0] - w) / dx - x, (flat[i][1] - s) / dy - y, values as number[]))));
      }
    }
  }
  return { positions, indices };
}

export function terrainSurface(terrain: TerrainGrid, geometries: Geometry[], options: SurfaceOptions = {}) {
  const key = `${geometries.map(id).join(",")}|-${options.exclude?.map(id).join(",") ?? ""}|+${options.include ? id(options.include) : ""}`;
  let cache = layouts.get(terrain);
  if (!cache) { cache = new Map(); layouts.set(terrain, cache); }
  let layout = cache.get(key);
  if (!layout) {
    layout = buildLayout(terrain, geometries, options);
    if (cache.size >= 6) cache.delete(cache.keys().next().value!);
    cache.set(key, layout);
  }
  const positions = Float32Array.from(layout.positions);
  const colors = new Float32Array(positions.length);
  const low = new Color(TERRAIN_PALETTE.low), high = new Color(TERRAIN_PALETTE.high), base = new Color(options.color ?? "#829181");
  const scale = Number.isFinite(options.verticalScale) && options.verticalScale! > 0 ? options.verticalScale! : 1;
  for (let i = 0; i < positions.length; i += 3) {
    const t = Math.max(0, Math.min((positions[i + 1] - TERRAIN_PALETTE.minM) / (TERRAIN_PALETTE.maxM - TERRAIN_PALETTE.minM), 1));
    colors[i] = options.showTerrain ? low.r + (high.r - low.r) * t : base.r;
    colors[i + 1] = options.showTerrain ? low.g + (high.g - low.g) * t : base.g;
    colors[i + 2] = options.showTerrain ? low.b + (high.b - low.b) * t : base.b;
    positions[i + 1] = positions[i + 1] * scale + (options.lift ?? 0);
  }
  const geometry = new BufferGeometry();
  geometry.setAttribute("position", new Float32BufferAttribute(positions, 3));
  geometry.setAttribute("color", new Float32BufferAttribute(colors, 3));
  geometry.setIndex(layout.indices);
  geometry.computeVertexNormals();
  geometry.computeBoundingBox();
  geometry.computeBoundingSphere();
  return geometry;
}
