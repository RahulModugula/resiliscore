import assert from "node:assert/strict";
import test from "node:test";
import { unprojectMeters } from "../src/lib/manhattan/geo";
import { parkGeometry } from "../src/lib/manhattan/sceneGeometry";
import type { Park, TerrainGrid } from "../src/lib/manhattan/types";

const southwest = unprojectMeters([0, 0]);
const northeast = unprojectMeters([100, 100]);
const hill: TerrainGrid = { bounds: [...southwest, ...northeast], width: 3, height: 3, elevationsM: [0, 0, 0, 0, 20, 0, 0, 0, 0], source: "regression fixture" };
const park: Park = { id: "hill-park", name: "Hill park", geometry: { type: "Polygon", coordinates: [[southwest, unprojectMeters([100, 0]), northeast, unprojectMeters([0, 100]), southwest]] } };

test("park surfaces preserve a supplied interior hill even when all boundary elevations are zero", () => {
  const mesh = parkGeometry([park], hill);
  assert.ok((mesh.boundingBox?.max.y ?? 0) >= 20, `interior hill disappeared: maximum rendered height ${mesh.boundingBox?.max.y}`);
  mesh.dispose();
});
