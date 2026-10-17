import Ajv from "ajv";
import addFormats from "ajv-formats";
import schema from "../../../contracts/parcel_score_schema.json";
import type { ParcelScoreResponse } from "@/types/resiliscore";

const ajv = new Ajv({ allErrors: true, strict: false });
addFormats(ajv);
const validate = ajv.compile<ParcelScoreResponse>(schema);

export async function requestParcel(path: string, body: unknown, signal?: AbortSignal): Promise<ParcelScoreResponse> {
  const base = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
  const response = await fetch(`${base.replace(/\/$/, "")}${path}`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(4500)]) : AbortSignal.timeout(4500),
  });
  if (!response.ok) throw new Error(`API returned ${response.status}`);
  const data: unknown = await response.json();
  if (!validate(data)) throw new Error("API response does not match the parcel contract");
  return data;
}
