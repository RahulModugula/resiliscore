import type { Bounds, Geometry, LngLat } from "./types";

export const MANHATTAN_ORIGIN: LngLat = [-73.9712, 40.7831];
const EARTH_RADIUS_M = 6_371_008.8;
const RAD = Math.PI / 180;

/** Local equirectangular projection, east/north metres, suited to Manhattan scale. */
export function projectLngLat([lng, lat]: LngLat, origin: LngLat = MANHATTAN_ORIGIN): [number, number] {
  return [(lng - origin[0]) * RAD * EARTH_RADIUS_M * Math.cos(origin[1] * RAD), (lat - origin[1]) * RAD * EARTH_RADIUS_M];
}

export function unprojectMeters([east, north]: [number, number], origin: LngLat = MANHATTAN_ORIGIN): LngLat {
  return [origin[0] + east / (RAD * EARTH_RADIUS_M * Math.cos(origin[1] * RAD)), origin[1] + north / (RAD * EARTH_RADIUS_M)];
}

export function geometryPolygons(geometry: Geometry): LngLat[][][] {
  return geometry.type === "Polygon" ? [geometry.coordinates] : geometry.coordinates;
}

export function boundsCenter([west, south, east, north]: Bounds): LngLat {
  return [(west + east) / 2, (south + north) / 2];
}

export function geometryBounds(geometry: Geometry): Bounds {
  const points = geometryPolygons(geometry).flat(2);
  return points.reduce<Bounds>((bounds, [lng, lat]) => [Math.min(bounds[0], lng), Math.min(bounds[1], lat), Math.max(bounds[2], lng), Math.max(bounds[3], lat)], [Infinity, Infinity, -Infinity, -Infinity]);
}

function insideRing([lng, lat]: LngLat, ring: LngLat[]): boolean {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i];
    const [xj, yj] = ring[j];
    if ((yi > lat) !== (yj > lat) && lng < (xj - xi) * (lat - yi) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

export function pointInGeometry(point: LngLat, geometry: Geometry): boolean {
  return geometryPolygons(geometry).some(([outer, ...holes]) => insideRing(point, outer) && !holes.some((hole) => insideRing(point, hole)));
}
