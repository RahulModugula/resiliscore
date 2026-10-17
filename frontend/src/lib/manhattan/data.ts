import type { ManhattanManifest, ManhattanOverview, Neighborhood, NeighborhoodDetail } from "./types";

const cache = new Map<string, unknown>();

/** Runtime geography comes from bundled assets, without map tokens or GIS requests. */
export async function loadMapAsset<T>(path: string, signal: AbortSignal | undefined, validate: (value: unknown) => boolean, invalidMessage = "Map data is incomplete or does not match the selection"): Promise<T> {
  if (!/^\/manhattan\/[\w./-]+\.json$/.test(path) || path.includes("..")) throw new Error("Invalid map asset path");
  signal?.throwIfAborted();
  if (cache.has(path) && validate(cache.get(path))) return cache.get(path) as T;
  const response = await fetch(path, { signal, credentials: "omit" });
  if (!response.ok) throw new Error(`Map data could not be loaded (${response.status})`);
  const data: unknown = await response.json();
  signal?.throwIfAborted();
  if (!validate(data)) throw new Error(invalidMessage);
  cache.set(path, data);
  return data as T;
}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export async function loadManhattan(signal?: AbortSignal) {
  const manifest = await loadMapAsset<ManhattanManifest>("/manhattan/manifest.json", signal, value => record(value) && record(value.details) && Array.isArray(value.sources) && typeof value.neighborhoodsUrl === "string" && typeof value.overviewUrl === "string");
  const [neighborhoods, overview] = await Promise.all([
    loadMapAsset<Neighborhood[]>(manifest.neighborhoodsUrl, signal, value => Array.isArray(value) && value.every(item => record(item) && typeof item.id === "string" && typeof item.name === "string" && Array.isArray(item.bounds) && record(item.geometry))),
    loadMapAsset<ManhattanOverview>(manifest.overviewUrl, signal, value => record(value) && Array.isArray(value.buildings) && Array.isArray(value.parks) && record(value.terrain)),
  ]);
  return { manifest, neighborhoods, overview };
}

export async function loadNeighborhood(manifest: ManhattanManifest, id: string, signal?: AbortSignal) {
  const path = manifest.details[id];
  if (!path) throw new Error("This neighborhood has no cached detail");
  const detail = await loadMapAsset<NeighborhoodDetail>(path, signal, value => record(value) && value.neighborhoodId === id && Array.isArray(value.buildings) && Array.isArray(value.parks) && record(value.terrain));
  return detail;
}
