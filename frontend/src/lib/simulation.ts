import type { ParcelScoreResponse, UnderwritingTier } from "@/types/resiliscore";
import { goldenScenarios } from "../data/goldenScenarios";
import { goldenSimulations } from "../data/goldenSimulations";

export function tierForScore(score: number): UnderwritingTier {
  return score >= 720 ? "TIER_1_AUTO_BIND" : score >= 580 ? "TIER_2_CONDITIONAL" : "TIER_3_DECLINE_ESCALATE";
}

function selectedSummary(base: ParcelScoreResponse, actionIds: string[]) {
  const scenario = (Object.keys(goldenScenarios) as Array<keyof typeof goldenScenarios>).find(key => goldenScenarios[key].request_id === base.request_id);
  const summary = scenario && goldenSimulations[scenario][[...actionIds].sort().join("+")];
  if (!summary) throw new Error("This action combination has no offline model result");
  return summary;
}

// Combined outcomes come from the backend-generated table, as required by D2.
// Per-action credits are not additive, and existing verified actions earn no second credit.
export function simulateMitigations(base: ParcelScoreResponse, actionIds: string[]): ParcelScoreResponse {
  const result = structuredClone(base);
  const actions = base.prescriptive_mitigations.filter(a => actionIds.includes(a.action_id));
  if (actions.length === 0) return result;
  const summary = selectedSummary(base, actions.map(action => action.action_id));
  const a = result.actuarial_breakdown;
  const outcomeChanged = Object.entries(summary).some(([field, value]) => Object.hasOwn(a, field) && Reflect.get(a, field) !== value) || result.hitl_status.trigger_code !== summary.trigger_code;
  if (actions.every(action => action.currently_applied) && !outcomeChanged) return result;
  a.resili_score = summary.resili_score;
  a.underwriting_tier = summary.underwriting_tier;
  a.posterior_lcr = summary.posterior_lcr;
  a.credibility_weight_z = summary.credibility_weight_z;
  a.parcel_raw_lcr = Math.max(0, (a.posterior_lcr - (1 - a.credibility_weight_z) * a.tract_prior_lcr) / a.credibility_weight_z);
  a.expected_annual_loss_usd = summary.expected_annual_loss_usd;
  // The summary has no fitted peril allocation; retain the demo allocation only.
  const priorTotal = a.peril_split.reduce((sum, item) => sum + item.peril_aal_usd, 0);
  if (priorTotal > 0) a.peril_split.forEach(item => { item.peril_aal_usd *= a.expected_annual_loss_usd / priorTotal; });
  a.annual_discounted_premium_usd = summary.annual_discounted_premium_usd;
  a.statutory_discount_pct = summary.statutory_discount_pct;
  result.hitl_status = { escalated: summary.trigger_code !== "NONE", trigger_code: summary.trigger_code, trigger_reason: summary.trigger_code === "NONE" ? null : "The backend model result requires human review.", recommended_underwriter_action: null };
  // These details are absent from the summary. Do not export baseline evidence as a new fit.
  result.uncertainty = null;
  result.premium_build = null;
  result.factor_contributions = [];
  const p = result.private_verification_layer;
  const factors = result.regulatory_compliance.ca_2644_9_factors;
  for (const action of actions) {
    if (action.action_id === "CA_ZONE0_1_CLEARANCE" || action.action_id === "CA_IBHS_WPH_PLUS") {
      p.cv_zone0_clear = true; p.cv_zone1_no_shed = true; p.cv_overhang_ft = 0;
      factors.cat_b1_zone0_clear_0_5ft = true; factors.cat_b1_no_sheds_within_30ft = true; factors.cat_b1_prc_4291_compliance = true;
      result.parcel_identity.geometries.features = result.parcel_identity.geometries.features.filter(f => f.properties.kind !== "cv_detection" || !/canopy|shed/i.test(f.properties.label ?? ""));
    }
    if (action.action_id === "CA_EMBER_VENTS_EAVES" || action.action_id === "CA_IBHS_WPH_PLUS") {
      p.cv_ember_vents = true; p.cv_enclosed_eaves = true;
      factors.cat_b2_ember_vents = true; factors.cat_b2_enclosed_eaves = true;
    }
    if (action.action_id === "CA_IBHS_WPH_CLASS_A_ROOF" || action.action_id === "CA_IBHS_WPH_PLUS") {
      if (p.cv_roof_class === "WOOD_SHAKE_UNRATED") p.cv_roof_class = "CLASS_A_ASPHALT";
      if (action.action_id === "CA_IBHS_WPH_PLUS") p.ibhs_wph_tier = "PLUS";
      else if (p.ibhs_wph_tier === "NONE") p.ibhs_wph_tier = "BASE";
      factors.cat_b2_class_a_roof = true;
    }
    if (action.action_id === "HAIL_CLASS4_ROOF") p.cv_roof_class = "CLASS_A_IMPACT_4";
    if (action.action_id === "SMART_WATER_SHUTOFF") p.iot_shutoff_active = true;
  }
  return result;
}

export function applyStructureLoading(base: ParcelScoreResponse): ParcelScoreResponse {
  const result = structuredClone(base);
  result.parcel_identity.rcv_usd += 240 * 250; // Demo assumption: $250/sq ft.
  result.actuarial_breakdown.posterior_lcr += 35 / 10000;
  result.actuarial_breakdown.expected_annual_loss_usd = result.actuarial_breakdown.posterior_lcr * result.parcel_identity.rcv_usd;
  const a = result.actuarial_breakdown;
  result.uncertainty = null;
  result.premium_build = null;
  result.factor_contributions = [];
  a.parcel_raw_lcr = (a.posterior_lcr - (1 - a.credibility_weight_z) * a.tract_prior_lcr) / a.credibility_weight_z;
  const priorTotal = a.peril_split.reduce((sum, item) => sum + item.peril_aal_usd, 0);
  if (priorTotal > 0) a.peril_split.forEach(item => { item.peril_aal_usd *= a.expected_annual_loss_usd / priorTotal; });
  result.actuarial_breakdown.underwriting_tier = "TIER_2_CONDITIONAL";
  result.hitl_status = { escalated: false, trigger_code: "NONE", trigger_reason: null, recommended_underwriter_action: "Demo loading accepted. Conditional bind requires permit review within 60 days." };
  return result;
}

export function actionTotals(base: ParcelScoreResponse, ids: string[]) {
  const actions = base.prescriptive_mitigations.filter(a => ids.includes(a.action_id));
  const totals = actions.filter(action => !action.currently_applied).reduce((total, a) => ({
    net: total.net + a.net_capex_usd, gross: total.gross + a.gross_capex_usd,
    grants: total.grants + a.grant_subsidy_usd, savings: 0,
  }), { net: 0, gross: 0, grants: 0, savings: 0 });
  if (!actions.length) return totals;
  const summary = selectedSummary(base, actions.map(action => action.action_id));
  totals.net = summary.net_capex_usd;
  totals.gross = totals.net + totals.grants;
  totals.savings = base.actuarial_breakdown.annual_discounted_premium_usd - summary.annual_discounted_premium_usd;
  return totals;
}
