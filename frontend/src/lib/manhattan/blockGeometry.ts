import { BufferGeometry, Color, Float32BufferAttribute } from "three";
import { projectLngLat, unprojectMeters } from "./geo";
import { terrainElevation, worldPoint } from "./sceneGeometry";
import type { Bounds, LngLat, TerrainGrid } from "./types";
import type { ContextStreet } from "./blockContext";

/** Clip a geographic segment to the context rectangle before sampling. */
export function clipStreet(a: LngLat, b: LngLat, bounds: Bounds): [LngLat, LngLat] | null {
  let low=0,high=1;
  const dx=b[0]-a[0],dy=b[1]-a[1];
  for(const [p,q] of [[-dx,a[0]-bounds[0]],[dx,bounds[2]-a[0]],[-dy,a[1]-bounds[1]],[dy,bounds[3]-a[1]]]) {
    if(p===0) { if(q<0) return null; continue; }
    const r=q/p;
    if(p<0) low=Math.max(low,r); else high=Math.min(high,r);
    if(low>high) return null;
  }
  return [[a[0]+low*dx,a[1]+low*dy],[a[0]+high*dx,a[1]+high*dy]];
}
/** Anchor a name on a visible, DEM-supported segment, even when the source midpoint is far away. */
export function streetLabelPosition(street: ContextStreet, terrain: TerrainGrid, bounds: Bounds): { point:LngLat; elevation:number } | null {
  for(let i=1;i<street.coordinates.length;i++) {
    const clipped=clipStreet(street.coordinates[i-1],street.coordinates[i],bounds);
    if(!clipped) continue;
    const point:LngLat=[(clipped[0][0]+clipped[1][0])/2,(clipped[0][1]+clipped[1][1])/2];
    const elevation=terrainElevation(point,terrain);
    if(elevation!==null) return {point,elevation};
  }
  return null;
}
/** Real centerlines draped at <=5m intervals. Null DEM samples never become zero-height roads. */
export function streetGeometry(streets: ContextStreet[], terrain: TerrainGrid, bounds: Bounds) {
  const positions:number[]=[];
  for(const street of streets) for(let i=1;i<street.coordinates.length;i++) {
    const clipped=clipStreet(street.coordinates[i-1],street.coordinates[i],bounds);
    if(!clipped) continue;
    const [a,b]=clipped.map(p=>projectLngLat(p));
    const dx=b[0]-a[0],dy=b[1]-a[1],length=Math.hypot(dx,dy);
    if(!length) continue;
    // Missing widths are centerlines, never a guessed curb-to-curb road width.
    const halfWidth=(street.widthM ?? .8)/2;
    const normal:[number,number]=[-dy/length*halfWidth,dx/length*halfWidth];
    const count=Math.max(1,Math.ceil(length/5));
    for(let j=0;j<count;j++) {
      const corners:LngLat[]=[];
      for(const [t,side] of [[j/count,-1],[j/count,1],[(j+1)/count,-1],[(j+1)/count,1]]) {
        corners.push(unprojectMeters([a[0]+dx*t+normal[0]*side,a[1]+dy*t+normal[1]*side]));
      }
      const heights=corners.map(p=>terrainElevation(p,terrain));
      if(heights.some(h=>h===null)) continue;
      const points=corners.map((p,k)=>worldPoint(p,heights[k]!+.3));
      for(const k of [0,2,1,1,2,3]) positions.push(...points[k]);
    }
  }
  const geometry=new BufferGeometry();
  geometry.setAttribute("position",new Float32BufferAttribute(positions,3));
  geometry.computeVertexNormals();
  return geometry;
}
export const TERRAIN_LOW="#476b61",TERRAIN_HIGH="#b8bd83";
/** Color encodes the same measured elevations as the vertex positions. */
export function colorTerrain(geometry: BufferGeometry, min:number,max:number) {
  const positions=geometry.getAttribute("position"),colors:number[]=[];
  const low=new Color(TERRAIN_LOW),high=new Color(TERRAIN_HIGH);
  for(let i=0;i<positions.count;i++) {
    const t=max>min ? (positions.getY(i)-min)/(max-min) : 0;
    const color=low.clone().lerp(high,Math.max(0,Math.min(1,t)));
    colors.push(color.r,color.g,color.b);
  }
  geometry.setAttribute("color",new Float32BufferAttribute(colors,3));
  return geometry;
}
