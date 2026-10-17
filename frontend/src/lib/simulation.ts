import type { ParcelScoreResponse, UnderwritingTier } from "@/types/resiliscore";

export function tierForScore(score: number): UnderwritingTier {
  return score >= 720 ? "TIER_1_AUTO_BIND" : score >= 580 ? "TIER_2_CONDITIONAL" : "TIER_3_DECLINE_ESCALATE";
}

// Local demo counterfactuals use the contract's action deltas, not a new score curve.
// Already verified actions are included in the baseline and cannot be double counted.
export function simulateMitigations(base: ParcelScoreResponse, actionIds: string[]): ParcelScoreResponse {
  const result = structuredClone(base);
  const actions = base.prescriptive_mitigations.filter(a => !a.currently_applied && actionIds.includes(a.action_id));
  if (actions.length === 0) return result;
  const a = result.actuarial_breakdown;
  const delta = actions.reduce((sum, item) => sum + item.lcr_delta_bps / 10000, 0);
  a.resili_score = Math.min(850, a.resili_score + actions.reduce((sum, item) => sum + item.score_delta_pts, 0));
  a.posterior_lcr = Math.max(0, a.posterior_lcr + delta);
  a.parcel_raw_lcr = Math.max(0, (a.posterior_lcr - (1 - a.credibility_weight_z) * a.tract_prior_lcr) / a.credibility_weight_z);
  a.expected_annual_loss_usd = a.posterior_lcr * result.parcel_identity.rcv_usd;
  // Preserve the supplied peril allocation while making its total agree with AAL.
  const priorTotal = a.peril_split.reduce((sum, item) => sum + item.peril_aal_usd, 0);
  if (priorTotal > 0) a.peril_split.forEach(item => { item.peril_aal_usd *= a.expected_annual_loss_usd / priorTotal; });
  a.annual_discounted_premium_usd = Math.max(0, a.annual_discounted_premium_usd - actions.reduce((sum, item) => sum + item.annual_premium_savings_usd, 0));
  a.statutory_discount_pct = 100 * (1 - a.annual_discounted_premium_usd / a.annual_base_premium_usd);
  a.underwriting_tier = tierForScore(a.resili_score);
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

export function actionTotals(base: ParcelScoreResponse, ids: string[]) {
  return base.prescriptive_mitigations.filter(a => !a.currently_applied && ids.includes(a.action_id)).reduce((total, a) => ({
    net: total.net + a.net_capex_usd, gross: total.gross + a.gross_capex_usd,
    grants: total.grants + a.grant_subsidy_usd, savings: total.savings + a.annual_premium_savings_usd,
  }), { net: 0, gross: 0, grants: 0, savings: 0 });
}
