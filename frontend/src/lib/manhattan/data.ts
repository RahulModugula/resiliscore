import type { ManhattanManifest, ManhattanOverview, Neighborhood, NeighborhoodDetail } from "./types";

const cache = new Map<string, unknown>();

/** Runtime geography comes from bundled assets, without map tokens or GIS requests. */
async function localJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  if (!/^\/manhattan\/[\w./-]+\.json$/.test(path) || path.includes("..")) throw new Error("Invalid map asset path");
  signal?.throwIfAborted();
  if (cache.has(path)) return cache.get(path) as T;
  const response = await fetch(path, { signal, credentials: "omit" });
  if (!response.ok) throw new Error(`Map data could not be loaded (${response.status})`);
  const data: unknown = await response.json();
  signal?.throwIfAborted();
  cache.set(path, data);
  return data as T;
}

export async function loadManhattan(signal?: AbortSignal) {
  const manifest = await localJson<ManhattanManifest>("/manhattan/manifest.json", signal);
  if (!manifest.details || !Array.isArray(manifest.sources)) throw new Error("Map manifest is incomplete");
  const [neighborhoods, overview] = await Promise.all([
    localJson<Neighborhood[]>(manifest.neighborhoodsUrl, signal),
    localJson<ManhattanOverview>(manifest.overviewUrl, signal),
  ]);
  if (!Array.isArray(neighborhoods) || !Array.isArray(overview.buildings)) throw new Error("Map data is incomplete");
  return { manifest, neighborhoods, overview };
}

export async function loadNeighborhood(manifest: ManhattanManifest, id: string, signal?: AbortSignal) {
  const path = manifest.details[id];
  if (!path) throw new Error("This neighborhood has no cached detail");
  const detail = await localJson<NeighborhoodDetail>(path, signal);
  if (detail.neighborhoodId !== id || !Array.isArray(detail.buildings)) throw new Error("Neighborhood data does not match the selection");
  return detail;
}
