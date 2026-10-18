import { loadMapAsset } from "./data";
import type { Bounds, LngLat } from "./types";

export interface TransportDeck {
  id: string;
  sourceId: string;
  status: string;
  streetIds: string[];
  bounds: Bounds;
  rings: [number, number, number][][]; // longitude, latitude, metres NAVD88
}
export interface TransportDeckBundle {
  version: 1;
  horizontalCrs: "EPSG:4326";
  verticalDatum: "NAVD88";
  elevationUnit: "metre";
  source: string;
  decks: TransportDeck[];
}
function record(value: unknown): value is Record<string, unknown> { return !!value && typeof value === "object"; }
function valid(value: unknown) {
  return record(value) && value.version === 1 && value.horizontalCrs === "EPSG:4326" && value.verticalDatum === "NAVD88" && value.elevationUnit === "metre"
    && typeof value.source === "string" && Array.isArray(value.decks) && value.decks.every(deck => record(deck)
      && typeof deck.id === "string" && typeof deck.sourceId === "string" && typeof deck.status === "string"
      && Array.isArray(deck.streetIds) && deck.streetIds.length>0 && deck.streetIds.every(id=>typeof id==="string")
      && Array.isArray(deck.bounds) && deck.bounds.length === 4 && deck.bounds.every(Number.isFinite)
      && deck.bounds[0]<deck.bounds[2] && deck.bounds[1]<deck.bounds[3]
      && Array.isArray(deck.rings) && deck.rings.length > 0 && deck.rings.every(ring => Array.isArray(ring) && ring.length >= 4
        && ring.every(point => Array.isArray(point) && point.length === 3 && point.every(Number.isFinite))
        && ring[0].every((coordinate:number,i:number)=>coordinate===ring.at(-1)[i])));
}
/** A bounded source bundle, not inferred decks or a citywide bridge inventory. */
export async function loadTransportDecks(bounds: Bounds, signal?: AbortSignal) {
  const bundle = await loadMapAsset<TransportDeckBundle>("/manhattan/context/transport-decks.json", signal, valid, "Transport structure data is malformed");
  return bundle.decks.filter(deck => deck.bounds[0] <= bounds[2] && deck.bounds[2] >= bounds[0] && deck.bounds[1] <= bounds[3] && deck.bounds[3] >= bounds[1]);
}
export function deckFootprint(deck: TransportDeck): LngLat[][] { return deck.rings.map(ring => ring.map(([x,y]) => [x,y])); }
