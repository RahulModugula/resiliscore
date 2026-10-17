import { readFileSync } from 'node:fs';
import { performance } from 'node:perf_hooks';
import { MeshBVH, SAH, CENTER } from 'three-mesh-bvh';
import { buildingGeometry, terrainGeometry, outlineGeometry } from '../../src/lib/manhattan/sceneGeometry';
import { terrainSurface } from '../../src/lib/manhattan/terrainSurface';
import { sceneScope } from '../../src/lib/manhattan/sceneScope';
import { pointInGeometry } from '../../src/lib/manhattan/geo';
import type { ManhattanOverview, Neighborhood, NeighborhoodDetail } from '../../src/lib/manhattan/types';
const read = <T,>(path: string): T => JSON.parse(readFileSync(new URL(`../../public/manhattan/${path}.json`, import.meta.url), 'utf8'));
const neighborhoods = read<Neighborhood[]>('neighborhoods');
const overview = read<ManhattanOverview>('overview');
const output = [];
for (const id of [null, 'MN0101', 'MN1292']) {
 const detail = id ? read<NeighborhoodDetail>(`neighborhoods/${id}`) : null;
 const stages: Record<string, number> = {};
 function time<T>(name: string, fn: () => T): T { const start = performance.now(); const value = fn(); stages[name] = performance.now() - start; return value; }
 const scope = time('scope', () => sceneScope(neighborhoods, overview, detail, id));
 const terrainAt = (point: [number, number]) => detail && scope.selected && point[0] >= scope.selected.bounds[0] && point[0] <= scope.selected.bounds[2] && point[1] >= scope.selected.bounds[1] && point[1] <= scope.selected.bounds[3] && pointInGeometry(point, scope.selected.geometry) ? detail.terrain : overview.terrain;
 const buildings = time('buildings', () => buildingGeometry(scope.buildings, { terrainAt }).geometry);
 const land = time('land', () => terrainGeometry(scope.terrain!, scope.neighborhoods));
 const parks = time('parks', () => terrainSurface(scope.terrain!, scope.parks.map(p => p.geometry), { include: scope.clip, color: '#4d8066', lift: .06 }));
 const borders = time('borders', () => scope.neighborhoods.map(n => outlineGeometry(n.geometry, scope.terrain)));
 time('SAH', () => [buildings, land, parks].map(g => new MeshBVH(g, { ...{ indirect: true }, strategy: SAH })));
 time('CENTER', () => [buildings, land, parks].map(g => new MeshBVH(g, { ...{ indirect: true }, strategy: CENTER })));
 output.push({ id, buildings: scope.buildings.length, vertices: buildings.getAttribute('position').count, stages });
 [buildings, land, parks, ...borders].forEach(g => g.dispose());
}
console.log(JSON.stringify(output, null, 2));
