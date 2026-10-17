import Ajv from "ajv/dist/2020";
import addFormats from "ajv-formats";
import simulationSchema from "../../../contracts/golden_simulations_schema.json";
import schema from "../../../contracts/parcel_score_schema.json";
import type { ParcelScoreResponse } from "@/types/resiliscore";

const ajv = new Ajv({ allErrors: true, strict: false });
addFormats(ajv);
const validate = ajv.compile<ParcelScoreResponse>(schema);

export function parseParcel(data: unknown): ParcelScoreResponse {
  if (!validate(data)) throw new Error("API response does not match the parcel contract");
  return data;
}

export interface GoldenSimulation {
  resili_score: number;
  underwriting_tier: ParcelScoreResponse["actuarial_breakdown"]["underwriting_tier"];
  posterior_lcr: number;
  credibility_weight_z: number;
  expected_annual_loss_usd: number;
  statutory_discount_pct: number;
  annual_discounted_premium_usd: number;
  total_annual_savings_usd: number;
  net_capex_usd: number;
  trigger_code: ParcelScoreResponse["hitl_status"]["trigger_code"];
}
const validateSimulations = ajv.compile<Record<string, Record<string, GoldenSimulation>>>(simulationSchema);
export function parseGoldenSimulations(data: unknown) {
  if (!validateSimulations(data)) throw new Error("Golden simulations do not match the simulation contract");
  return data;
}
