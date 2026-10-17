import { goldenScenarios, getGoldenSimulation } from "@/data/goldenScenarios";
import type { GoldenScenarioKey, ParcelScoreResponse, UnderwritingTier } from "@/types/resiliscore";

export function tierForScore(score: number): UnderwritingTier {
  return score >= 720 ? "TIER_1_AUTO_BIND" : score >= 580 ? "TIER_2_CONDITIONAL" : "TIER_3_DECLINE_ESCALATE";
}

// Offline projections use the engine's complete action-subset summaries.
export function simulateMitigations(base: ParcelScoreResponse, actionIds: string[], scenarioId?: GoldenScenarioKey): ParcelScoreResponse {
  const result = structuredClone(base);
  const actions = base.prescriptive_mitigations.filter(a => !a.currently_applied && actionIds.includes(a.action_id));
  if (actions.length === 0) return result;
  const id = scenarioId ?? Object.entries(goldenScenarios).find(([, parcel]) => parcel?.request_id === base.request_id)?.[0];
  const summary = id ? getGoldenSimulation(id, actions.map(a => a.action_id)) : undefined;
  if (!summary) throw new Error("Offline simulation is unavailable for this action plan");
  const a = result.actuarial_breakdown;
  Object.assign(a, {
    resili_score: summary.resili_score, underwriting_tier: summary.underwriting_tier,
    posterior_lcr: summary.posterior_lcr, credibility_weight_z: summary.credibility_weight_z,
    expected_annual_loss_usd: summary.expected_annual_loss_usd,
    statutory_discount_pct: summary.statutory_discount_pct,
    annual_discounted_premium_usd: summary.annual_discounted_premium_usd,
  });
  a.parcel_raw_lcr = a.credibility_weight_z > 0
    ? Math.max(0, (a.posterior_lcr - (1 - a.credibility_weight_z) * a.tract_prior_lcr) / a.credibility_weight_z)
    : base.actuarial_breakdown.parcel_raw_lcr;
  const priorTotal = a.peril_split.reduce((sum, item) => sum + item.peril_aal_usd, 0);
  if (priorTotal > 0) a.peril_split.forEach(item => { item.peril_aal_usd *= a.expected_annual_loss_usd / priorTotal; });
  result.hitl_status.trigger_code = summary.trigger_code;
  result.hitl_status.escalated = summary.trigger_code !== "NONE";
  const p = result.private_verification_layer;
  const factors = result.regulatory_compliance.ca_2644_9_factors;
  for (const action of actions) {
    if (action.action_id === "CA_ZONE0_1_CLEARANCE") {
      p.cv_zone0_clear = true; p.cv_zone1_no_shed = true; p.cv_overhang_ft = 0;
      factors.cat_b1_zone0_clear_0_5ft = true; factors.cat_b1_no_sheds_within_30ft = true; factors.cat_b1_prc_4291_compliance = true;
      result.parcel_identity.geometries.features = result.parcel_identity.geometries.features.filter(f => f.properties.kind !== "cv_detection" || !/canopy|shed/i.test(f.properties.label ?? ""));
    }
    if (action.action_id === "CA_EMBER_VENTS_EAVES") {
      p.cv_ember_vents = true; p.cv_enclosed_eaves = true;
      factors.cat_b2_ember_vents = true; factors.cat_b2_enclosed_eaves = true;
    }
    if (action.action_id === "CA_IBHS_WPH_CLASS_A_ROOF") {
      p.cv_roof_class = "CLASS_A_ASPHALT"; factors.cat_b2_class_a_roof = true;
    }
  }
  return result;
}

export function applyStructureLoading(base: ParcelScoreResponse): ParcelScoreResponse {
  const result = structuredClone(base);
  result.parcel_identity.rcv_usd += 240 * 250; // Demo assumption: $250/sq ft.
  result.actuarial_breakdown.posterior_lcr += 35 / 10000;
  result.actuarial_breakdown.expected_annual_loss_usd = result.actuarial_breakdown.posterior_lcr * result.parcel_identity.rcv_usd;
  const a = result.actuarial_breakdown;
  a.parcel_raw_lcr = (a.posterior_lcr - (1 - a.credibility_weight_z) * a.tract_prior_lcr) / a.credibility_weight_z;
  const priorTotal = a.peril_split.reduce((sum, item) => sum + item.peril_aal_usd, 0);
  if (priorTotal > 0) a.peril_split.forEach(item => { item.peril_aal_usd *= a.expected_annual_loss_usd / priorTotal; });
  result.actuarial_breakdown.underwriting_tier = "TIER_2_CONDITIONAL";
  result.hitl_status = { escalated: false, trigger_code: "NONE", trigger_reason: null, recommended_underwriter_action: "Demo loading accepted. Conditional bind requires permit review within 60 days." };
  return result;
}

export function actionTotals(base: ParcelScoreResponse, ids: string[], projected = simulateMitigations(base, ids), scenarioId?: GoldenScenarioKey) {
  const totals = base.prescriptive_mitigations.filter(a => !a.currently_applied && ids.includes(a.action_id)).reduce((total, a) => ({
    net: total.net + a.net_capex_usd, gross: total.gross + a.gross_capex_usd,
    grants: total.grants + a.grant_subsidy_usd,
  }), { net: 0, gross: 0, grants: 0 });
  const id = scenarioId ?? Object.entries(goldenScenarios).find(([, parcel]) => parcel?.request_id === base.request_id)?.[0];
  const selected = base.prescriptive_mitigations.filter(a => !a.currently_applied && ids.includes(a.action_id)).map(a => a.action_id);
  const summary = id ? getGoldenSimulation(id, selected) : undefined;
  const net = summary?.net_capex_usd ?? totals.net;
  return { ...totals, net, gross: net + totals.grants, savings: base.actuarial_breakdown.annual_discounted_premium_usd - projected.actuarial_breakdown.annual_discounted_premium_usd };
}
