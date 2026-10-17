import assert from "node:assert/strict";
import { test } from "node:test";
import Ajv2020 from "ajv/dist/2020";
import addFormats from "ajv-formats";
import schema from "../../contracts/parcel_score_schema.json";
import fixtures from "../../contracts/golden_scenarios.json";
import { findScenario, getScenario, goldenScenarios, scenarios } from "../src/data/goldenScenarios";

test("every golden response validates against the canonical JSON Schema", () => {
  const ajv = new Ajv2020({ allErrors: true, strict: false });
  addFormats(ajv);
  const validate = ajv.compile(schema);
  for (const [name, fixture] of Object.entries(fixtures)) {
    assert.equal(validate(fixture), true, `${name}: ${ajv.errorsText(validate.errors)}`);
  }
});

test("scenario selector exposes the six demo journeys and returns independent payloads", () => {
  assert.equal(scenarios.length, 6);
  for (const { id } of scenarios) {
    if (!goldenScenarios[id]) {
      assert.ok(id.startsWith("NYC_"));
      assert.equal(findScenario(id), null);
      continue;
    }
    const first = getScenario(id);
    const second = getScenario(id);
    assert.deepEqual(first, goldenScenarios[id]);
    first.parcel_identity.address = "Modified copy";
    first.parcel_identity.geometries.features.length = 0;
    assert.deepEqual(second, goldenScenarios[id]);
  }
});

test("the unpermitted variant preserves score while explicitly holding auto-bind", () => {
  const clear = getScenario("SCENARIO_3_ESCONDIDO_HITL");
  const alerted = getScenario("SCENARIO_3_ESCONDIDO_HITL__UNPERMITTED");
  assert.equal(alerted.actuarial_breakdown.resili_score, clear.actuarial_breakdown.resili_score);
  assert.equal(clear.hitl_status.escalated, false);
  assert.equal(alerted.hitl_status.escalated, true);
  assert.equal(alerted.hitl_status.trigger_code, "HITL_TRIGGER_02_UNPERMITTED_ADDITION");
  assert.equal(alerted.private_verification_layer.unpermitted_footprint_delta_sqft, 240);
  assert.ok(alerted.parcel_identity.geometries.features.some(feature => /240 sq ft/.test(feature.properties.label ?? "")));
});

test("NYC selector IDs and addresses match the pending contract", () => {
  assert.deepEqual(scenarios.filter(s => s.id.startsWith("NYC_")).map(s => [s.id, s.address]), [
    ["NYC_RED_HOOK", "5 Luquer St"], ["NYC_HOLLIS", "81-52 192 St"], ["NYC_ROCKAWAY", "74-02 Beach Channel Dr"],
  ]);
});
