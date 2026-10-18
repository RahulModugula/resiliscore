import { loadMapAsset } from "./data";
import { decodeElevation } from "./detailedElevation";
import type { Bounds, TerrainGrid } from "./types";

const MANIFEST = "/manhattan/prototypes/nyc2021-murray-hill.json";
const RASTER = "/manhattan/prototypes/nyc2021-murray-hill.tif";
let cached: TerrainGrid | null = null;

interface PrototypeManifest {
  version: 1;
  dataset: "NYC_2021_PROTOTYPE";
  buildingId: "1112075";
  rasterUrl: typeof RASTER;
  sha256: string;
  width: number;
  height: number;
  bounds: Bounds;
  source: string;
  horizontalCrs: "EPSG:4326";
  verticalDatum: "NAVD88";
  geoid: "GEOID18";
  elevationUnit: "metre";
  interpolation: { method: "linear-TIN"; maxTriangleEdgeM: number; maxCircumradiusM: number; maxNearestPointM: number };
}
function record(value: unknown): value is Record<string, unknown> { return !!value && typeof value === "object" && !Array.isArray(value); }
function validManifest(value: unknown): value is PrototypeManifest {
  if (!record(value) || !record(value.interpolation)) return false;
  return value.version === 1 && value.dataset === "NYC_2021_PROTOTYPE" && value.buildingId === "1112075"
    && value.rasterUrl === RASTER && typeof value.sha256 === "string" && /^[a-f0-9]{64}$/.test(value.sha256)
    && typeof value.width === "number" && Number.isInteger(value.width) && value.width >= 2 && value.width <= 512
    && typeof value.height === "number" && Number.isInteger(value.height) && value.height >= 2 && value.height <= 512
    && Array.isArray(value.bounds) && value.bounds.length === 4 && value.bounds.every(Number.isFinite)
    && value.bounds[2] > value.bounds[0] && value.bounds[3] > value.bounds[1] && typeof value.source === "string"
    && value.horizontalCrs === "EPSG:4326" && value.verticalDatum === "NAVD88" && value.geoid === "GEOID18" && value.elevationUnit === "metre"
    && value.interpolation.method === "linear-TIN" && value.interpolation.maxTriangleEdgeM === 10
    && value.interpolation.maxCircumradiusM === 5 && value.interpolation.maxNearestPointM === 3;
}
function covers(outer: Bounds, inner: Bounds) {
  return inner.every(Number.isFinite) && inner[0] < inner[2] && inner[1] < inner[3]
    && outer[0] <= inner[0] + 1e-8 && outer[1] <= inner[1] + 1e-8
    && outer[2] >= inner[2] - 1e-8 && outer[3] >= inner[3] - 1e-8;
}

/** This experimental asset covers one evaluated building context only. */
export function hasPrototypeTerrain(buildingId: string) { return buildingId === "1112075"; }

export async function decodePrototypeElevation(buffer: ArrayBuffer, manifest: unknown): Promise<TerrainGrid> {
  if (!validManifest(manifest)) throw new Error("2021 terrain metadata is unsupported");
  const hash = await crypto.subtle.digest("SHA-256", buffer);
  const hex = Array.from(new Uint8Array(hash), value => value.toString(16).padStart(2, "0")).join("");
  if (hex !== manifest.sha256) throw new Error("2021 terrain checksum mismatch");
  const terrain = await decodeElevation(buffer);
  if (terrain.width !== manifest.width || terrain.height !== manifest.height || terrain.bounds.some((v, i) => Math.abs(v - manifest.bounds[i]) > 1e-10)) throw new Error("2021 terrain grid does not match its metadata");
  return { ...terrain, source: manifest.source, raster: { ...terrain.raster!, dataset: manifest.dataset,
    sourceResolutionM: null, resampling: "linear-TIN" } };
}

/** Local, bounded, cached terrain; never download LAS data during an interaction. */
export async function loadPrototypeElevation(bounds: Bounds, signal?: AbortSignal): Promise<TerrainGrid> {
  signal?.throwIfAborted();
  if (cached) {
    if (!covers(cached.bounds, bounds)) throw new Error("2021 prototype does not cover this block");
    return cached;
  }
  const manifest = await loadMapAsset<PrototypeManifest>(MANIFEST, signal, validManifest, "2021 terrain metadata is unsupported");
  if (!covers(manifest.bounds, bounds)) throw new Error("2021 prototype does not cover this block");
  const response = await fetch(manifest.rasterUrl, { signal, credentials: "omit" });
  if (!response.ok) throw new Error("2021 terrain could not be loaded");
  const terrain = await decodePrototypeElevation(await response.arrayBuffer(), manifest);
  signal?.throwIfAborted();
  cached = terrain;
  return terrain;
}
