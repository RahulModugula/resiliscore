import { expect, test } from "@playwright/test";
import fs from "node:fs/promises";
import path from "node:path";
import fixtures from "../../../contracts/golden_scenarios.json";
import type { ParcelScoreResponse } from "../../src/types/resiliscore";

function indicativeParcel(): ParcelScoreResponse {
  const parcel: ParcelScoreResponse = structuredClone(fixtures.NYC_RED_HOOK);
  parcel.indicative_only = true;
  parcel.public_hazard_layer.usgs_lag_ft = null;
  parcel.public_hazard_layer.est_ffe_ft = null;
  parcel.public_hazard_layer.freeboard_delta_h_ft = null;
  parcel.nyc!.ground_elevation_ft = null;
  parcel.input_provenance = [
    { field: "usgs_lag_ft", value_source: "UNAVAILABLE", source_name: "Elevation source unavailable", vintage: null },
    { field: "cv_confidence", value_source: "UNAVAILABLE", source_name: "No aerial image supplied", vintage: null },
  ];
  return parcel;
}

for (const [device, width, height] of [["desktop", 1440, 1000], ["mobile", 390, 844]] as const) {
  test(`indicative evidence remains unknown on ${device}`, async ({ page }) => {
    await page.setViewportSize({ width, height });
    await page.emulateMedia({ reducedMotion: "reduce" });
    const parcel = indicativeParcel();
    await page.route("**/v1/parcel/score", route => route.fulfill({ json: parcel }));
    await page.goto("/assessment?demo=true");
    const search = page.getByRole("textbox", { name: "Search address or APN" });
    await search.fill(parcel.parcel_identity.address);
    await search.press("Enter");
    const score = page.locator(".score-panel");
    await expect(score.locator(".panel-heading").first().locator(".badge")).toHaveText("Indicative only");
    await expect(score.getByText("Verified parcel", { exact: true })).toHaveCount(0);
    for (const label of ["USGS 3DEP · Ground elevation", "Aerial computer vision"]) {
      const row = score.locator(".evidence-list li").filter({ hasText: label });
      await expect(row.locator("span").last()).toHaveText("Unknown");
      await expect(row.locator(".lucide-check")).toHaveCount(0);
    }
    await expect(page.getByText("0% confidence", { exact: true })).toHaveCount(0);
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.evaluate(() => { if (document.activeElement instanceof HTMLElement) document.activeElement.blur(); });
    const dir = path.resolve(".impeccable/review/handoff-evidence");
    await fs.mkdir(dir, { recursive: true });
    await page.screenshot({ path: path.join(dir, `${device}.png`), fullPage: true, animations: "disabled" });
  });
}

test("default provenance cannot become confirmed evidence through populated values", async ({ page }) => {
  const parcel = indicativeParcel();
  parcel.public_hazard_layer.usgs_lag_ft = 0;
  parcel.private_verification_layer.cv_confidence = .6;
  parcel.input_provenance = [
    { field: "public_hazard_layer.usgs_lag_ft", value_source: "DEFAULT", source_name: "Default elevation", vintage: null },
    { field: "private_verification_layer.cv_confidence", value_source: "DEFAULT", source_name: "Default confidence", vintage: null },
  ];
  await page.route("**/v1/parcel/score", route => route.fulfill({ json: parcel }));
  await page.goto("/assessment?demo=true");
  await page.getByRole("checkbox", { name: "Live API", exact: true }).check();
  const score = page.locator(".score-panel");
  for (const label of ["USGS 3DEP · Ground elevation", "Aerial computer vision"]) {
    const row = score.locator(".evidence-list li").filter({ hasText: label });
    await expect(row.locator("span").last()).toHaveText("Default input");
    await expect(row.locator(".lucide-check")).toHaveCount(0);
  }
});

test("a measured zero elevation is supplied while reference evidence remains labeled", async ({ page }) => {
  const parcel: ParcelScoreResponse = structuredClone(fixtures.NYC_RED_HOOK);
  parcel.public_hazard_layer.usgs_lag_ft = 0;
  parcel.input_provenance = [
    { field: "usgs_lag_ft", value_source: "LIVE", source_name: "USGS 3DEP EPQS", vintage: null },
    { field: "cv_confidence", value_source: "REFERENCE_PARCEL", source_name: "Reference record", vintage: null },
  ];
  parcel.private_verification_layer.cv_confidence = .96;
  await page.route("**/v1/parcel/score", route => route.fulfill({ json: parcel }));
  await page.goto("/assessment?demo=true");
  await page.getByRole("checkbox", { name: "Live API", exact: true }).check();
  const score = page.locator(".score-panel");
  await expect(score.locator(".panel-heading").first().locator(".badge")).toHaveText("Model result");
  const ground = score.locator(".evidence-list li").filter({ hasText: "USGS 3DEP · Ground elevation" });
  await expect(ground.locator("span").last()).toHaveText("Supplied");
  await expect(ground.locator(".lucide-check")).toHaveCount(1);
  const cv = score.locator(".evidence-list li").filter({ hasText: "Aerial computer vision" });
  await expect(cv.locator("span").last()).toHaveText("Reference data");
  await expect(cv.locator(".lucide-check")).toHaveCount(0);
});
