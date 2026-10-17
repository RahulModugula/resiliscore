/** All geographic coordinates use WGS84 longitude, latitude. All heights are metres. */
export type LngLat = [number, number];
export type Bounds = [west: number, south: number, east: number, north: number];
export type PolygonGeometry = { type: "Polygon"; coordinates: LngLat[][] };
export type MultiPolygonGeometry = { type: "MultiPolygon"; coordinates: LngLat[][][] };
export type Geometry = PolygonGeometry | MultiPolygonGeometry;

export interface Neighborhood {
  id: string;
  name: string;
  geometry: Geometry;
  center: LngLat;
  bounds: Bounds;
  /** NYC NTA2020 classification code, preserved verbatim from the source. */
  type: string;
}

export interface Building {
  /** NYC OTI DOITT_ID, with part suffix when a footprint has multiple polygons. */
  id: string;
  bin: string | null;
  bbl: string | null;
  address: string | null;
  name: string | null;
  center: LngLat;
  /** First ring is exterior. Subsequent rings are holes. */
  footprint: LngLat[][];
  heightM: number | null;
  groundElevationM: number | null;
  neighborhoodId: string;
  yearBuilt: number | null;
  featureCode: string;
}

export interface Park { id: string; name: string; geometry: Geometry }

export interface TerrainGrid {
  /** Coordinates of the southwest and northeast sample centres, not pixel edges. */
  bounds: Bounds;
  width: number;
  height: number;
  /** Row-major, starting at southwest; null means no supported ground observation. */
  elevationsM: (number | null)[];
  source: string;
  raster?: {
    dataset: "USGS_3DEP_1M";
    horizontalCrs: "EPSG:4326";
    verticalDatum: "NAVD88";
    elevationUnit: "metre";
    sourceResolutionM: number;
    nominalSpacingM: number;
    cellSizeDegrees: LngLat;
    extent: Bounds;
    sampleLocation: "pixel-center";
    rowOrder: "south-to-north";
    resampling: "nearest-neighbor";
    quantizationM: number;
  };
}

export interface StormDrain { id: string; position: LngLat; depthM: number | null }
export interface SewerLine { id: string; coordinates: LngLat[]; depthM: number | null; type: string | null }
export interface Infrastructure {
  stormDrains: StormDrain[];
  sewerLines: SewerLine[];
  sewerAvailability: "unavailable" | "partial" | "available";
  sewerStatus: string;
}

export interface NeighborhoodDetail {
  neighborhoodId: string;
  buildings: Building[];
  parks: Park[];
  terrain: TerrainGrid;
  infrastructure?: Infrastructure;
}

export interface ManhattanOverview { buildings: Building[]; parks: Park[]; terrain: TerrainGrid; infrastructure?: Infrastructure }
export interface ManhattanSource { name: string; url: string; retrievedAt: string; license: string }
export interface ManhattanManifest {
  version: number;
  neighborhoodsUrl: string;
  overviewUrl: string;
  /** Lazy full-resolution DEM for block context across neighborhood boundaries. */
  terrainUrl?: string;
  details: Record<string, string>;
  counts: { neighborhoods: number; buildings: number; parks: number };
  sources: ManhattanSource[];
  limitations: string[];
}
