import { parseParcel } from "../contract";
import screening from "../../data/manhattan/screening.json";
import type { ParcelScoreResponse, InputProvenance } from "../../types/resiliscore";
import type { Building } from "./types";

export interface ManhattanAssessment {
  parcel: ParcelScoreResponse;
  source: "live" | "local";
  notice: string;
  property: Pick<Building, "id" | "neighborhoodId" | "bin" | "bbl" | "address" | "name">;
}
const LOCAL_NOTICE = "Offline model screening. The canonical risk engine was run with national-default hazards, a nonlocal FEMA NRI reference tract and an assumed $350,000 replacement value. This is not measured Manhattan hazard evidence. Map geometry identifies your building; missing inputs remain unknown. No quote, verified credit or binding authority. Connect the backend and select this property again for a live assessment.";
const STORAGE_PREFIX = "resiliscore:manhattan:assessment:v1:";
const MAX_AGE_MS = 6 * 60 * 60 * 1000;
const NYC_SOURCE = "NYC OTI Building Footprints cached map data; not a verification channel";
export function propertyLabel(building: Pick<Building, "address" | "name" | "bin" | "id">): string {
  return building.address || building.name || (building.bin ? `BIN ${building.bin}` : `Building ${building.id}`);
}
/** A contract-required numeric id, explicitly synthetic. Never a NYC BBL or assessor APN. */
function syntheticId(id: string): string {
  let hash = 2166136261;
  for (const char of id) hash = Math.imul(hash ^ char.charCodeAt(0), 16777619) >>> 0;
  return `0000${String(hash).padStart(10, "0")}`;
}
/** Cached canonical-engine outputs vary only by construction era under the documented defaults.
 * No geographic risk ranking can be inferred between buildings using this cache.
 * Map elevation is deliberately not treated as certified USGS elevation or freeboard.
 */
function localScreening(building: Building): ParcelScoreResponse {
  const year = building.yearBuilt ?? screening.defaultYearBuilt;
  const parcel = structuredClone(parseParcel(screening.screens[year < screening.yearCutoff ? "pre2002" : "post2002"]));
  parcel.request_id = crypto.randomUUID();
  parcel.parcel_identity = {
    ...parcel.parcel_identity,
    apn_uid: syntheticId(building.id), address: `${propertyLabel(building)}, Manhattan, NY`,
    centroid: building.center, year_built: year,
    geometries: { type: "FeatureCollection", features: [{ type: "Feature", geometry: { type: "Polygon", coordinates: building.footprint }, properties: { kind: "building_footprint", label: "NYC mapped building footprint; not a surveyed parcel boundary" } }] },
  };
  const mapProvenance: InputProvenance[] = [
    { field: "footprint", value_source: "LIVE", source_name: NYC_SOURCE, vintage: null },
    { field: "centroid", value_source: "LIVE", source_name: NYC_SOURCE, vintage: null },
    { field: "apn_uid", value_source: "DEFAULT", source_name: "Synthetic local identifier; not assessor APN or BBL", vintage: null },
    { field: "year_built", value_source: building.yearBuilt === null ? "DEFAULT" : "LIVE", source_name: building.yearBuilt === null ? "Backend national default year built: 1990" : NYC_SOURCE, vintage: null },
    { field: "map_ground_elevation_m", value_source: building.groundElevationM === null ? "UNAVAILABLE" : "LIVE", source_name: `${NYC_SOURCE}; vertical datum not confirmed for flood comparison; excluded from risk model`, vintage: null },
    { field: "offline_screening_model", value_source: "DEFAULT", source_name: `Canonical backend optimizer.simulate snapshot ${screening.engineSha256}; no live geographic hazard lookup`, vintage: null },
  ];
  parcel.input_provenance = [...(parcel.input_provenance ?? []).filter(row => row.field !== "year_built"), ...mapProvenance];
  return parcel;
}
/** Runs the actual parcel API. Network/validation errors leave a truthful building workspace. */
export async function assessManhattanProperty(building: Building, options: { signal?: AbortSignal; preferLive?: boolean } = {}): Promise<ManhattanAssessment> {
  options.signal?.throwIfAborted();
  const property = { id: building.id, neighborhoodId: building.neighborhoodId, bin: building.bin, bbl: building.bbl, address: building.address, name: building.name };
  if (options.preferLive !== false) {
    try {
      const base = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
      const timeout = AbortSignal.timeout(10_000);
      const response = await fetch(`${base.replace(/\/$/, "")}/v1/parcel/score`, {
        method: "POST", headers: { "Content-Type": "application/json" }, signal: options.signal ? AbortSignal.any([options.signal, timeout]) : timeout,
        body: JSON.stringify({ address: `${propertyLabel(building)}, Manhattan, NY`, lat: building.center[1], lng: building.center[0], county_fips: "36061", state: "NY", footprint: building.footprint[0], ...(building.yearBuilt === null ? {} : { year_built: building.yearBuilt }) }),
      });
      if (!response.ok) throw new Error(`API returned ${response.status}`);
      const parcel = parseParcel(await response.json());
      const p = parcel.parcel_identity;
      if (p.state !== "NY" || p.county_fips !== "36061" || Math.abs(p.centroid[0] - building.center[0]) > .0001 || Math.abs(p.centroid[1] - building.center[1]) > .0001) throw new Error("The API returned a different property");
      return { parcel, source: "live", property, notice: parcel.indicative_only ? "Live risk assessment for this building. Some model inputs remain default or unavailable. This result is indicative only, with no binding authority or verified credits." : "Live risk assessment for this building. Review the supplied evidence before underwriting. This workspace does not issue policies." };
    } catch (error) { if (options.signal?.aborted) throw error; }
  }
  options.signal?.throwIfAborted();
  return { parcel: localScreening(building), source: "local", property, notice: LOCAL_NOTICE };
}
export function saveManhattanAssessment(id: string, result: ManhattanAssessment): boolean {
  if (typeof window === "undefined" || result.property.id !== id) return false;
  try { window.sessionStorage.setItem(`${STORAGE_PREFIX}${id}`, JSON.stringify({ savedAt: Date.now(), result })); return true; } catch { return false; }
}
export function loadManhattanAssessment(id: string): ManhattanAssessment | null {
  if (typeof window === "undefined") return null;
  try {
    const raw: unknown = JSON.parse(window.sessionStorage.getItem(`${STORAGE_PREFIX}${id}`) ?? "null");
    if (!raw || typeof raw !== "object" || !("savedAt" in raw) || typeof raw.savedAt !== "number" || Date.now() - raw.savedAt > MAX_AGE_MS || raw.savedAt > Date.now() + 60_000 || !("result" in raw)) return null;
    const result = raw.result as Partial<ManhattanAssessment>;
    if (!result || (result.source !== "live" && result.source !== "local") || typeof result.notice !== "string" || result.property?.id !== id || typeof result.property.neighborhoodId !== "string") return null;
    if (![result.property.bin, result.property.bbl, result.property.address, result.property.name].every(value => value === null || typeof value === "string")) return null;
    const parcel = parseParcel(result.parcel);
    if (parcel.parcel_identity.state !== "NY" || parcel.parcel_identity.county_fips !== "36061") return null;
    return { ...result, parcel } as ManhattanAssessment;
  } catch { return null; }
}
