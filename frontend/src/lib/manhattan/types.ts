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
  /** NYC NTA2020 type: 0 residential, 1 park, 2 airport, 3 cemetery, 4 other. */
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
  bounds: Bounds;
  width: number;
  height: number;
  /** Row-major, starting at southwest; null means no supported ground observation. */
  elevationsM: (number | null)[];
  source: string;
}

export interface NeighborhoodDetail {
  neighborhoodId: string;
  buildings: Building[];
  parks: Park[];
  terrain: TerrainGrid;
}

export interface ManhattanOverview { buildings: Building[]; parks: Park[]; terrain: TerrainGrid }
export interface ManhattanSource { name: string; url: string; retrievedAt: string; license: string }
export interface ManhattanManifest {
  version: number;
  neighborhoodsUrl: string;
  overviewUrl: string;
  details: Record<string, string>;
  counts: { neighborhoods: number; buildings: number; parks: number };
  sources: ManhattanSource[];
  limitations: string[];
}
