import Ajv from "ajv/dist/2020";
import fixtures from "../../../contracts/golden_simulations.json";
import schema from "../../../contracts/golden_simulations_schema.json";
import type { GoldenScenarioKey, ParcelScoreResponse } from "@/types/resiliscore";

type Summary = Pick<ParcelScoreResponse["actuarial_breakdown"],
  "resili_score" | "underwriting_tier" | "posterior_lcr" | "credibility_weight_z" |
  "expected_annual_loss_usd" | "statutory_discount_pct" | "annual_discounted_premium_usd"
> & {
  total_annual_savings_usd: number;
  net_capex_usd: number;
  trigger_code: ParcelScoreResponse["hitl_status"]["trigger_code"];
};

const validate = new Ajv({ strict: false }).compile<Record<GoldenScenarioKey, Record<string, Summary>>>(schema);
const data: unknown = fixtures;
if (!validate(data)) throw new Error("Golden simulations do not match their shared contract");

export const goldenSimulations = data;
