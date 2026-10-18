import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import { DoubleSide, Mesh, MeshBasicMaterial, Raycaster, Vector3 } from "three";
import { flatFootprintGeometry, streetGeometry, streetLabelPosition } from "../src/lib/manhattan/blockGeometry";
import { loadBuildingContext } from "../src/lib/manhattan/blockContext";
import { decodeElevation } from "../src/lib/manhattan/detailedElevation";
import { blockBuildingPlacement } from "../src/lib/manhattan/blockElevation";
import { loadTransportDecks } from "../src/lib/manhattan/transportStructures";
import { terrainElevation, worldPoint } from "../src/lib/manhattan/sceneGeometry";
import { unprojectMeters } from "../src/lib/manhattan/geo";
import type { TerrainGrid } from "../src/lib/manhattan/types";

test("a level street beside a lower tunnel approach does not fold its width into the excavation", () => {
  const terrain: TerrainGrid = {
    bounds: [...unprojectMeters([0, 0]), ...unprojectMeters([40, 40])], width: 5, height: 5,
    elevationsM: Array.from({ length: 25 }, (_, i) => Math.floor(i / 5) <= 1 ? 0 : 6),
    source: "Two ground levels separated by a retaining wall",
  };
  const street = { id: "upper-street", name: "Upper street", widthM: 20,
    coordinates: [unprojectMeters([5, 20]), unprojectMeters([35, 20])] };
  const deck = {id:"observed-deck",sourceId:"source",status:"Unchanged",streetIds:[street.id],bounds:terrain.bounds,
    rings:[[[5,10],[35,10],[35,30],[5,30],[5,10]].map(([x,y]):[number,number,number]=>[...unprojectMeters([x,y]),6])]};
  const geometry = streetGeometry([street], terrain, terrain.bounds, [deck]);
  const positions = geometry.getAttribute("position");
  assert.ok(positions.count > 0);
  const lowest = Math.min(...Array.from({ length: positions.count }, (_, i) => positions.getY(i)));
  geometry.dispose();
  assert.ok(lowest >= 6, `Upper street bends into lower ground at ${lowest.toFixed(2)} m`);
});

test("an unassociated lower road remains below the deck rather than being lifted to its height", () => {
  const terrain:TerrainGrid={bounds:[...unprojectMeters([0,0]),...unprojectMeters([40,40])],width:2,height:2,elevationsM:[0,0,0,0],source:"Lower ground"};
  const street={id:"lower-road",name:"Lower road",widthM:8,coordinates:[unprojectMeters([20,5]),unprojectMeters([20,35])]};
  const deck={id:"upper",sourceId:"upper",status:"Unchanged",streetIds:["upper-road"],bounds:terrain.bounds,
    rings:[[[10,10],[30,10],[30,30],[10,30],[10,10]].map(([x,y]):[number,number,number]=>[...unprojectMeters([x,y]),6])]};
  const geometry=streetGeometry([street],terrain,terrain.bounds,[deck]);
  const positions=geometry.getAttribute("position");
  assert.ok(Array.from({length:positions.count},(_,i)=>positions.getY(i)).some(h=>Math.abs(h-.3)<1e-5));
  assert.ok(Array.from({length:positions.count},(_,i)=>positions.getY(i)).some(h=>Math.abs(h-6.3)<1e-5));
  geometry.dispose();
});

test("road approaches meet the sourced deck edge without retaining an interpolated dip outside the deck",()=>{
  const terrain:TerrainGrid={bounds:[...unprojectMeters([0,0]),...unprojectMeters([40,40])],width:5,height:5,
    elevationsM:Array.from({length:25},(_,i)=>i%5===2 ? 0 : 6),source:"Excavation below a bridge"};
  const street={id:"upper-road",name:"Upper road",widthM:8,coordinates:[unprojectMeters([5,20]),unprojectMeters([35,20])]};
  const deck={id:"upper",sourceId:"upper",status:"Unchanged",streetIds:[street.id],bounds:terrain.bounds,
    rings:[[[12,10],[28,10],[28,30],[12,30],[12,10]].map(([x,y]):[number,number,number]=>[...unprojectMeters([x,y]),6])]};
  const geometry=streetGeometry([street],terrain,terrain.bounds,[deck]),p=geometry.getAttribute("position");
  const low=Math.min(...Array.from({length:p.count},(_,i)=>p.getY(i)));
  geometry.dispose();assert.ok(low>=6,`The road approach retained a false dip at ${low} m`);
});

