import fixtures from "../../../contracts/golden_scenarios.json";
import type { GoldenScenarios, GoldenScenarioKey } from "@/types/resiliscore";
import { parseParcel } from "@/lib/contract";
import { goldenSimulations } from "./goldenSimulations";

// This is the sole fixture import. Never mutate the shared payloads.
export const goldenScenarios = {
  SCENARIO_1_LA_FLOOD: parseParcel(fixtures.SCENARIO_1_LA_FLOOD),
  SCENARIO_2_CA_WUI: parseParcel(fixtures.SCENARIO_2_CA_WUI),
  SCENARIO_3_ESCONDIDO_HITL: parseParcel(fixtures.SCENARIO_3_ESCONDIDO_HITL),
  SCENARIO_3_ESCONDIDO_HITL__UNPERMITTED: parseParcel(fixtures.SCENARIO_3_ESCONDIDO_HITL__UNPERMITTED),
} satisfies GoldenScenarios;
export const scenarios: { id: GoldenScenarioKey; title: string; location: string; summary: string }[] = [
  { id: "SCENARIO_1_LA_FLOOD", title: "Coastal flood", location: "Jefferson Parish, LA", summary: `${goldenScenarios.SCENARIO_1_LA_FLOOD.actuarial_breakdown.baseline_macro_score} → ${goldenScenarios.SCENARIO_1_LA_FLOOD.actuarial_breakdown.resili_score} · Verified freeboard` },
  { id: "SCENARIO_2_CA_WUI", title: "Wildfire remediation", location: "Altadena, CA", summary: `${goldenScenarios.SCENARIO_2_CA_WUI.actuarial_breakdown.resili_score} → ${goldenSimulations.SCENARIO_2_CA_WUI["CA_EMBER_VENTS_EAVES+CA_IBHS_WPH_CLASS_A_ROOF+CA_ZONE0_1_CLEARANCE"].resili_score} · Mitigation plan` },
  { id: "SCENARIO_3_ESCONDIDO_HITL", title: "Verification guardrail", location: "Escondido, CA", summary: `${goldenScenarios.SCENARIO_3_ESCONDIDO_HITL.actuarial_breakdown.resili_score} · Human review workflow` },
];

export function getScenario(id: GoldenScenarioKey) {
  return structuredClone(goldenScenarios[id]);
}
