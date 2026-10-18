import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { writeArrayBuffer } from "geotiff";
import { blockBuildingPlacement, buildingGroundRange, sampleBuildingPerimeter, terrainRange } from "../src/lib/manhattan/blockElevation";
import { loadBuildingContext } from "../src/lib/manhattan/blockContext";
import { decodeElevation, elevationRequest, loadDetailedElevation } from "../src/lib/manhattan/detailedElevation";
import { buildingGeometry, terrainElevation } from "../src/lib/manhattan/sceneGeometry";
import { unprojectMeters } from "../src/lib/manhattan/geo";
import { flatFootprintGeometry } from "../src/lib/manhattan/blockGeometry";
import type { Bounds, Building, TerrainGrid } from "../src/lib/manhattan/types";

const grid: TerrainGrid = { bounds: [...unprojectMeters([0,0]),...unprojectMeters([100,100])], width:2,height:2,elevationsM:[0,10,20,30],source:"Measured slope" };
const building: Building = {id:"slope",bin:null,bbl:null,address:null,name:null,center:unprojectMeters([50,50]),footprint:[[[10,10],[90,10],[90,90],[10,90],[10,10]].map(p=>unprojectMeters([p[0],p[1]]))],heightM:30,groundElevationM:null,neighborhoodId:"MN0101",yearBuilt:1900,featureCode:"2100"};

test("sloping block roofs use lowest supported footprint ground and retain the actual building height",()=>{
  const before=structuredClone(building), range=buildingGroundRange(building,grid);
  assert.ok(Math.abs(range.minM!-3)<1e-7);
  assert.ok(Math.abs(range.maxM!-27)<1e-7);
  assert.ok(Math.abs(terrainElevation(building.center,grid)!-15)<1e-7);
  const geometry=buildingGeometry([sampleBuildingPerimeter(building,2)],{terrain:grid,groundAt:b=>buildingGroundRange(b,grid).minM}).geometry;
  assert.ok(Math.abs(geometry.getAttribute("position").getY(0)-33.2)<1e-4,"roof was anchored 12m too high at the centre sample");
  assert.deepEqual(building,before);
  geometry.dispose();
});

test("walls resolve a hill between original corners and unknown perimeter ground never becomes zero",()=>{
  const hill={...grid,width:3,height:3,elevationsM:[0,10,0,0,10,0,0,10,0]};
  const prepared=sampleBuildingPerimeter(building,2);
  assert.ok(prepared.footprint[0].length>building.footprint[0].length);
  const geometry=buildingGeometry([prepared],{terrain:hill,groundAt:b=>buildingGroundRange(b,hill).minM}).geometry;
  const positions=geometry.getAttribute("position");
  const roofCount=prepared.footprint[0].length-1;
  assert.ok(Array.from({length:positions.count-roofCount},(_,i)=>positions.getY(i+roofCount)).some(h=>Math.abs(h-10)<1e-5));
  assert.equal(buildingGroundRange(building,{...grid,elevationsM:[null,null,null,null]}).minM,null);
  assert.equal(terrainRange({...grid,elevationsM:[null,null,null,null]}).maxM,null);
  geometry.dispose();
});

test("conflicting ground and building heights retain a flat outline without invented walls or a folded footprint",async()=>{
  const original=globalThis.fetch;
  globalThis.fetch=async path=>new Response(await readFile(new URL(`../public${path}`,import.meta.url)));
  try {
    const overview=JSON.parse(await readFile(new URL("../public/manhattan/overview.json",import.meta.url),"utf8"));
    const building:Building=overview.buildings.find((b:Building)=>b.id==="308707");
    const context=await loadBuildingContext(building);
    const placement=blockBuildingPlacement(context.selected,context.terrain);
    assert.ok(placement.range.maxM!>placement.roofM!,"recorded building must reproduce the wall/roof conflict");
    assert.equal(placement.conflict,true);
    assert.equal(placement.geometryBuilding.heightM,null);
    assert.equal(context.selected.heightM,21.21,"the sourced height must remain unchanged");
    const reference=building.groundElevationM??placement.range.maxM!;
    const geometry=flatFootprintGeometry([{building,elevationM:reference}]);
    const positions=geometry.getAttribute("position");
    assert.ok(positions.count>0);
    assert.equal(geometry.getIndex(),null,"the unresolved footprint must have no filled faces");
    assert.ok(Array.from({length:positions.count},(_,i)=>positions.getY(i)).every(h=>Math.abs(h-reference-.2)<1e-5));
    geometry.dispose();
  } finally {globalThis.fetch=original;}
});

