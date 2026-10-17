import type { ParcelScoreResponse } from "@/types/resiliscore";
import { parseParcel } from "./contract";

export async function requestParcel(path: string, body: unknown, signal?: AbortSignal): Promise<ParcelScoreResponse> {
  const base = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
  const response = await fetch(`${base.replace(/\/$/, "")}${path}`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(4500)]) : AbortSignal.timeout(4500),
  });
  if (!response.ok) throw new Error(`API returned ${response.status}`);
  const data: unknown = await response.json();
  return parseParcel(data);
}
