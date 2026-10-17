import { expect, test } from "@playwright/test";
import fs from "node:fs/promises";
import path from "node:path";
import simulations from "../../../contracts/golden_simulations.json";
import { money } from "../../src/lib/format";
import fixtures from "../../../contracts/golden_scenarios.json";
import { scenarios } from "../../src/data/goldenScenarios";
import type { ParcelScoreResponse } from "../../src/types/resiliscore";

// Test responses exercise the pending NYC shape without inventing production fixtures.
function nycParcel(address = "5 Luquer St, Brooklyn, NY"): ParcelScoreResponse {
  const parcel: ParcelScoreResponse = structuredClone(fixtures.SCENARIO_1_LA_FLOOD);
  Object.assign(parcel.parcel_identity, { address, state: "NY", apn_uid: "03000000000001", centroid: [-74.004, 40.676] });
  parcel.nyc = {
    bbl: "3000000001", bin: null, borough: "Brooklyn", bldg_class: null,
    year_built: null, num_floors: null, basement_code: null, basement_type: "FULL",
    ground_elevation_ft: 8.5, roof_height_ft: null, dep_stormwater: [],
    floodnet_events_500m_5y: null, floodnet_max_depth_in: 14.2,
    sewer_backup_311_500m_5y: 12, street_flooding_311_500m_5y: 23,
    residential_units_500m: null, catch_basins_150m: 7, dob_open_violations: null,
    dob_cellar_conversion_flag: null, sandy_inundated: true, evacuation_zone: "1",
  };
  const row = parcel.actuarial_breakdown.peril_split[0];
  parcel.actuarial_breakdown.peril_split = ["FLOOD", "PLUVIAL", "SEWER_BACKUP"].map((peril, i) => ({ ...row, peril: peril as "FLOOD" | "PLUVIAL" | "SEWER_BACKUP", peril_aal_usd: [300, 200, 100][i] }));
  parcel.prescriptive_mitigations = ["Backwater valve", "Flood vents", "Elevated mechanicals", "Sump pump"].map((title, i) => ({
    ...parcel.prescriptive_mitigations[0], action_id: `NYC_TEST_${i}`, title, currently_applied: false,
  }));
  return parcel;
}

