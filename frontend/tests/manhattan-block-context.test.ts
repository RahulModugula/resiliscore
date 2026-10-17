import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { loadAddressIndex, loadBuildingContext, resolveBuildingAddress, taxBlockId, contextBounds, selectBlockBuildings, selectContextStreets, cropTerrain, type AddressIndex, type ContextStreet } from "../src/lib/manhattan/blockContext";
import { streetGeometry, streetLabelPosition } from "../src/lib/manhattan/blockGeometry";
import { terrainElevation } from "../src/lib/manhattan/sceneGeometry";
import { unprojectMeters } from "../src/lib/manhattan/geo";
import type { Building, TerrainGrid } from "../src/lib/manhattan/types";

const building: Building={id:"selected",bin:"1000001",bbl:"1000010001",address:null,name:"Not a street address",center:unprojectMeters([50,50]),footprint:[[unprojectMeters([40,40]),unprojectMeters([60,40]),unprojectMeters([60,60]),unprojectMeters([40,60]),unprojectMeters([40,40])]],heightM:30,groundElevationM:null,yearBuilt:1900,featureCode:"2100",neighborhoodId:"MN0101"};

test("official address bundle resolves an exact BBL, never a landmark name or nearby lot",async()=>{
  const index:AddressIndex=JSON.parse(await readFile(new URL("../public/manhattan/context/addresses.json",import.meta.url),"utf8"));
  assert.equal(resolveBuildingAddress({...building,bbl:"1000960005"},index),"207 FRONT STREET");
  assert.equal(resolveBuildingAddress({...building,bbl:null},index),null);
  assert.equal(resolveBuildingAddress({...building,address:"1 ACTUAL STREET"},index),"1 ACTUAL STREET");
  assert.equal(resolveBuildingAddress({...building,bbl:"1999999999"},index),null);
});

test("tax block grouping includes same-block lots and adjoining building footprints",()=>{
  const neighbor={...building,id:"neighbor",bbl:"1000010002",center:unprojectMeters([90,50]),footprint:[building.footprint[0].map(([x,y])=>[x+.0005,y] as [number,number])]};
  const far={...building,id:"far",bbl:"1000020001",center:unprojectMeters([900,900]),footprint:[building.footprint[0].map(()=>unprojectMeters([900,900]))]};
  const {bounds,taxBlock}=contextBounds(building,[building,neighbor,far]);
  assert.equal(taxBlock,"100001");
  assert.equal(taxBlockId("1000010002"),"100001");
  assert.equal(taxBlockId("not-a-bbl"),null);
  assert.deepEqual(selectBlockBuildings([neighbor,far],building,bounds).map(b=>b.id),["selected","neighbor"]);
  assert.equal(selectBlockBuildings([{...building,address:"Stale overview"}],building,bounds)[0],building);
  assert.equal(contextBounds({...building,bbl:null},[building]).taxBlock,null);
});

test("street context contains actual named segments and excludes distant streets",async()=>{
  const streets:ContextStreet[]=JSON.parse(await readFile(new URL("../public/manhattan/context/streets.json",import.meta.url),"utf8"));
  const found=selectContextStreets(streets,[-74.004,40.706,-74.001,40.709]);
  assert.ok(found.length>1);
  assert.ok(found.some(s=>s.name.includes("FULTON")));
  assert.ok(found.every(s=>s.coordinates.length>=2));
  assert.ok(found.length<streets.length);
});

test("block DEM crop retains unequal measured samples and missing elevation",()=>{
  const southwest=unprojectMeters([0,0]),northeast=unprojectMeters([200,200]);
  const terrain:TerrainGrid={bounds:[...southwest,...northeast],width:3,height:3,elevationsM:[0,10,20,20,30,40,40,null,60],source:"Measured NAVD88 samples"};
  const crop=cropTerrain(terrain,[...unprojectMeters([10,10]),...unprojectMeters([90,90])]);
  assert.equal(crop.width,2);assert.equal(crop.height,2);
  assert.deepEqual(crop.elevationsM,[0,10,20,30]);
  assert.ok(Math.abs((terrainElevation(unprojectMeters([50,50]),crop)??-1)-15)<.01);
  assert.equal(terrainElevation(unprojectMeters([150,150]),terrain),null);
});

