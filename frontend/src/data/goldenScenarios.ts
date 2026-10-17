import fixtures from "../../../contracts/golden_scenarios.json";
import type { GoldenScenarios, GoldenScenarioKey } from "@/types/resiliscore";
import { simulateMitigations } from "@/lib/simulation";
import { parseParcel } from "@/lib/contract";

// This is the sole fixture import. Never mutate the shared payloads.
export const goldenScenarios = {
  SCENARIO_1_LA_FLOOD: parseParcel(fixtures.SCENARIO_1_LA_FLOOD),
  SCENARIO_2_CA_WUI: parseParcel(fixtures.SCENARIO_2_CA_WUI),
  SCENARIO_3_ESCONDIDO_HITL: parseParcel(fixtures.SCENARIO_3_ESCONDIDO_HITL),
  SCENARIO_3_ESCONDIDO_HITL__UNPERMITTED: parseParcel(fixtures.SCENARIO_3_ESCONDIDO_HITL__UNPERMITTED),
  NYC_RED_HOOK: parseParcel(fixtures.NYC_RED_HOOK),
  NYC_HOLLIS: parseParcel(fixtures.NYC_HOLLIS),
  NYC_ROCKAWAY: parseParcel(fixtures.NYC_ROCKAWAY),
} satisfies GoldenScenarios;
const floodScores = goldenScenarios.SCENARIO_1_LA_FLOOD.actuarial_breakdown;
const wildfire = goldenScenarios.SCENARIO_2_CA_WUI;
const plannedWildfire = simulateMitigations(wildfire, wildfire.prescriptive_mitigations.map(action => action.action_id));
const verifiedScore = goldenScenarios.SCENARIO_3_ESCONDIDO_HITL.actuarial_breakdown.resili_score;

export const scenarios: { id: GoldenScenarioKey; title: string; location: string; summary: string }[] = [
  { id: "SCENARIO_1_LA_FLOOD", title: "Coastal flood", location: "Jefferson Parish, LA", summary: `${floodScores.baseline_macro_score} → ${floodScores.resili_score} · Verified freeboard` },
  { id: "SCENARIO_2_CA_WUI", title: "Wildfire remediation", location: "Altadena, CA", summary: `${wildfire.actuarial_breakdown.resili_score} → ${plannedWildfire.actuarial_breakdown.resili_score} · Mitigation plan` },
  { id: "SCENARIO_3_ESCONDIDO_HITL", title: "Verification guardrail", location: "Escondido, CA", summary: `${verifiedScore} · Human review workflow` },
];

export function getScenario(id: GoldenScenarioKey) {
  return structuredClone(goldenScenarios[id]);
}
