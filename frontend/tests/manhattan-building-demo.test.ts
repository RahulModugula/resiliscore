import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import test from "node:test";
import cache from "../src/data/manhattan/building-demo.json";
import screening from "../src/data/manhattan/screening.json";
import { assessManhattanProperty } from "../src/lib/manhattan/assessment";
import { buildingDemoReceipt, buildingDemoReducer, canCreateBuildingDemoReceipt, initialBuildingDemo, projectBuildingDemo, type BuildingDemoState } from "../src/lib/manhattan/buildingDemo";
import type { Building } from "../src/lib/manhattan/types";

const building: Building = { id: "441", bin: "1082012", bbl: "1000960005", address: "207 FRONT STREET", name: null, center: [-74.002,40.707], footprint: [[[-74.0021,40.7069],[-74.0019,40.7069],[-74.0019,40.7071],[-74.0021,40.7071],[-74.0021,40.7069]]], heightM: 20, groundElevationM: 4, neighborhoodId: "MN0101", yearBuilt: 1900, featureCode: "2100" };

test("every demo combination retains real identity without changing the recorded assessment", async () => {
  for (const yearBuilt of [null,1900,2020]) {
    const { parcel } = await assessManhattanProperty({ ...building, yearBuilt }, { preferLive: false });
    const before = structuredClone(parcel);
    for (const roof of [false,true]) for (const phase of ["planning","captured","reviewed"] as const) {
      const result = projectBuildingDemo(parcel,{ roof,phase });
      assert.deepEqual(result.parcel_identity,parcel.parcel_identity);
      assert.equal(result.indicative_only,true);
      assert.equal(result.public_hazard_layer.freeboard_delta_h_ft,null);
      assert.equal(result.private_verification_layer.elev_cert_verified,false);
      assert.equal(result.private_verification_layer.cv_confidence,phase === "reviewed" ? .99 : 0);
      assert.equal(result.hitl_status.escalated,phase !== "reviewed");
      assert.ok(result.input_provenance?.some(row => row.field === "building_demo" && row.value_source === "DEFAULT"));
      assert.deepEqual(parcel,before);
    }
  }
});

test("live assessment evidence and valuation do not silently become demo assumptions", async () => {
  const { parcel } = await assessManhattanProperty(building,{preferLive:false});
  parcel.parcel_identity.rcv_usd = 2_000_000;
  parcel.public_hazard_layer.fema_flood_zone = "AE";
  parcel.private_verification_layer.elev_cert_verified = true;
  const result = projectBuildingDemo(parcel,{roof:true,phase:"reviewed"});
  assert.equal(result.parcel_identity.rcv_usd,350_000);
  assert.equal(result.public_hazard_layer.fema_flood_zone,"D");
  assert.equal(result.private_verification_layer.elev_cert_verified,false);
  assert.equal(result.uncertainty,null);
  assert.deepEqual(result.factor_contributions,[]);
  assert.equal(parcel.private_verification_layer.elev_cert_verified,true);
  result.parcel_identity.centroid[0] = 0;
  assert.equal(parcel.parcel_identity.centroid[0],building.center[0]);
  assert.throws(() => projectBuildingDemo({...parcel,parcel_identity:{...parcel.parcel_identity,state:"CA"}},initialBuildingDemo),/Manhattan/);
});

test("capture and review gate receipts; changing or resetting the plan revokes review", async () => {
  const { parcel } = await assessManhattanProperty(building,{preferLive:false});
  let state = buildingDemoReducer(initialBuildingDemo,{type:"approve"});
  assert.deepEqual(state,initialBuildingDemo);
  assert.throws(() => buildingDemoReceipt(building.id,parcel,state),/simulated capture and review/);
  state = buildingDemoReducer(state,{type:"roof",selected:true});
  state = buildingDemoReducer(state,{type:"capture"});
  assert.equal(canCreateBuildingDemoReceipt(state,projectBuildingDemo(parcel,state)),false);
  state = buildingDemoReducer(state,{type:"approve"});
  const receipt = buildingDemoReceipt(building.id,parcel,state);
  assert.equal(receipt.demo,true);
  assert.equal(receipt.no_policy_issued,true);
  assert.equal(receipt.building_id,building.id);
  assert.equal(receipt.address,parcel.parcel_identity.address);
  assert.deepEqual(receipt.footprint,parcel.parcel_identity.geometries);
  assert.deepEqual(receipt.centroid,building.center);
  assert.deepEqual(receipt.action_plan,["HAIL_CLASS4_ROOF"]);
  assert.equal(receipt.policy_number,null);
  assert.equal(receipt.filed_quote,null);
  state = buildingDemoReducer(state,{type:"roof",selected:false});
  assert.equal(state.phase,"planning");
  assert.throws(() => buildingDemoReceipt(building.id,parcel,state));
  assert.deepEqual(buildingDemoReducer(state,{type:"reset"}),initialBuildingDemo);
});

test("the cache covers every plan/review state and follows canonical screening inputs", async () => {
  assert.equal(cache.engineSha256,screening.engineSha256);
  assert.equal(cache.screeningSha256,createHash("sha256").update(readFileSync(new URL("../src/data/manhattan/screening.json",import.meta.url))).digest("hex"));
  for (const [era,outputs] of Object.entries(cache.projections)) {
    assert.deepEqual(Object.keys(outputs).sort(),["0:0","0:1","1:0","1:1"]);
    const { parcel } = await assessManhattanProperty({...building,yearBuilt:era === "pre2002" ? 1900 : 2020},{preferLive:false});
    for (const [key,output] of Object.entries(outputs)) {
      const [roof,reviewed] = key.split(":").map(Number);
      const state: BuildingDemoState = {roof:!!roof,phase:reviewed ? "reviewed" : "planning"};
      const actual = projectBuildingDemo(parcel,state);
      assert.deepEqual(actual.actuarial_breakdown,output.actuarial_breakdown);
      assert.deepEqual(actual.premium_build,output.premium_build);
    }
  }
});
