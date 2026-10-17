import fixtures from "../../../contracts/golden_scenarios.json";
import simulations from "../../../contracts/golden_simulations.json";
import type { GoldenScenarios, GoldenScenarioKey } from "@/types/resiliscore";
import { parseParcel, parseGoldenSimulations } from "@/lib/contract";

// Sole fixture entry point. New golden parcels are picked up when contracts merge.
export const goldenScenarios: GoldenScenarios = Object.fromEntries(
  Object.entries(fixtures).map(([id, payload]) => [id, parseParcel(payload)]),
);
export const scenarios: { id: GoldenScenarioKey; title: string; location: string; address: string; summary: string }[] = [
  { id: "SCENARIO_1_LA_FLOOD", title: "Coastal flood", location: "Jefferson Parish, LA", address: "412 Bayou Rd", summary: "Verified freeboard" },
  { id: "SCENARIO_2_CA_WUI", title: "Wildfire remediation", location: "Altadena, CA", address: "1840 Canyon Crest Dr", summary: "Mitigation plan" },
  { id: "SCENARIO_3_ESCONDIDO_HITL", title: "Verification guardrail", location: "Escondido, CA", address: "742 Dixon Trail", summary: "Human review workflow" },
  { id: "NYC_RED_HOOK", title: "NYC Red Hook", location: "Brooklyn, NY", address: "5 Luquer St", summary: "NYC lot & flood evidence" },
  { id: "NYC_HOLLIS", title: "NYC Hollis", location: "Queens, NY", address: "81-52 192 St", summary: "NYC lot & flood evidence" },
  { id: "NYC_ROCKAWAY", title: "NYC Rockaway", location: "Queens, NY", address: "74-02 Beach Channel Dr", summary: "NYC lot & flood evidence" },
];

export function findScenario(id: GoldenScenarioKey) {
  const parcel = goldenScenarios[id];
  return parcel ? structuredClone(parcel) : null;
}

export function getScenario(id: GoldenScenarioKey) {
  const parcel = findScenario(id);
  if (!parcel) throw new Error(`Golden scenario ${id} is not available yet`);
  return parcel;
}

const goldenSimulations = parseGoldenSimulations(simulations);

export function getGoldenSimulation(id: string, actionIds: string[]) {
  return goldenSimulations[id]?.[[...new Set(actionIds)].sort().join("+")];
}
