import { projectLngLat, unprojectMeters } from "./geo";
import type { Bounds, Building, LngLat, ManhattanManifest, ManhattanOverview, NeighborhoodDetail, TerrainGrid } from "./types";

export type AddressIndex = Record<string, string>;
export interface ContextStreet { id: string; name: string; coordinates: LngLat[]; widthM: number | null }
export interface BlockContext {
  selected: Building;
  buildings: Building[];
  streets: ContextStreet[];
  terrain: TerrainGrid;
  bounds: Bounds;
  taxBlock: string | null;
}

/** BBL is borough(1), block(5), lot(4). Never match an address by proximity. */
export function taxBlockId(bbl: string | null): string | null {
  return bbl && /^1\d{9}$/.test(bbl) ? bbl.slice(0, 6) : null;
}
export function resolveBuildingAddress(building: Pick<Building, "bbl" | "address">, index: AddressIndex): string | null {
  return building.address?.trim() || (building.bbl ? index[building.bbl]?.trim() : null) || null;
}
export async function loadAddressIndex(signal?: AbortSignal): Promise<AddressIndex> {
  const value=await localJson<unknown>("/manhattan/context/addresses.json", signal);
  if(!value || typeof value!=="object" || Array.isArray(value) || !Object.entries(value).every(([bbl,address])=>/^1\d{9}$/.test(bbl) && typeof address==="string" && address.trim().length>0)) {
    throw new Error("The local address index is malformed");
  }
  return value as AddressIndex;
}
async function localJson<T>(url: string, signal?: AbortSignal): Promise<T> {
  if (!/^\/manhattan\/[a-zA-Z0-9_/-]+\.json$/.test(url)) throw new Error("Context assets must be local");
  const response = await fetch(url, { signal });
  if (!response.ok) throw new Error(`Map context unavailable (${response.status})`);
  return response.json();
}
function intersects(a: Bounds, b: Bounds) { return a[0] <= b[2] && a[2] >= b[0] && a[1] <= b[3] && a[3] >= b[1]; }
function pointBounds(points: LngLat[]): Bounds {
  return [Math.min(...points.map(p => p[0])), Math.min(...points.map(p => p[1])), Math.max(...points.map(p => p[0])), Math.max(...points.map(p => p[1]))];
}
export function contextBounds(selected: Building, buildings: Building[]): { bounds: Bounds; taxBlock: string | null } {
  const taxBlock = taxBlockId(selected.bbl);
  const sameBlock = taxBlock ? buildings.filter(b => taxBlockId(b.bbl) === taxBlock) : [];
  const points = sameBlock.length ? sameBlock.flatMap(b => b.footprint[0]) : [selected.center];
  const projected = points.map(p => projectLngLat(p));
  // Tax-block bounds plus the adjoining street frontage. Unknown BBL uses an explicit vicinity.
  const margin = sameBlock.length ? 42 : 180;
  const southwest = unprojectMeters([Math.min(...projected.map(p => p[0])) - margin, Math.min(...projected.map(p => p[1])) - margin]);
  const northeast = unprojectMeters([Math.max(...projected.map(p => p[0])) + margin, Math.max(...projected.map(p => p[1])) + margin]);
  return { bounds: [...southwest, ...northeast], taxBlock: sameBlock.length ? taxBlock : null };
}
export function selectBlockBuildings(buildings: Building[], selected: Building, bounds: Bounds): Building[] {
  const nearby = buildings.filter(b => intersects(pointBounds(b.footprint[0]), bounds));
  if (!nearby.some(b => b.id === selected.id)) nearby.push(selected);
  return nearby;
}
export function selectContextStreets(streets: ContextStreet[], bounds: Bounds) {
  return streets.filter(street => intersects(pointBounds(street.coordinates), bounds));
}
/** Crop the original measured raster. Do not flatten, extrapolate or fill missing samples. */
export function cropTerrain(terrain: TerrainGrid, bounds: Bounds): TerrainGrid {
  if(!terrain || !Array.isArray(terrain.bounds) || terrain.bounds.length!==4 || !terrain.bounds.every(Number.isFinite) || !Number.isInteger(terrain.width) || terrain.width<2 || !Number.isInteger(terrain.height) || terrain.height<2 || !Array.isArray(terrain.elevationsM) || terrain.elevationsM.length!==terrain.width*terrain.height) throw new Error("The local measured elevation grid is malformed");
  const [w,s,e,n] = terrain.bounds;
  if(e<=w || n<=s) throw new Error("The local measured elevation bounds are malformed");
  const dx = (e-w)/(terrain.width-1), dy=(n-s)/(terrain.height-1);
  const x0=Math.max(0,Math.floor((bounds[0]-w)/dx)), x1=Math.min(terrain.width-1,Math.ceil((bounds[2]-w)/dx));
  const y0=Math.max(0,Math.floor((bounds[1]-s)/dy)), y1=Math.min(terrain.height-1,Math.ceil((bounds[3]-s)/dy));
  if(x1<=x0 || y1<=y0) throw new Error("Measured elevation is unavailable for this block");
  const elevationsM=[];
  for(let y=y0;y<=y1;y++) for(let x=x0;x<=x1;x++) elevationsM.push(terrain.elevationsM[y*terrain.width+x]);
  return { bounds:[w+x0*dx,s+y0*dy,w+x1*dx,s+y1*dy], width:x1-x0+1,height:y1-y0+1,elevationsM,source:terrain.source };
}
export async function loadBuildingContext(property: {id: string; neighborhoodId: string}, signal?: AbortSignal): Promise<BlockContext> {
  const [manifest, overview, addresses, streets] = await Promise.all([
    localJson<ManhattanManifest>("/manhattan/manifest.json",signal), localJson<ManhattanOverview>("/manhattan/overview.json",signal),
    loadAddressIndex(signal),localJson<ContextStreet[]>("/manhattan/context/streets.json",signal),
  ]);
  if(!manifest || typeof manifest.details!=="object" || !Array.isArray(overview?.buildings) || !Array.isArray(streets)) throw new Error("The local context assets are malformed");
  const detailUrl=manifest.details[property.neighborhoodId];
  if(!detailUrl) throw new Error("The selected neighborhood is missing from the local map");
  const detail=await localJson<NeighborhoodDetail>(detailUrl,signal);
  if(!Array.isArray(detail?.buildings)) throw new Error("The local building detail is malformed");
  const selected=detail.buildings.find(b=>b.id===property.id);
  if(!selected) throw new Error("The selected building is missing from the local map");
  const {bounds,taxBlock}=contextBounds(selected,overview.buildings);
  // Overview retains every source footprint. Cross-neighborhood context therefore stays complete.
  const buildings=selectBlockBuildings(overview.buildings,selected,bounds).map(b=>({...b,address:resolveBuildingAddress(b,addresses)}));
  const resolved=buildings.find(b=>b.id===selected.id)!;
  // The 50m overview is too coarse at block scale. The common 10m DEM also covers NTA edges.
  const measured=await localJson<TerrainGrid>("/manhattan/terrain-10m.json",signal);
  const terrain=cropTerrain(measured,bounds);
  return { selected:resolved,buildings,streets:selectContextStreets(streets,bounds),terrain,bounds,taxBlock };
}
