import type { ParcelScoreResponse } from "@/types/resiliscore";
import { parseParcel } from "./contract";

export async function requestParcel(path: string, body: unknown, signal?: AbortSignal): Promise<ParcelScoreResponse> {
  const base = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
  // A cold address lookup includes geocoding and hazard ingestion before scoring.
  const addressLookup = path === "/v1/parcel/score" && typeof body === "object" && body !== null && "address" in body && typeof body.address === "string";
  const deadline = AbortSignal.timeout(addressLookup ? 15_000 : 4_500);
  const response = await fetch(`${base.replace(/\/$/, "")}${path}`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    signal: signal ? AbortSignal.any([signal, deadline]) : deadline,
  });
  if (!response.ok) throw new Error(`API returned ${response.status}`);
  const data: unknown = await response.json();
  return parseParcel(data);
}
