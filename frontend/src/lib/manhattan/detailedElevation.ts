import { loadMapAsset } from "./data";
import { projectLngLat } from "./geo";
import type { Bounds, TerrainGrid } from "./types";

export const ELEVATION_SERVICE = "https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer";
const cache = new Map<string, TerrainGrid>();
const MAX_SIDE = 512;

/** Native-source detail, bounded to 512² samples for large campuses and tax blocks. */
export function elevationRequest(bounds: Bounds, sourceIds: number[]) {
  const [west, south] = projectLngLat([bounds[0], bounds[1]]), [east, north] = projectLngLat([bounds[2], bounds[3]]);
  const spacing = Math.max(1, (east - west) / (MAX_SIDE - 2), (north - south) / (MAX_SIDE - 2));
  const width = Math.min(MAX_SIDE, Math.ceil((east - west) / spacing) + 2), height = Math.min(MAX_SIDE, Math.ceil((north - south) / spacing) + 2);
  if (width < 2 || height < 2 || ![...bounds, spacing].every(Number.isFinite) || east <= west || north <= south) throw new Error("Invalid block elevation extent");
  // A pixel halo ensures every context boundary is within the decoded sample centres.
  const dx = (bounds[2] - bounds[0]) / (width - 2), dy = (bounds[3] - bounds[1]) / (height - 2);
  const extent = [bounds[0] - dx / 2, bounds[1] - dy / 2, bounds[2] + dx / 2, bounds[3] + dy / 2];
  const params = new URLSearchParams({ f: "json", bbox: extent.join(","), bboxSR: "4326", imageSR: "4326", size: `${width},${height}`, format: "tiff", pixelType: "F32", renderingRule: JSON.stringify({ rasterFunction: "None" }), mosaicRule: JSON.stringify({ mosaicMethod: "esriMosaicLockRaster", lockRasterIds: sourceIds, mosaicOperation: "MT_FIRST" }), interpolation: "RSP_NearestNeighbor", adjustAspectRatio: "false" });
  return { url: `${ELEVATION_SERVICE}/exportImage?${params}`, spacing };
}

/** Decode the actual affine transform; never treat pixel edges as sample centres. */
export async function decodeElevation(buffer: ArrayBuffer): Promise<TerrainGrid> {
  const { fromArrayBuffer } = await import("geotiff");
  const tiff = await fromArrayBuffer(buffer), image = await tiff.getImage();
  const keys = image.getGeoKeys(), width = image.getWidth(), height = image.getHeight();
  const [west, north] = image.getOrigin(), [dx, dy] = image.getResolution();
  if (keys?.GeographicTypeGeoKey !== 4326 || keys.GTRasterTypeGeoKey !== 1 || image.fileDirectory.hasTag("ModelTransformation") || image.getSamplesPerPixel() !== 1 || width < 2 || height < 2 || width > MAX_SIDE || height > MAX_SIDE || dx <= 0 || dy >= 0 || ![west, north, dx, dy].every(Number.isFinite)) throw new Error("USGS elevation raster has an unsupported grid");
  const values = await image.readRasters({ interleave: true }), noData = image.getGDALNoData();
  if (!(values instanceof Float32Array)) throw new Error("USGS elevation raster is not Float32 ground data");
  const elevationsM: (number | null)[] = new Array(width * height);
  for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
    const value = values[(height - 1 - y) * width + x];
    elevationsM[y * width + x] = !Number.isFinite(value) || value === noData || Math.abs(value) > 100000 ? null : value;
  }
  if (!elevationsM.some(value => value !== null)) throw new Error("USGS elevation has no supported samples for this block");
  const bounds: Bounds = [west + dx / 2, north + dy * (height - .5), west + dx * (width - .5), north + dy / 2];
  const [ax, ay] = projectLngLat([bounds[0], bounds[1]]), [bx, by] = projectLngLat([bounds[2], bounds[3]]);
  return { bounds, width, height, elevationsM, source: "USGS 3DEP one-metre bare-earth source tiles; nearest-neighbor samples; metres NAVD88", raster: { dataset: "USGS_3DEP_1M", horizontalCrs: "EPSG:4326", verticalDatum: "NAVD88", elevationUnit: "metre", sourceResolutionM: 1, nominalSpacingM: Math.max((bx - ax) / (width - 1), (by - ay) / (height - 1)), cellSizeDegrees: [dx, -dy], extent: [west, north + height * dy, west + width * dx, north], sampleLocation: "pixel-center", rowOrder: "south-to-north", resampling: "nearest-neighbor", quantizationM: 0 } };
}

export async function loadDetailedElevation(bounds: Bounds, signal?: AbortSignal): Promise<TerrainGrid> {
  signal?.throwIfAborted();
  const key = bounds.join(",");
  if (cache.has(key)) return cache.get(key)!;
  const controller = new AbortController(), abort = () => controller.abort();
  signal?.addEventListener("abort", abort, { once: true });
  const timer = setTimeout(abort, 45000);
  try {
    const provenance = await loadMapAsset<{ nativeSources: { OBJECTID: number; VerticalDatum: string }[] }>("/manhattan/dem-provenance.json", controller.signal, value => {
      if (!value || typeof value !== "object" || !("nativeSources" in value) || !Array.isArray(value.nativeSources)) return false;
      return value.nativeSources.length > 0 && value.nativeSources.every(source => Number.isInteger(source.OBJECTID) && source.VerticalDatum === "North American Vertical Datum of 1988 (NAVD 88)");
    });
    const { url } = elevationRequest(bounds, provenance.nativeSources.map(source => source.OBJECTID));
    const options: RequestInit = { signal: controller.signal, credentials: "omit", referrerPolicy: "no-referrer" };
    const response = await fetch(url, options);
    if (!response.ok) throw new Error("USGS detail request failed");
    const result = await response.json();
    const rasterUrl = new URL(result.href);
    if (rasterUrl.origin !== "https://elevation.nationalmap.gov" || !rasterUrl.pathname.startsWith("/arcgis/rest/directories/") || !rasterUrl.pathname.endsWith(".tif")) throw new Error("USGS did not return an elevation raster");
    const raster = await fetch(rasterUrl, options);
    if (!raster.ok) throw new Error("USGS raster download failed");
    const terrain = await decodeElevation(await raster.arrayBuffer());
    controller.signal.throwIfAborted();
    const tolerance = 1e-8;
    if (terrain.bounds[0] > bounds[0] + tolerance || terrain.bounds[1] > bounds[1] + tolerance || terrain.bounds[2] < bounds[2] - tolerance || terrain.bounds[3] < bounds[3] - tolerance) throw new Error("USGS raster does not cover the selected block");
    if (cache.size >= 4) cache.delete(cache.keys().next().value!);
    cache.set(key, terrain);
    return terrain;
  } finally { clearTimeout(timer); signal?.removeEventListener("abort", abort); }
}