test("GeoTIFF affine transform, row orientation, zero and NoData survive decoding",async()=>{
  const data=writeArrayBuffer(new Float32Array([11,0,13,21,NaN,-3.4028234663852886e38]),{width:3,height:2,BitsPerSample:[32],SampleFormat:[3],ModelPixelScale:[.00001,.00001,0],ModelTiepoint:[0,0,0,-74,41,0],GeographicTypeGeoKey:4326,GTRasterTypeGeoKey:1});
  const terrain=await decodeElevation(data);
  assert.deepEqual(terrain.elevationsM,[21,null,null,11,0,13]);
  assert.ok(Math.abs(terrain.bounds[0]-(-74+.000005))<1e-10);
  assert.ok(Math.abs(terrain.bounds[1]-(41-.000015))<1e-10);
  assert.equal(terrain.raster?.verticalDatum,"NAVD88");
  assert.ok(terrain.raster && terrain.raster.nominalSpacingM<2);
  assert.deepEqual(terrainRange(terrain),{minM:0,maxM:21});
});

test("native-source requests lock raster IDs, request numeric bare earth, cover the block and bound large-grid work",()=>{
  for(const bounds of [[-74.004,40.706,-74.001,40.709],[-74.02,40.70,-73.98,40.74]] as Bounds[]) {
    const request=elevationRequest(bounds,[34803,48017]), params=new URL(request.url).searchParams;
    assert.equal(params.get("format"),"tiff"); assert.equal(params.get("pixelType"),"F32");
    assert.equal(params.get("interpolation"),"RSP_NearestNeighbor");
    assert.deepEqual(JSON.parse(params.get("renderingRule")!),{rasterFunction:"None"});
    assert.deepEqual(JSON.parse(params.get("mosaicRule")!).lockRasterIds,[34803,48017]);
    const extent=params.get("bbox")!.split(",").map(Number);
    assert.ok(extent[0]<bounds[0] && extent[1]<bounds[1] && extent[2]>bounds[2] && extent[3]>bounds[3]);
    assert.ok(params.get("size")!.split(",").map(Number).every(size=>size>=2 && size<=512));
  }
});

test("recorded USGS block raster decodes, validates coverage, caches successful data and respects cancellation",async()=>{
  const bytes=await readFile(new URL("fixtures/elevation/usgs-block-441.tif",import.meta.url));
  const metadata=JSON.parse(await readFile(new URL("fixtures/elevation/usgs-block-441.json",import.meta.url),"utf8"));
  assert.equal(createHash("sha256").update(bytes).digest("hex"),metadata.sha256);
  const original=globalThis.fetch, requests:string[]=[];
  globalThis.fetch=async input=>{
    const url=String(input); requests.push(url);
    if(url==="/manhattan/dem-provenance.json") return new Response(await readFile(new URL("../public/manhattan/dem-provenance.json",import.meta.url)));
    if(url.includes("/exportImage?")) return Response.json(metadata.response);
    return new Response(bytes);
  };
  try {
    const terrain=await loadDetailedElevation(metadata.bounds);
    assert.equal(terrain.width,metadata.response.width); assert.equal(terrain.height,metadata.response.height);
    const decoded=Buffer.alloc(terrain.elevationsM.length*4);
    terrain.elevationsM.forEach((value,index)=>decoded.writeFloatLE(value??NaN,index*4));
    assert.equal(createHash("sha256").update(decoded).digest("hex"),metadata.rasterioReference.southFirstFloat32Sha256);
    terrain.bounds.forEach((value,index)=>assert.ok(Math.abs(value-metadata.rasterioReference.bounds[index])<1e-12));
    assert.ok(terrain.raster!.nominalSpacingM<1.01);
    assert.ok(terrainRange(terrain).maxM!>terrainRange(terrain).minM!);
    const count=requests.length;
    assert.equal(await loadDetailedElevation(metadata.bounds),terrain);
    assert.equal(requests.length,count);
    const controller=new AbortController();controller.abort();
    await assert.rejects(loadDetailedElevation(metadata.bounds,controller.signal),{name:"AbortError"});
  } finally { globalThis.fetch=original; }
});