const nycScenarios = scenarios.filter(s => s.id.startsWith("NYC_"));
for (const scenario of nycScenarios) {
  test(`${scenario.id} posts the scenario ID and uses the existing simulation endpoint`, async ({ page }) => {
    const requests: { path: string; body: Record<string, unknown> }[] = [];
    const base = nycParcel(`${scenario.address}, ${scenario.location}`);
    const simulated = structuredClone(base);
    simulated.actuarial_breakdown.resili_score = 840;
    await page.route("**/v1/**", route => {
      const requestPath = new URL(route.request().url()).pathname;
      requests.push({ path: requestPath, body: route.request().postDataJSON() });
      return route.fulfill({ json: requestPath.endsWith("simulate-mitigation") ? simulated : base });
    });
    await page.goto("/assessment?demo=true");
    await expect(page.getByRole("heading", { name: "NYC Lot", exact: true })).toHaveCount(0);
    await page.getByRole("button", { name: new RegExp(scenario.title) }).click();
    await page.getByRole("checkbox", { name: "Live API", exact: true }).check();
    await expect(page.getByRole("heading", { name: scenario.address, exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "NYC Lot", exact: true })).toBeVisible();
    await expect(page.getByText("Street/rain flooding", { exact: true })).toBeVisible();
    await expect(page.getByText("Sewer backup", { exact: true })).toBeVisible();
    const lot = page.getByRole("region", { name: "NYC Lot", exact: true });
    await expect(lot).toContainText("3000000001");
    await expect(lot).toContainText("8.5 ft");
    await expect(lot).toContainText("14.2 in");
    await expect(lot.locator("div").filter({ has: page.locator("dt", { hasText: "DOB open violations" }) }).last()).toContainText("No data");
    await page.getByRole("checkbox", { name: /Backwater valve/ }).check();
    await expect(page.getByTestId("score")).toHaveText("840");
    await expect(page.getByText("Offline projections retain the baseline peril allocation.")).toHaveCount(0);
    expect(requests).toContainEqual({ path: "/v1/parcel/score", body: { scenario_id: scenario.id } });
    expect(requests).toContainEqual({ path: "/v1/parcel/simulate-mitigation", body: { apn_uid: "03000000000001", action_ids: ["NYC_TEST_0"] } });
  });

  test(`${scenario.id} runs its canonical offline baseline and complete retrofit plan without a backend`, async ({ page }) => {
    const requests: string[] = [];
    page.on("request", request => { if (/\/v1\//.test(request.url())) requests.push(request.url()); });
    const fixture = fixtures[scenario.id as keyof typeof fixtures];
    const actions = fixture.prescriptive_mitigations.filter(action => !action.currently_applied);
    const key = actions.map(action => action.action_id).sort().join("+");
    const expected = simulations[scenario.id as keyof typeof simulations][key];
    await page.goto("/assessment?demo=true");
    await page.getByRole("button", { name: new RegExp(scenario.title) }).click();
    await expect(page.getByTestId("score")).toHaveText(String(fixture.actuarial_breakdown.resili_score));
    await expect(page.getByRole("heading", { name: fixture.parcel_identity.address.split(",")[0], exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "NYC Lot", exact: true })).toBeVisible();
    const lot = page.getByRole("region", { name: "NYC Lot", exact: true });
    await expect(lot).toContainText(fixture.nyc!.bbl!);
    await expect(page.getByText("Street/rain flooding", { exact: true })).toBeVisible();
    await expect(page.getByText("Sewer backup", { exact: true })).toBeVisible();
    await page.getByRole("tab", { name: "Mitigation & grant ROI" }).click();
    for (const action of actions) {
      await page.locator("label.mitigation-row").filter({ hasText: action.title }).getByRole("checkbox").check();
    }
    await expect(page.getByTestId("score")).toHaveText(String(expected.resili_score));
    await expect(page.getByTestId("net-investment")).toHaveText(money(expected.net_capex_usd));
    await expect(page.getByTestId("annual-savings")).toHaveText(money(fixture.actuarial_breakdown.annual_discounted_premium_usd - expected.annual_discounted_premium_usd));
    await expect(page.getByText("Offline projections retain the baseline peril allocation.")).toBeVisible();
    await page.getByRole("tab", { name: "Model Validation" }).click();
    await expect(page.getByRole("heading", { name: "Model Validation", exact: true })).toBeVisible();
    await page.getByRole("tab", { name: "Mitigation & grant ROI" }).click();
    await page.getByRole("button", { name: "Reset plan" }).click();
    await expect(page.getByTestId("score")).toHaveText(String(fixture.actuarial_breakdown.resili_score));
    expect(requests).toEqual([]);
  });
}

test("live NYC addresses show unknown evidence, keep real negatives, and hide mitigation toggles", async ({ page }) => {
  const parcel = nycParcel("100 Test St, Queens, NY");
  Object.assign(parcel.nyc!, { basement_type: "UNKNOWN", ground_elevation_ft: null, sandy_inundated: false, evacuation_zone: null, floodnet_max_depth_in: null, sewer_backup_311_500m_5y: null, street_flooding_311_500m_5y: 0, catch_basins_150m: null });
  const requests: Record<string, unknown>[] = [];
  await page.route("**/v1/**", route => {
    requests.push(route.request().postDataJSON());
    return route.fulfill({ json: parcel });
  });
  await page.goto("/assessment?demo=true");
  const search = page.getByRole("textbox", { name: "Search address or APN" });
  await search.fill("100 Test St, Queens, NY");
  await search.press("Enter");
  await expect(page.getByRole("heading", { name: "100 Test St", exact: true })).toBeVisible();
  const lot = page.getByRole("region", { name: "NYC Lot", exact: true });
  for (const label of ["Basement type", "Ground elevation", "Hurricane evacuation zone", "FloodNet max depth", "311 sewer backups", "Catch basins", "DOB open violations"]) {
    await expect(lot.locator("dt").filter({ hasText: label }).locator("..").locator("dd")).toHaveText("No data");
  }
  await expect(lot.locator("dt").filter({ hasText: "Sandy-inundated" }).locator("..").locator("dd")).toHaveText("No");
  await expect(lot.locator("dt").filter({ hasText: "311 street flooding" }).locator("..").locator("dd")).toHaveText("None reported");
  for (const title of ["Backwater valve", "Flood vents", "Elevated mechanicals", "Sump pump"]) {
    await expect(page.getByText(title, { exact: true })).toBeVisible();
    await expect(page.getByRole("checkbox", { name: new RegExp(title) })).toHaveCount(0);
  }
  await page.getByRole("tab", { name: "Mitigation & grant ROI" }).click();
  await expect(page.getByRole("checkbox", { name: /Backwater valve/ })).toHaveCount(0);
  expect(requests).toEqual([{ address: "100 Test St, Queens, NY" }]);
});

test("a failed live lookup never presents the previous scenario as the requested address", async ({ page }) => {
  await page.route("**/v1/**", route => route.abort("connectionrefused"));
  await page.goto("/assessment?demo=true");
  await page.getByRole("textbox", { name: "Search address or APN" }).fill("100 Missing St, Queens, NY");
  await page.getByRole("textbox", { name: "Search address or APN" }).press("Enter");
  await expect(page.getByRole("status")).toContainText("Address lookup failed");
  await expect(page.getByTestId("score")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "412 Bayou Rd" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Retry lookup" })).toBeVisible();
  await page.getByRole("button", { name: /Coastal flood/ }).click();
  await expect(page.getByTestId("score")).toBeVisible();
});

test("a late live-address response cannot overwrite a golden scenario selection", async ({ page }) => {
  let release!: () => void;
  let started!: () => void;
  const held = new Promise<void>(resolve => { release = resolve; });
  const requested = new Promise<void>(resolve => { started = resolve; });
  await page.route("**/v1/**", async route => {
    if (route.request().postDataJSON().address) {
      started(); await held;
      await route.fulfill({ json: nycParcel("100 Late St, Queens, NY") }).catch(() => {});
    } else await route.fulfill({ json: fixtures.SCENARIO_2_CA_WUI });
  });
  await page.goto("/assessment?demo=true");
  await page.getByRole("textbox", { name: "Search address or APN" }).fill("100 Late St, Queens, NY");
  await page.getByRole("textbox", { name: "Search address or APN" }).press("Enter");
  await requested;
  await page.getByRole("button", { name: /Wildfire remediation/ }).click();
  release();
  await expect(page.getByRole("heading", { name: "1840 Canyon Crest Dr" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "NYC Lot", exact: true })).toHaveCount(0);
});

test("NYC evidence fits desktop and mobile", async ({ page }) => {
  await page.route("**/v1/**", route => route.fulfill({ json: nycParcel() }));
  await page.goto("/assessment?demo=true");
  await page.getByRole("button", { name: /NYC Red Hook/ }).click();
  await page.getByRole("checkbox", { name: "Live API", exact: true }).check();
  await expect(page.getByRole("heading", { name: "NYC Lot", exact: true })).toBeVisible();
  await page.emulateMedia({ reducedMotion: "reduce" });
  const dir = path.resolve(".impeccable/review");
  await fs.mkdir(dir, { recursive: true });
  for (const [name, width, height] of [["desktop", 1440, 1000], ["mobile", 390, 844]] as const) {
    await page.setViewportSize({ width, height });
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: path.join(dir, `nyc-${name}.png`), fullPage: true, animations: "disabled" });
  }
});
