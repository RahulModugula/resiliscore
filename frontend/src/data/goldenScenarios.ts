import fixtures from "../../../contracts/golden_scenarios.json";
import type { GoldenScenarios, GoldenScenarioKey } from "@/types/resiliscore";
import { parseParcel } from "@/lib/contract";

// This is the sole fixture import. Never mutate the shared payloads.
export const goldenScenarios = {
  SCENARIO_1_LA_FLOOD: parseParcel(fixtures.SCENARIO_1_LA_FLOOD),
  SCENARIO_2_CA_WUI: parseParcel(fixtures.SCENARIO_2_CA_WUI),
  SCENARIO_3_ESCONDIDO_HITL: parseParcel(fixtures.SCENARIO_3_ESCONDIDO_HITL),
  SCENARIO_3_ESCONDIDO_HITL__UNPERMITTED: parseParcel(fixtures.SCENARIO_3_ESCONDIDO_HITL__UNPERMITTED),
} satisfies GoldenScenarios;
export const scenarios: { id: GoldenScenarioKey; title: string; location: string; summary: string }[] = [
  { id: "SCENARIO_1_LA_FLOOD", title: "Coastal flood", location: "Jefferson Parish, LA", summary: "430 → 765 · Verified freeboard" },
  { id: "SCENARIO_2_CA_WUI", title: "Wildfire remediation", location: "Altadena, CA", summary: "385 → 630 · Mitigation plan" },
  { id: "SCENARIO_3_ESCONDIDO_HITL", title: "Verification guardrail", location: "Escondido, CA", summary: "815 · Human review workflow" },
];

export function getScenario(id: GoldenScenarioKey) {
  return structuredClone(goldenScenarios[id]);
}