test("neighboring street geometry follows nonplanar DEM instead of one flat plane",()=>{
  const terrain:TerrainGrid={bounds:[...unprojectMeters([0,0]),...unprojectMeters([100,100])],width:2,height:2,elevationsM:[0,10,20,30],source:"Measured samples"};
  const street:ContextStreet={id:"road",name:"Real street",widthM:4,coordinates:[unprojectMeters([10,50]),unprojectMeters([90,50])]};
  const geometry=streetGeometry([street],terrain,terrain.bounds);
  const positions=geometry.getAttribute("position");
  const ys=Array.from({length:positions.count},(_,i)=>positions.getY(i));
  assert.ok(positions.count>12);
  assert.ok(Math.max(...ys)-Math.min(...ys)>7);
  assert.ok(Math.min(...ys)>10);
  geometry.dispose();
  const noData=streetGeometry([street],{...terrain,elevationsM:[null,10,20,30]},terrain.bounds);
  assert.equal(noData.getAttribute("position").count,0);noData.dispose();
});


test("a malformed address asset fails clearly before labels can crash",async()=>{
  const original=globalThis.fetch;
  globalThis.fetch=async()=>new Response(JSON.stringify({"1000010001":42}));
  try {await assert.rejects(loadAddressIndex(),/address index is malformed/);} finally {globalThis.fetch=original;}
});

test("selected block loads local assets, keeps property identity and includes measured cross-boundary context",async()=>{
  const original=globalThis.fetch;
  const urls:string[]=[];
  globalThis.fetch=async(input)=>{
    const url=String(input);urls.push(url);
    assert.ok(url.startsWith("/manhattan/"));
    const body=await readFile(new URL(`../public${url}`,import.meta.url),"utf8");
    return new Response(body,{status:200,headers:{"content-type":"application/json"}});
  };
  try {
    const context=await loadBuildingContext({id:"441",neighborhoodId:"MN0101"});
    assert.equal(context.selected.id,"441");
    assert.equal(context.selected.address,"207 FRONT STREET");
    assert.equal(context.selected.bin,"1082012");
    assert.equal(context.taxBlock,"100096");
    assert.ok(context.buildings.length>1);
    assert.ok(context.streets.length>1);
    assert.ok(urls.includes("/manhattan/terrain-10m.json"));
    const elevations=context.terrain.elevationsM.filter((h):h is number=>h!==null);
    assert.ok(Math.max(...elevations)>Math.min(...elevations));
    assert.match(context.terrain.source,/USGS/);
    assert.equal(context.terrain.raster?.verticalDatum,"NAVD88");
    assert.equal(context.terrain.raster?.nominalSpacingM,10);
    assert.ok(context.terrain.raster!.extent[0]<context.terrain.bounds[0]);
    assert.ok(context.terrain.raster!.extent[2]>context.terrain.bounds[2]);
    const requests = urls.length;
    const again = await loadBuildingContext({id:"441",neighborhoodId:"MN0101"});
    assert.equal(again.selected.id, context.selected.id);
    assert.equal(urls.length, requests, "reopening the block fetched and reparsed map assets");
    const controller = new AbortController(); controller.abort();
    await assert.rejects(loadBuildingContext({id:"441",neighborhoodId:"MN0101"}, controller.signal), { name: "AbortError" });
  } finally {globalThis.fetch=original;}
});





test("exceptionally large tax blocks use a clearly bounded local part",()=>{
  const farSameBlock={...building,id:"far-campus",bbl:"1000010002",footprint:[[unprojectMeters([3000,3000]),unprojectMeters([3010,3000]),unprojectMeters([3010,3010]),unprojectMeters([3000,3010]),unprojectMeters([3000,3000])]]};
  const result=contextBounds(building,[building,farSameBlock]);
  assert.equal(result.taxBlock,"100001");
  assert.equal(result.wholeBlock,false);
  assert.ok(result.bounds[2]-result.bounds[0]<.01);
  assert.ok(result.bounds[3]-result.bounds[1]<.01);
});


test("long adjacent streets are labeled within the visible measured block",()=>{
  const terrain:TerrainGrid={bounds:[...unprojectMeters([0,0]),...unprojectMeters([100,100])],width:2,height:2,elevationsM:[0,10,20,30],source:"Measured samples"};
  const street:ContextStreet={id:"long",name:"Long street",widthM:8,coordinates:[unprojectMeters([-1000,50]),unprojectMeters([200,50])]};
  const label=streetLabelPosition(street,terrain,terrain.bounds);
  assert.ok(label);
  assert.ok(label.point[0]>=terrain.bounds[0] && label.point[0]<=terrain.bounds[2]);
  assert.ok(label.point[1]>=terrain.bounds[1] && label.point[1]<=terrain.bounds[3]);
  assert.ok(Math.abs(label.elevation-15)<.01);
});
