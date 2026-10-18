import { BufferGeometry, Color, Float32BufferAttribute, ShapeUtils, Vector2 } from "three";
import polygonClipping, { type MultiPolygon, type Polygon } from "polygon-clipping";
import { projectLngLat, unprojectMeters } from "./geo";
import { terrainElevation, worldPoint } from "./sceneGeometry";
import type { Bounds, Building, LngLat, TerrainGrid } from "./types";
import type { ContextStreet } from "./blockContext";
import type { TransportDeck } from "./transportStructures";

type Point3 = [number,number,number];
const planPolygon=(points:Point3[]):Polygon=>[[...points.map(([x,,z]):[number,number]=>[x,z]),[points[0][0],points[0][2]]]];
const deckTriangleCache=new WeakMap<TransportDeck,Point3[][]>();
function deckTriangles(deck:TransportDeck,lift=0) {
  let triangles=deckTriangleCache.get(deck);
  if(!triangles) {
    const rings=deck.rings.map(ring=>ring.slice(0,-1).map(([lng,lat,height])=>worldPoint([lng,lat],height)));
    const points=rings.flat(),vectors=rings.map(ring=>ring.map(([x,,z])=>new Vector2(x,z)));
    triangles=ShapeUtils.triangulateShape(vectors[0],vectors.slice(1)).map(face=>face.map(k=>points[k]));
    deckTriangleCache.set(deck,triangles);
  }
  return lift ? triangles.map(triangle=>triangle.map(([x,y,z]):Point3=>[x,y+lift,z])) : triangles;
}
function deckElevation(point:LngLat,deck:TransportDeck) {
  const [x,,z]=worldPoint(point);
  for(const [a,b,c] of deckTriangles(deck)) {
    const denominator=(b[2]-c[2])*(a[0]-c[0])+(c[0]-b[0])*(a[2]-c[2]);
    if(Math.abs(denominator)<1e-12) continue;
    const u=((b[2]-c[2])*(x-c[0])+(c[0]-b[0])*(z-c[2]))/denominator;
    const v=((c[2]-a[2])*(x-c[0])+(a[0]-c[0])*(z-c[2]))/denominator;
    if(u>=-1e-9 && v>=-1e-9 && u+v<=1+1e-9) return u*a[1]+v*b[1]+(1-u-v)*c[1];
  }
  return null;
}
/** A cartographic outline only. Conflicting terrain must not turn a footprint into a sloping solid. */
export function flatFootprintGeometry(items:{building:Building;elevationM:number}[]) {
  const positions:number[]=[];
  for(const {building,elevationM} of items) for(const ring of building.footprint) {
    const closed=ring.length>1 && ring[0][0]===ring.at(-1)![0] && ring[0][1]===ring.at(-1)![1];
    const points=closed ? ring.slice(0,-1) : ring;
    for(let i=0;i<points.length;i++) positions.push(...worldPoint(points[i],elevationM+.2),...worldPoint(points[(i+1)%points.length],elevationM+.2));
  }
  const geometry=new BufferGeometry();geometry.setAttribute("position",new Float32BufferAttribute(positions,3));return geometry;
}
/** Retain the source triangle's plane when clipping its plan footprint. */
function appendClipped(positions:number[],source:Point3[],polygons:MultiPolygon) {
  const [a,b,c]=source;
  const denominator=(b[2]-c[2])*(a[0]-c[0])+(c[0]-b[0])*(a[2]-c[2]);
  if(Math.abs(denominator)<1e-12) return;
  for(const polygon of polygons) {
    const rings=polygon.map(ring=>ring.slice(0,-1).map(([x,z])=>new Vector2(x,z)));
    const points=rings.flat();
    for(const face of ShapeUtils.triangulateShape(rings[0],rings.slice(1))) {
      const [p,q,r]=face.map(i=>points[i]);
      if(Math.abs((q.x-p.x)*(r.y-p.y)-(q.y-p.y)*(r.x-p.x))<1e-8) continue;
      for(const i of face) {
        const {x,y:z}=points[i];
        const u=((b[2]-c[2])*(x-c[0])+(c[0]-b[0])*(z-c[2]))/denominator;
        const v=((c[2]-a[2])*(x-c[0])+(a[0]-c[0])*(z-c[2]))/denominator;
        positions.push(x,u*a[1]+v*b[1]+(1-u-v)*c[1],z);
      }
    }
  }
}
/** Split in plan first: a DEM sample beneath a bridge must not pull down the approach seam. */
function appendRoadApproach(positions:number[],polygons:MultiPolygon,terrain:TerrainGrid,decks:TransportDeck[]) {
  for(const polygon of polygons) {
    const rings=polygon.map(ring=>ring.slice(0,-1).map(([x,z])=>new Vector2(x,z))),points=rings.flat();
    const heights=points.map(({x,y:z})=>{
      const point=unprojectMeters([x,-z]);
      return decks.map(deck=>deckElevation(point,deck)).find(height=>height!==null)??terrainElevation(point,terrain);
    });
    for(const face of ShapeUtils.triangulateShape(rings[0],rings.slice(1))) {
      const [a,b,c]=face.map(i=>points[i]);
      if(Math.abs((b.x-a.x)*(c.y-a.y)-(b.y-a.y)*(c.x-a.x))<1e-8 || face.some(i=>heights[i]===null)) continue;
      for(const i of face) positions.push(points[i].x,heights[i]!+.3,points[i].y);
    }
  }
}

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
export function streetLabelPosition(street: ContextStreet, terrain: TerrainGrid, bounds: Bounds, decks:TransportDeck[] = []): { point:LngLat; elevation:number } | null {
  for(let i=1;i<street.coordinates.length;i++) {
    const clipped=clipStreet(street.coordinates[i-1],street.coordinates[i],bounds);
    if(!clipped) continue;
    const point:LngLat=[(clipped[0][0]+clipped[1][0])/2,(clipped[0][1]+clipped[1][1])/2];
    const deckHeight=decks.filter(deck=>deck.streetIds.includes(street.id)).map(deck=>deckElevation(point,deck)).find(height=>height!==null);
    const elevation=deckHeight??terrainElevation(point,terrain);
    if(elevation!==null) return {point,elevation};
  }
  return null;
}
/** Ground ribbons stop at associated deck outlines. Deck Z never comes from the bare-earth raster. */
export function streetGeometry(streets: ContextStreet[], terrain: TerrainGrid, bounds: Bounds, decks:TransportDeck[] = []) {
  const positions:number[]=[];
  const deckPlans=decks.map(deck=>deck.rings.map(ring=>ring.map(([lng,lat])=>{const [x,,z]=worldPoint([lng,lat]);return [x,z] as [number,number];})));
  for(const street of streets) for(let i=1;i<street.coordinates.length;i++) {
    const associated=decks.filter(deck=>deck.streetIds.includes(street.id));
    const excluded=decks.flatMap((deck,k)=>deck.streetIds.includes(street.id) ? [deckPlans[k]] : []);
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
      if(excluded.length) {
        const source=[0,2,3,1].map(k=>worldPoint(corners[k]));
        appendRoadApproach(positions,polygonClipping.difference(planPolygon(source),...excluded),terrain,associated);
      } else {
        const heights=corners.map(p=>terrainElevation(p,terrain));
        if(heights.some(h=>h===null)) continue;
        const points=corners.map((p,k)=>worldPoint(p,heights[k]!+.3));
        for(const k of [0,2,1,1,2,3]) positions.push(...points[k]);
      }
    }
  }
  const [west,,southZ]=worldPoint([bounds[0],bounds[1]]),[east,,northZ]=worldPoint([bounds[2],bounds[3]]);
  // world Z points south; bounds must be converted independently of elevation.
  const rectangle:Polygon=[[[west,northZ],[east,northZ],[east,southZ],[west,southZ],[west,northZ]]];
  for(const deck of decks) {
    for(const source of deckTriangles(deck,.3)) {
      appendClipped(positions,source,polygonClipping.intersection(planPolygon(source),rectangle));
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
