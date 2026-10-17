import assert from "node:assert/strict";
import { test } from "node:test";
import { getScenario, goldenScenarios } from "../src/data/goldenScenarios";
import { actionTotals, applyStructureLoading, simulateMitigations, tierForScore } from "../src/lib/simulation";

const wildfireId = "SCENARIO_2_CA_WUI";
const allActions = goldenScenarios[wildfireId].prescriptive_mitigations.map(action => action.action_id);
const closeTo = (actual: number, expected: number) => assert.ok(Math.abs(actual - expected) < 1e-10, `${actual} differs from ${expected}`);

test("wildfire plan reproduces the contract deltas and preserves financial consistency", () => {
  const baseline = getScenario(wildfireId);
  const result = simulateMitigations(baseline, allActions);
  const a = result.actuarial_breakdown;
  assert.equal(a.resili_score, 630);
  assert.equal(a.underwriting_tier, "TIER_2_CONDITIONAL");
  assert.equal(a.annual_discounted_premium_usd, 9060);
  closeTo(a.posterior_lcr, 0.017);
  closeTo(a.expected_annual_loss_usd, 14450);
  closeTo(a.peril_split.reduce((sum, item) => sum + item.peril_aal_usd, 0), a.expected_annual_loss_usd);
  closeTo(a.credibility_weight_z * a.parcel_raw_lcr + (1 - a.credibility_weight_z) * a.tract_prior_lcr, a.posterior_lcr);
  assert.deepEqual(actionTotals(baseline, allActions), { net: 19500, gross: 19500, grants: 0, savings: 2140 });
  assert.deepEqual(baseline, goldenScenarios[wildfireId]);
});

test("plans are reversible, deterministic, and count a selected action only once", () => {
  const baseline = getScenario(wildfireId);
  const selection = [allActions[0], allActions[0], "unknown-action"];
  const first = simulateMitigations(baseline, selection);
  assert.equal(first.actuarial_breakdown.resili_score, 450);
  assert.deepEqual(first, simulateMitigations(baseline, [allActions[0]]));
  assert.deepEqual(first, simulateMitigations(baseline, selection));
  assert.deepEqual(actionTotals(baseline, selection), { net: 1800, gross: 1800, grants: 0, savings: 680 });
  assert.deepEqual(simulateMitigations(baseline, []), baseline);
  assert.deepEqual(simulateMitigations(baseline, ["unknown-action"]), baseline);
});

test("verified Louisiana and Escondido actions cannot earn a second discount", () => {
  for (const id of ["SCENARIO_1_LA_FLOOD", "SCENARIO_3_ESCONDIDO_HITL"] as const) {
    const baseline = getScenario(id);
    const ids = baseline.prescriptive_mitigations.map(action => action.action_id);
    assert.deepEqual(simulateMitigations(baseline, ids), baseline);
    assert.deepEqual(actionTotals(baseline, ids), { net: 0, gross: 0, grants: 0, savings: 0 });
  }
});

test("clearance updates the map evidence and matching California factors only", () => {
  const baseline = getScenario(wildfireId);
  const result = simulateMitigations(baseline, ["CA_ZONE0_1_CLEARANCE"]);
  const p = result.private_verification_layer;
  assert.equal(p.cv_zone0_clear, true);
  assert.equal(p.cv_zone1_no_shed, true);
  assert.equal(p.cv_overhang_ft, 0);
  assert.equal(p.cv_ember_vents, baseline.private_verification_layer.cv_ember_vents);
  const factors = result.regulatory_compliance.ca_2644_9_factors;
  assert.equal(factors.cat_b1_zone0_clear_0_5ft, true);
  assert.equal(factors.cat_b1_no_sheds_within_30ft, true);
  assert.equal(factors.cat_b1_prc_4291_compliance, true);
  const remaining = result.parcel_identity.geometries.features;
  assert.equal(remaining.some(feature => feature.properties.kind === "cv_detection" && /canopy|shed/i.test(feature.properties.label ?? "")), false);
  assert.deepEqual(remaining.filter(feature => feature.properties.kind !== "cv_detection"), baseline.parcel_identity.geometries.features.filter(feature => feature.properties.kind !== "cv_detection"));
  assert.ok(baseline.parcel_identity.geometries.features.length > remaining.length);
});

test("roof and vents select their supplied evidence without claiming unrelated compliance", () => {
  const baseline = getScenario(wildfireId);
  const result = simulateMitigations(baseline, ["CA_EMBER_VENTS_EAVES", "CA_IBHS_WPH_CLASS_A_ROOF"]);
  assert.equal(result.private_verification_layer.cv_ember_vents, true);
  assert.equal(result.private_verification_layer.cv_enclosed_eaves, true);
  assert.equal(result.private_verification_layer.cv_roof_class, "CLASS_A_ASPHALT");
  assert.equal(result.regulatory_compliance.ca_2644_9_factors.cat_b2_class_a_roof, true);
  assert.equal(result.regulatory_compliance.ca_2644_9_factors.cat_b1_zone0_clear_0_5ft, false);
  assert.equal(result.private_verification_layer.cv_zone1_no_shed, false);
});

test("structure review increases RCV and loss cost, and releases only a conditional bind", () => {
  const baseline = getScenario("SCENARIO_3_ESCONDIDO_HITL__UNPERMITTED");
  const original = structuredClone(baseline);
  const result = applyStructureLoading(baseline);
  assert.equal(result.parcel_identity.rcv_usd, 780000);
  closeTo(result.actuarial_breakdown.posterior_lcr, baseline.actuarial_breakdown.posterior_lcr + 35 / 10000);
  closeTo(result.actuarial_breakdown.expected_annual_loss_usd, 4134);
  assert.equal(result.actuarial_breakdown.underwriting_tier, "TIER_2_CONDITIONAL");
  const a = result.actuarial_breakdown;
  closeTo(a.peril_split.reduce((sum, item) => sum + item.peril_aal_usd, 0), a.expected_annual_loss_usd);
  closeTo(a.credibility_weight_z * a.parcel_raw_lcr + (1 - a.credibility_weight_z) * a.tract_prior_lcr, a.posterior_lcr);
  assert.equal(result.hitl_status.escalated, false);
  assert.match(result.hitl_status.recommended_underwriter_action ?? "", /permit review within 60 days/i);
  assert.equal(result.private_verification_layer.unpermitted_footprint_delta_sqft, 240);
  assert.deepEqual(baseline, original);
});

test("underwriting tiers use the inclusive 580 and 720 boundaries", () => {
  assert.equal(tierForScore(579), "TIER_3_DECLINE_ESCALATE");
  assert.equal(tierForScore(580), "TIER_2_CONDITIONAL");
  assert.equal(tierForScore(719), "TIER_2_CONDITIONAL");
  assert.equal(tierForScore(720), "TIER_1_AUTO_BIND");
});
