import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { test } from "node:test";
import { assessManhattanProperty, loadManhattanAssessment, propertyLabel, saveManhattanAssessment } from "../src/lib/manhattan/assessment";
import { parseParcel } from "../src/lib/contract";
import type { Building } from "../src/lib/manhattan/types";
import screening from "../src/data/manhattan/screening.json";

const building: Building = { id: "123456", bin: "1000001", bbl: "1000010001", address: null, name: null, center: [-74.005, 40.715], footprint: [[[-74.0051, 40.7149], [-74.0049, 40.7149], [-74.0049, 40.7151], [-74.0051, 40.7151], [-74.0051, 40.7149]]], heightM: 15, groundElevationM: 7.2, neighborhoodId: "MN0101", yearBuilt: null, featureCode: "2100" };

test("offline screening preserves selected property geometry and never fabricates verification", async () => {
  const result = await assessManhattanProperty(building, { preferLive: false });
  const p = result.parcel;
  assert.equal(result.source, "local");
  assert.match(result.notice, /nonlocal FEMA NRI/);
  assert.equal(p.parcel_identity.address, "BIN 1000001, Manhattan, NY");
  assert.equal(p.parcel_identity.state, "NY");
  assert.equal(p.parcel_identity.county_fips, "36061");
  assert.notEqual(p.parcel_identity.apn_uid, building.bbl);
  assert.deepEqual(p.parcel_identity.centroid, building.center);
  assert.deepEqual(p.parcel_identity.geometries.features[0].geometry.coordinates, building.footprint);
  assert.equal(p.indicative_only, true);
  assert.equal(p.private_verification_layer.elev_cert_verified, false);
  assert.equal(p.private_verification_layer.cv_confidence, 0);
  assert.equal(p.private_verification_layer.ibhs_fortified_tier, "NONE");
  assert.equal(p.actuarial_breakdown.statutory_discount_pct, 0);
  assert.equal(p.public_hazard_layer.usgs_lag_ft, null);
  assert.equal(p.public_hazard_layer.freeboard_delta_h_ft, null);
  assert.ok(p.input_provenance?.some(row => row.value_source === "REFERENCE_PARCEL"));
  assert.equal(parseParcel(p), p);
});

test("offline risk values are canonical cached engine output selected by construction era", async () => {
  for (const year of [null, 1900, 2001, 2002, 2024]) {
    const result = await assessManhattanProperty({ ...building, yearBuilt: year }, { preferLive: false });
    const expected = (year ?? 1990) < 2002 ? screening.screens.pre2002 : screening.screens.post2002;
    assert.deepEqual(result.parcel.actuarial_breakdown, expected.actuarial_breakdown);
    assert.equal(result.parcel.parcel_identity.year_built, year ?? 1990);
    assert.equal(result.parcel.input_provenance?.find(row => row.field === "year_built")?.value_source, year === null ? "DEFAULT" : "LIVE");
  }
});

test("screening cache guard requires regeneration whenever canonical engine inputs change", () => {
  const root = resolve(import.meta.dirname, "../..");
  const hash = createHash("sha256");
  for (const path of screening.engineFiles) { hash.update(path); hash.update(readFileSync(resolve(root, path))); }
  assert.equal(hash.digest("hex"), screening.engineSha256, "Regenerate with frontend/scripts/generate-manhattan-screening.py");
});

test("live request sends selected NYC coordinates and outer footprint, with no golden scenario", async t => {
  const local = await assessManhattanProperty(building, { preferLive: false });
  let request: Record<string, unknown> = {};
  t.mock.method(globalThis, "fetch", async (_url: unknown, init?: RequestInit) => {
    request = JSON.parse(String(init?.body));
    return Response.json(local.parcel);
  });
  const live = await assessManhattanProperty({ ...building, yearBuilt: 1920 });
  assert.equal(live.source, "live");
  assert.deepEqual(request, { address: "BIN 1000001, Manhattan, NY", lat: 40.715, lng: -74.005, county_fips: "36061", state: "NY", footprint: building.footprint[0], year_built: 1920 });
  assert.equal("scenario_id" in request, false);
});

test("backend outage, malformed payload, or another property's response fall back without swapping parcels", async t => {
  for (const response of [() => { throw new TypeError("offline"); }, () => Response.json({}), () => Response.json(screening.screens.pre2002)]) {
    t.mock.method(globalThis, "fetch", response);
    const result = await assessManhattanProperty(building);
    assert.equal(result.source, "local");
    assert.deepEqual(result.parcel.parcel_identity.centroid, building.center);
    t.mock.restoreAll();
  }
});

test("caller cancellation rejects rather than opening a stale property", async () => {
  const controller = new AbortController();
  controller.abort();
  await assert.rejects(assessManhattanProperty(building, { signal: controller.signal }), { name: "AbortError" });
});

test("session handoff validates payloads, expires after six hours, and tolerates blocked storage", async t => {
  const data = new Map<string, string>();
  const sessionStorage = { getItem: (key: string) => data.get(key) ?? null, setItem: (key: string, value: string) => data.set(key, value) };
  Object.defineProperty(globalThis, "window", { value: { sessionStorage }, configurable: true });
  t.after(() => { Reflect.deleteProperty(globalThis, "window"); });
  const result = await assessManhattanProperty(building, { preferLive: false });
  assert.equal(saveManhattanAssessment(building.id, result), true);
  assert.deepEqual(loadManhattanAssessment(building.id), result);
  assert.equal(saveManhattanAssessment("different", result), false);
  const key = [...data.keys()][0];
  const saved = JSON.parse(data.get(key)!);
  data.set(key, JSON.stringify({ ...saved, savedAt: Date.now() - 7 * 60 * 60 * 1000 }));
  assert.equal(loadManhattanAssessment(building.id), null);
  data.set(key, JSON.stringify({ ...saved, result: { ...result, property: { ...result.property, name: {} } } }));
  assert.equal(loadManhattanAssessment(building.id), null);
  data.set(key, "malformed");
  assert.equal(loadManhattanAssessment(building.id), null);
  t.mock.method(sessionStorage, "setItem", () => { throw new Error("blocked"); });
  assert.equal(saveManhattanAssessment(building.id, result), false);
});

test("identifier labels use a mapped name or BIN without inventing a street address", () => {
  assert.equal(propertyLabel(building), "BIN 1000001");
  assert.equal(propertyLabel({ ...building, bin: null }), "Building 123456");
  assert.equal(propertyLabel({ ...building, name: "Mapped landmark" }), "Mapped landmark");
});
