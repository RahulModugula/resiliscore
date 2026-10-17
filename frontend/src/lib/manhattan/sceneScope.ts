import { intersection } from "polygon-clipping";
import { geometryBounds, geometryPolygons, pointInGeometry } from "./geo";
import { combineBounds } from "./sceneGeometry";
import type { Bounds, Building, Geometry, Infrastructure, ManhattanOverview, Neighborhood, NeighborhoodDetail, Park, SewerLine, LngLat, TerrainGrid } from "./types";

export interface SceneScope {
  selected: Neighborhood | null;
  neighborhoods: Neighborhood[];
  detail: NeighborhoodDetail | null;
  buildings: Building[];
  parks: Park[];
  terrain?: TerrainGrid;
  infrastructure?: Infrastructure;
  bounds: Bounds;
  clip?: Geometry;
}

type Edge = [LngLat, LngLat];
const EPSILON = 1e-10;
const cross = (a: LngLat, b: LngLat) => a[0] * b[1] - a[1] * b[0];
const subtract = (a: LngLat, b: LngLat): LngLat => [a[0] - b[0], a[1] - b[1]];
const samePoint = (a: LngLat, b: LngLat) => Math.hypot(a[0] - b[0], a[1] - b[1]) < EPSILON;
function edges(geometry: Geometry): Edge[] {
  return geometryPolygons(geometry).flatMap(polygon => polygon.flatMap(ring => ring.slice(1).map((point, index): Edge => [ring[index], point])));
}
function onBoundary(point: LngLat, boundary: Edge[]): boolean {
  return boundary.some(([a, b]) => {
    const length = Math.hypot(b[0] - a[0], b[1] - a[1]);
    return length > 0 && Math.abs(cross(subtract(point, a), subtract(b, a))) / length < EPSILON
      && point[0] >= Math.min(a[0], b[0]) - EPSILON && point[0] <= Math.max(a[0], b[0]) + EPSILON
      && point[1] >= Math.min(a[1], b[1]) - EPSILON && point[1] <= Math.max(a[1], b[1]) + EPSILON;
  });
}

/** Keep sourced line portions within the polygon, splitting at holes and detached areas. */
function clipLine(line: SewerLine, geometry: Geometry, boundary: Edge[]): SewerLine[] {
  const pieces: LngLat[][] = [];
  let current: LngLat[] = [];
  for (let i = 1; i < line.coordinates.length; i++) {
    const a = line.coordinates[i - 1], b = line.coordinates[i];
    const direction = subtract(b, a);
    const lengthSquared = direction[0] ** 2 + direction[1] ** 2;
    if (lengthSquared === 0) continue;
    const cuts = [0, 1];
    for (const [c, d] of boundary) {
      const edge = subtract(d, c), offset = subtract(c, a);
      const denominator = cross(direction, edge);
      if (Math.abs(denominator) > 1e-20) {
        const t = cross(offset, edge) / denominator, u = cross(offset, direction) / denominator;
        if (t > 0 && t < 1 && u >= -EPSILON && u <= 1 + EPSILON) cuts.push(t);
      } else if (Math.abs(cross(offset, direction)) < 1e-20) {
        for (const point of [c, d]) {
          const relative = subtract(point, a);
          const t = (relative[0] * direction[0] + relative[1] * direction[1]) / lengthSquared;
          if (t > 0 && t < 1) cuts.push(t);
        }
      }
    }
    cuts.sort((a, b) => a - b);
    const unique = cuts.filter((value, index) => index === 0 || value - cuts[index - 1] > EPSILON);
    const at = (t: number): LngLat => [a[0] + direction[0] * t, a[1] + direction[1] * t];
    for (let cut = 1; cut < unique.length; cut++) {
      const midpoint = at((unique[cut - 1] + unique[cut]) / 2);
      if (!pointInGeometry(midpoint, geometry) && !onBoundary(midpoint, boundary)) continue;
      const first = at(unique[cut - 1]), last = at(unique[cut]);
      if (current.length && !samePoint(current[current.length - 1], first)) { pieces.push(current); current = []; }
      if (!current.length) current.push(first);
      current.push(last);
    }
  }
  if (current.length >= 2) pieces.push(current);
  return pieces.map((coordinates, index) => ({ ...line, id: `${line.id}:selection-${index}`, coordinates }));
}

function overlaps(a: Bounds, b: Bounds) { return a[0] <= b[2] && a[2] >= b[0] && a[1] <= b[3] && a[3] >= b[1]; }

/** Shared render inputs for every layer, including the interval before detail arrives. */
export function sceneScope(neighborhoods: Neighborhood[], overview: ManhattanOverview | null, detail: NeighborhoodDetail | null, selectedId: string | null): SceneScope {
  const selected = neighborhoods.find(neighborhood => neighborhood.id === selectedId) ?? null;
  const activeDetail = selected && detail?.neighborhoodId === selected.id ? detail : null;
  if (!selected) return { selected: null, neighborhoods, detail: null, buildings: overview?.buildings ?? [], parks: overview?.parks ?? [], terrain: overview?.terrain, infrastructure: overview?.infrastructure, bounds: combineBounds(neighborhoods) };
  const source = activeDetail ?? overview;
  const boundary = edges(selected.geometry);
  const infrastructure = source?.infrastructure;
  return {
    selected, neighborhoods: [selected], detail: activeDetail,
    buildings: (source?.buildings ?? []).filter(building => building.neighborhoodId === selected.id),
    parks: (source?.parks ?? []).filter(park => overlaps(geometryBounds(park.geometry), selected.bounds) && intersection(geometryPolygons(park.geometry), geometryPolygons(selected.geometry)).length > 0),
    terrain: source?.terrain,
    infrastructure: infrastructure ? { ...infrastructure, stormDrains: infrastructure.stormDrains.filter(drain => pointInGeometry(drain.position, selected.geometry) || onBoundary(drain.position, boundary)), sewerLines: infrastructure.sewerLines.flatMap(line => clipLine(line, selected.geometry, boundary)) } : undefined,
    bounds: selected.bounds,
    clip: selected.geometry,
  };
}