test("the exact Second Avenue tunnel crossing renders its sourced deck over unchanged bare earth", async () => {
  const bytes=await readFile("tests/fixtures/elevation/usgs-block-412518.tif");
  const metadata=JSON.parse(await readFile("tests/fixtures/elevation/usgs-block-412518.json","utf8"));
  assert.equal(createHash("sha256").update(bytes).digest("hex"),metadata.sha256);
  const terrain=await decodeElevation(new Uint8Array(bytes).buffer), before=structuredClone(terrain);
  const original=globalThis.fetch;
  try {
    const bundle=JSON.parse(await readFile("public/manhattan/context/transport-decks.json","utf8"));
    globalThis.fetch=async()=>Response.json({...bundle,elevationUnit:"foot"});
    await assert.rejects(loadTransportDecks(terrain.bounds),/malformed/);
    globalThis.fetch=async path=>new Response(await readFile(`public${path}`));
    const context=await loadBuildingContext({id:"412518",neighborhoodId:"MN0603"});
    assert.deepEqual(context.transportDecks!.map(d=>d.id),["205","206"]);
    assert.deepEqual(context.transportDecks!.flatMap(d=>d.streetIds).sort(),["2113:0","2114:0","2207:0","2208:0","79426:0","79430:0"]);
    const label=streetLabelPosition(context.streets.find(s=>s.id==="2207:0")!,terrain,context.bounds,context.transportDecks);
    assert.ok(label && label.elevation>7.1 && label.elevation<7.7,"street labels must follow their associated deck, not the ground below it");
    const point:[number,number]=[-73.97462485673158,40.74650764617556];
    assert.ok(terrainElevation(point,terrain)!<2,"the source must retain the lower terrain beneath the bridge");
    const material=new MeshBasicMaterial({side:DoubleSide});
    const cast=(geometry:ReturnType<typeof streetGeometry>)=>{
      const [x,,z]=worldPoint(point), ray=new Raycaster(new Vector3(x,100,z),new Vector3(0,-1,0));
      return ray.intersectObject(new Mesh(geometry,material)).map(hit=>hit.point.y);
    };
    const old=streetGeometry(context.streets,terrain,context.bounds);
    assert.ok(cast(old).some(h=>h<2),"baseline must reproduce the street draped into the excavation");old.dispose();
    const corrected=streetGeometry(context.streets,terrain,context.bounds,context.transportDecks);
    const heights=cast(corrected);
    assert.ok(heights.length>0);
    assert.ok(heights.every(h=>h>7.4 && h<8),`Expected only the sourced deck at the crossing, got ${heights}`);
    corrected.dispose();material.dispose();
    assert.deepEqual(terrain,before,"a bridge correction must not fill or edit the bare-earth raster");
    const placement=blockBuildingPlacement(context.selected,terrain);
    assert.equal(placement.conflict,true);
    assert.equal(context.selected.heightM,5.79);
    assert.equal(context.selected.groundElevationM,6.1);
    const outline=flatFootprintGeometry([{building:context.selected,elevationM:context.selected.groundElevationM!}]);
    const ys=outline.getAttribute("position");
    assert.ok(ys.count>0);
    assert.ok(Array.from({length:ys.count},(_,i)=>ys.getY(i)).every(h=>Math.abs(h-6.3)<1e-5));outline.dispose();
  } finally {globalThis.fetch=original;}
});
