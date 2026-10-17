import { loadManhattan, loadMapAsset, loadNeighborhood } from "./data";
import { projectLngLat, unprojectMeters } from "./geo";
import type { Bounds, Building, LngLat, TerrainGrid } from "./types";

export type AddressIndex = Record<string, string>;
export interface ContextStreet { id: string; name: string; coordinates: LngLat[]; widthM: number | null }
export interface BlockContext {
  selected: Building;
  buildings: Building[];
  streets: ContextStreet[];
  terrain: TerrainGrid;
  bounds: Bounds;
  taxBlock: string | null;
  wholeBlock: boolean;
}

/** BBL is borough(1), block(5), lot(4). Never match an address by proximity. */
export function taxBlockId(bbl: string | null): string | null {
  return bbl && /^1\d{9}$/.test(bbl) ? bbl.slice(0, 6) : null;
}
export function resolveBuildingAddress(building: Pick<Building, "bbl" | "address">, index: AddressIndex): string | null {
  return building.address?.trim() || (building.bbl ? index[building.bbl]?.trim() : null) || null;
}
export async function loadAddressIndex(signal?: AbortSignal): Promise<AddressIndex> {
  return loadMapAsset<AddressIndex>("/manhattan/context/addresses.json", signal, value =>
    !!value && typeof value === "object" && !Array.isArray(value) && Object.entries(value).every(([bbl, address]) => /^1\d{9}$/.test(bbl) && typeof address === "string" && address.trim().length > 0), "The local address index is malformed");
}
function intersects(a: Bounds, b: Bounds) { return a[0] <= b[2] && a[2] >= b[0] && a[1] <= b[3] && a[3] >= b[1]; }
function pointBounds(points: LngLat[]): Bounds {
  return [Math.min(...points.map(p => p[0])), Math.min(...points.map(p => p[1])), Math.max(...points.map(p => p[0])), Math.max(...points.map(p => p[1]))];
}
export function contextBounds(selected: Building, buildings: Building[]): { bounds: Bounds; taxBlock: string | null; wholeBlock: boolean } {
  const taxBlock = taxBlockId(selected.bbl);
  const sameBlock = taxBlock ? buildings.filter(b => taxBlockId(b.bbl) === taxBlock) : [];
  const extent = (points: LngLat[]) => points.reduce<[number,number,number,number]>((b,p)=>{
    const [x,y]=projectLngLat(p);return [Math.min(b[0],x),Math.min(b[1],y),Math.max(b[2],x),Math.max(b[3],y)];
  },[Infinity,Infinity,-Infinity,-Infinity]);
  const blockExtent=extent(sameBlock.length ? sameBlock.flatMap(b=>b.footprint[0]) : selected.footprint[0]);
  // Exceptional park/campus tax blocks span kilometres. Keep the chosen property in a bounded local part.
  const wholeBlock=sameBlock.length>0 && Math.max(blockExtent[2]-blockExtent[0],blockExtent[3]-blockExtent[1])<=1000;
  const box=wholeBlock ? blockExtent : extent(selected.footprint[0]);
  const margin=wholeBlock ? 42 : 180;
  const southwest=unprojectMeters([box[0]-margin,box[1]-margin]);
  const northeast=unprojectMeters([box[2]+margin,box[3]+margin]);
  return {bounds:[...southwest,...northeast],taxBlock:sameBlock.length ? taxBlock : null,wholeBlock};
}
export function selectBlockBuildings(buildings: Building[], selected: Building, bounds: Bounds): Building[] {
  const nearby = buildings.filter(b => b.id!==selected.id && intersects(pointBounds(b.footprint[0]), bounds));
  return [selected,...nearby];
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
  const croppedBounds:Bounds=[w+x0*dx,s+y0*dy,w+x1*dx,s+y1*dy];
  return { ...terrain,bounds:croppedBounds,width:x1-x0+1,height:y1-y0+1,elevationsM,
    ...(terrain.raster ? {raster:{...terrain.raster,extent:[croppedBounds[0]-dx/2,croppedBounds[1]-dy/2,croppedBounds[2]+dx/2,croppedBounds[3]+dy/2] as Bounds}} : {}),
  };
}
export async function loadBuildingContext(property: {id: string; neighborhoodId: string}, signal?: AbortSignal): Promise<BlockContext> {
  // Reuse parsed geography when arriving from the map. Start independent block
  // assets together rather than downloading the DEM after all other work.
  const [map, addresses, streets, measured] = await Promise.all([
    loadManhattan(signal), loadAddressIndex(signal),
    loadMapAsset<ContextStreet[]>("/manhattan/context/streets.json", signal, value => Array.isArray(value)),
    loadMapAsset<TerrainGrid>("/manhattan/terrain-10m.json", signal, value => !!value && typeof value === "object" && "elevationsM" in value && Array.isArray(value.elevationsM) && "width" in value && typeof value.width === "number" && "height" in value && typeof value.height === "number" && value.elevationsM.length === value.width * value.height && "bounds" in value && Array.isArray(value.bounds) && value.bounds.length === 4 && value.bounds.every(Number.isFinite)),
  ]);
  const { overview } = map;
  const detail = await loadNeighborhood(map.manifest, property.neighborhoodId, signal);
  const selected=detail.buildings.find(b=>b.id===property.id);
  if(!selected) throw new Error("The selected building is missing from the local map");
  const {bounds,taxBlock,wholeBlock}=contextBounds(selected,overview.buildings);
  // Overview retains every source footprint. Cross-neighborhood context therefore stays complete.
  const buildings=selectBlockBuildings(overview.buildings,selected,bounds).map(b=>({...b,address:resolveBuildingAddress(b,addresses)}));
  const resolved=buildings.find(b=>b.id===selected.id)!;
  // The 50m overview is too coarse at block scale. The common 10m DEM also covers NTA edges.
  // Include entire neighboring footprints, so their walls do not float past a clipped ground patch.
  const terrainBounds=buildings.reduce<Bounds>((extent,building)=>{
    for(const ring of building.footprint) for(const point of ring) {
      extent[0]=Math.min(extent[0],point[0]);extent[1]=Math.min(extent[1],point[1]);
      extent[2]=Math.max(extent[2],point[0]);extent[3]=Math.max(extent[3],point[1]);
    }
    return extent;
  },[...bounds]);
  const terrain=cropTerrain(measured,terrainBounds);
  return { selected:resolved,buildings,streets:selectContextStreets(streets,bounds),terrain,bounds,taxBlock,wholeBlock };
}
