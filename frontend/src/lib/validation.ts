import Ajv from "ajv/dist/2020";
import addFormats from "ajv-formats";
import schema from "../../../contracts/validation_report_schema.json";
import type { ValidationReport } from "@/types/validation";

const ajv = new Ajv({ allErrors: true, strict: false, useDefaults: true });
addFormats(ajv);
const validate = ajv.compile<ValidationReport>(schema);

export function parseValidationReport(data: unknown): ValidationReport {
  if (!validate(data)) throw new Error("Response does not match the model validation contract");
  // Pydantic default_factory arrays are optional in the JSON schema but have no
  // JSON Schema default for Ajv to apply. Normalize them at this boundary.
  return {
    ...data,
    benchmarks: data.benchmarks ?? [],
    wildfire: data.wildfire ? { ...data.wildfire, features: data.wildfire.features ?? [], fires: data.wildfire.fires ?? [] } : null,
    flood: data.flood ? {
      ...data.flood,
      severity_by_depth: data.flood.severity_by_depth ?? [],
      events: (data.flood.events ?? []).map(event => ({ ...event, states: event.states ?? [] })),
      ranking: data.flood.ranking ? { ...data.flood.ranking, deciles: data.flood.ranking.deciles ?? [] } : null,
    } : null,
    model_card: { ...data.model_card, perils: data.model_card.perils ?? [], sources: data.model_card.sources ?? [] },
  };
}

export async function requestValidationReport(signal: AbortSignal): Promise<ValidationReport> {
  const base = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
  const response = await fetch(`${base.replace(/\/$/, "")}/v1/model/validation`, {
    signal: AbortSignal.any([signal, AbortSignal.timeout(4500)]),
    cache: "no-store",
  });
  if (!response.ok) throw new Error(`API returned ${response.status}`);
  return parseValidationReport(await response.json());
}
