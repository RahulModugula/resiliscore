import { projectLngLat } from "./geo";
import { terrainElevation } from "./sceneGeometry";
import type { Building, LngLat, TerrainGrid } from "./types";

/** Keep plan geometry intact while resolving terrain changes along long walls. */
export function sampleBuildingPerimeter(building: Building, spacingM: number): Building {
  const footprint = building.footprint.map(ring => {
    const points: LngLat[] = [];
    const closed = ring.length > 1 && ring[0][0] === ring.at(-1)![0] && ring[0][1] === ring.at(-1)![1];
    const count = closed ? ring.length - 1 : ring.length;
    for (let i = 0; i < count; i++) {
      const a = ring[i], b = ring[(i + 1) % count];
      const [ax, ay] = projectLngLat(a), [bx, by] = projectLngLat(b);
      const steps = Math.max(1, Math.ceil(Math.hypot(bx - ax, by - ay) / Math.max(1, spacingM)));
      for (let j = 0; j < steps; j++) points.push([a[0] + (b[0] - a[0]) * j / steps, a[1] + (b[1] - a[1]) * j / steps]);
    }
    if (points.length) points.push(points[0]);
    return points;
  });
  return { ...building, footprint };
}

export function buildingGroundRange(building: Building, terrain: TerrainGrid) {
  const sampled = sampleBuildingPerimeter(building, terrain.raster?.nominalSpacingM ?? 2);
  let minM = Infinity, maxM = -Infinity, known = 0, total = 0;
  for (const ring of sampled.footprint) for (const point of ring.slice(0, -1)) {
    total++;
    const height = terrainElevation(point, terrain);
    if (height === null) continue;
    known++; minM = Math.min(minM, height); maxM = Math.max(maxM, height);
  }
  return { minM: known ? minM : null, maxM: known ? maxM : null, known, total };
}

/** Conflicting observations cannot support a valid solid extrusion. Retain the sourced height in data. */
export function blockBuildingPlacement(building: Building, terrain: TerrainGrid) {
  const range = buildingGroundRange(building, terrain);
  const groundM = range.minM ?? building.groundElevationM;
  const roofM = groundM !== null && building.heightM !== null ? groundM + building.heightM + .2 : null;
  const conflict = roofM !== null && range.maxM !== null && range.maxM > roofM;
  const sampled = sampleBuildingPerimeter(building, terrain.raster?.nominalSpacingM ?? 2);
  return { geometryBuilding: conflict ? { ...sampled, heightM: null } : sampled, range, groundM, roofM, conflict };
}

export function terrainRange(terrain: TerrainGrid) {
  let minM = Infinity, maxM = -Infinity;
  for (const height of terrain.elevationsM) if (height !== null) { minM = Math.min(minM, height); maxM = Math.max(maxM, height); }
  return { minM: Number.isFinite(minM) ? minM : null, maxM: Number.isFinite(maxM) ? maxM : null };
}
