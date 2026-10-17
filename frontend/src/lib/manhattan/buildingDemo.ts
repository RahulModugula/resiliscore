import cache from "../../data/manhattan/building-demo.json";
import screening from "../../data/manhattan/screening.json";
import { parseParcel } from "../contract";
import type { ParcelScoreResponse } from "../../types/resiliscore";

export interface BuildingDemoState {
  roof: boolean;
  phase: "planning" | "captured" | "reviewed";
}
export type BuildingDemoEvent = { type: "roof"; selected: boolean } | { type: "capture" } | { type: "approve" } | { type: "reset" };
export const initialBuildingDemo: BuildingDemoState = { roof: false, phase: "planning" };

/** Changing an assumed retrofit invalidates capture/review and closes its receipt. */
export function buildingDemoReducer(state: BuildingDemoState, event: BuildingDemoEvent): BuildingDemoState {
  switch (event.type) {
    case "roof": return { roof: event.selected, phase: "planning" };
    case "capture": return state.phase === "planning" ? { ...state, phase: "captured" } : state;
    case "approve": return state.phase === "captured" ? { ...state, phase: "reviewed" } : state;
    case "reset": return { ...initialBuildingDemo };
  }
}

export function projectBuildingDemo(base: ParcelScoreResponse, state: BuildingDemoState): ParcelScoreResponse {
  if (base.parcel_identity.state !== "NY" || base.parcel_identity.county_fips !== "36061") throw new Error("This demo requires a selected Manhattan building");
  const era = base.parcel_identity.year_built < cache.yearCutoff ? "pre2002" : "post2002";
  const key = `${Number(state.roof)}:${Number(state.phase === "reviewed")}`;
  const projections: Record<string, unknown> = cache.projections[era];
  const output = projections[key];
  if (!output || typeof output !== "object") throw new Error("This demo combination is unavailable");
  return parseParcel({
    ...structuredClone(screening.screens[era]), ...structuredClone(output),
    request_id: base.request_id,
    // The real building stays attached. The scenario valuation is explicitly assumed.
    parcel_identity: { ...structuredClone(base.parcel_identity), rcv_usd: cache.replacementValueUsd },
    indicative_only: true, uncertainty: null, factor_contributions: [],
    input_provenance: [
      ...structuredClone(screening.screens[era].input_provenance),
      { field: "building_demo", value_source: "DEFAULT", source_name: cache.method, vintage: null },
      { field: "cv_confidence", value_source: "DEFAULT", source_name: "Hypothetical demo review; no actual capture or verification", vintage: null },
    ],
  });
}

export function canCreateBuildingDemoReceipt(state: BuildingDemoState, projected: ParcelScoreResponse) {
  return state.phase === "reviewed" && !projected.hitl_status.escalated && ["TIER_1_AUTO_BIND", "TIER_2_CONDITIONAL"].includes(projected.actuarial_breakdown.underwriting_tier);
}

export function buildingDemoReceipt(buildingId: string, base: ParcelScoreResponse, state: BuildingDemoState) {
  const projected = projectBuildingDemo(base, state);
  if (!canCreateBuildingDemoReceipt(state, projected)) throw new Error("Complete the simulated capture and review before creating a demo receipt");
  return {
    demo: true, no_policy_issued: true,
    status: projected.actuarial_breakdown.underwriting_tier === "TIER_2_CONDITIONAL" ? "DEMO_CONDITIONAL" : "DEMO_AUTO_BIND",
    building_id: buildingId, address: base.parcel_identity.address,
    centroid: structuredClone(base.parcel_identity.centroid),
    footprint: structuredClone(base.parcel_identity.geometries),
    source_assessment_request_id: base.request_id,
    verification: "SIMULATED_REVIEW_ONLY",
    action_plan: state.roof ? ["HAIL_CLASS4_ROOF"] : [],
    assumptions: cache.method, assumed_replacement_value_usd: cache.replacementValueUsd,
    engine_sha256: cache.engineSha256,
    scenario_score: projected.actuarial_breakdown.resili_score,
    modeled_annual_loss_usd: projected.actuarial_breakdown.expected_annual_loss_usd,
    modeled_annual_premium_usd: projected.premium_build?.indicated_premium_usd ?? null,
    filed_quote: null, policy_number: null,
  };
}
