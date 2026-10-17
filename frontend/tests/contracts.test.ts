import assert from "node:assert/strict";
import { test } from "node:test";
import Ajv2020 from "ajv/dist/2020";
import addFormats from "ajv-formats";
import schema from "../../contracts/parcel_score_schema.json";
import fixtures from "../../contracts/golden_scenarios.json";
import { getScenario, goldenScenarios, scenarios } from "../src/data/goldenScenarios";

test("every golden response validates against the canonical JSON Schema", () => {
  const ajv = new Ajv2020({ allErrors: true, strict: false });
  addFormats(ajv);
  const validate = ajv.compile(schema);
  for (const [name, fixture] of Object.entries(fixtures)) {
    assert.equal(validate(fixture), true, `${name}: ${ajv.errorsText(validate.errors)}`);
  }
});

test("scenario selector exposes the three demo journeys and returns independent payloads", () => {
  assert.equal(scenarios.length, 3);
  for (const { id } of scenarios) {
    const first = getScenario(id);
    const second = getScenario(id);
    assert.deepEqual(first, fixtures[id]);
    first.parcel_identity.address = "Modified copy";
    first.parcel_identity.geometries.features.length = 0;
    assert.deepEqual(second, fixtures[id]);
    assert.deepEqual(goldenScenarios[id], fixtures[id]);
  }
});

test("the unpermitted variant preserves score while explicitly holding auto-bind", () => {
  const clear = getScenario("SCENARIO_3_ESCONDIDO_HITL");
  const alerted = getScenario("SCENARIO_3_ESCONDIDO_HITL__UNPERMITTED");
  assert.equal(clear.actuarial_breakdown.resili_score, fixtures.SCENARIO_3_ESCONDIDO_HITL.actuarial_breakdown.resili_score);
  assert.equal(alerted.actuarial_breakdown.resili_score, clear.actuarial_breakdown.resili_score);
  assert.equal(clear.hitl_status.escalated, false);
  assert.equal(alerted.hitl_status.escalated, true);
  assert.equal(alerted.hitl_status.trigger_code, "HITL_TRIGGER_02_UNPERMITTED_ADDITION");
  assert.equal(alerted.private_verification_layer.unpermitted_footprint_delta_sqft, 240);
  assert.ok(alerted.parcel_identity.geometries.features.some(feature => /240 sq ft/.test(feature.properties.label ?? "")));
});
