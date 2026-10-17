import { expect, test, type Page } from "@playwright/test";
import simulations from "../../../contracts/golden_simulations.json";
import { money } from "../../src/lib/format";
import fixtures from "../../../contracts/golden_scenarios.json";

const la = fixtures.SCENARIO_1_LA_FLOOD.actuarial_breakdown;
const ca = fixtures.SCENARIO_2_CA_WUI.actuarial_breakdown;
const escondido = fixtures.SCENARIO_3_ESCONDIDO_HITL.actuarial_breakdown;
const caPlans: Record<string, { resili_score: number; annual_discounted_premium_usd: number; net_capex_usd: number }> = simulations.SCENARIO_2_CA_WUI;
const plan = (ids: string[]) => caPlans[ids.sort().join("+")];
const apiPattern = "**/v1/**";

async function openOfflineDemo(page: Page) {
  const apiRequests: string[] = [];
  page.on("request", request => {
    if (/\/v1\//.test(request.url())) apiRequests.push(request.url());
  });
  await page.route(apiPattern, route => route.abort("connectionrefused"));
  await page.goto("/assessment?demo=true");
  await expect(page.getByTestId("score")).toHaveText(String(la.resili_score));
  return apiRequests;
}

test("coastal flood binds a demo receipt without a backend or a second verified discount", async ({ page }) => {
  const apiRequests = await openOfflineDemo(page);
  await page.getByRole("button", { name: /Coastal flood/ }).click();
  await expect(page.getByRole("heading", { name: "412 Bayou Rd" })).toBeVisible();
  const roof = page.getByRole("checkbox", { name: /IBHS FORTIFIED Roof/ });
  await expect(roof).toBeChecked();
  await expect(roof).toBeDisabled();
  await page.getByRole("button", { name: "Auto-bind in PolicyCenter" }).click();
  const receipt = page.getByRole("dialog");
  await expect(receipt).toContainText("Demo policy issued");
  await expect(receipt).toContainText("No policy has been purchased or sent to Guidewire");
  await expect(receipt).toContainText('"demo": true');
  await expect(receipt).toContainText(`"annual_premium_usd": ${la.annual_discounted_premium_usd}`);
  const downloadEvent = page.waitForEvent("download");
  await receipt.getByRole("button", { name: "Download IDM receipt" }).click();
  expect((await downloadEvent).suggestedFilename()).toMatch(/^DEMO-LA-.*\.json$/);
  await page.keyboard.press("Escape");
  await expect(receipt).not.toBeVisible();
  expect(apiRequests).toEqual([]);
});

test("wildfire remediation uses combined-action results and resets to baseline", async ({ page }) => {
  const apiRequests = await openOfflineDemo(page);
  await page.getByRole("button", { name: /Wildfire remediation/ }).click();
  await expect(page.getByTestId("score")).toHaveText(String(ca.resili_score));
  await page.getByRole("tab", { name: "Mitigation & grant ROI" }).click();
  await page.getByRole("checkbox", { name: /Zone 0\/1 clearance/ }).check();
  await expect(page.getByTestId("score")).toHaveText(String(plan(["CA_ZONE0_1_CLEARANCE"]).resili_score));
  await page.getByRole("checkbox", { name: /1\/4-inch ember vents/ }).check();
  await expect(page.getByTestId("score")).toHaveText(String(plan(["CA_ZONE0_1_CLEARANCE", "CA_EMBER_VENTS_EAVES"]).resili_score));
  await page.getByRole("checkbox", { name: /IBHS Wildfire Prepared Home Class A roof/ }).check();
  await expect(page.getByTestId("score")).toHaveText(String(plan(["CA_ZONE0_1_CLEARANCE", "CA_EMBER_VENTS_EAVES", "CA_IBHS_WPH_CLASS_A_ROOF"]).resili_score));
  await expect(page.getByText("Offline projections retain the baseline peril allocation.")).toBeVisible();
  await expect(page.getByTestId("annual-savings")).toHaveText(money(ca.annual_discounted_premium_usd - plan(["CA_ZONE0_1_CLEARANCE", "CA_EMBER_VENTS_EAVES", "CA_IBHS_WPH_CLASS_A_ROOF"]).annual_discounted_premium_usd));
  await expect(page.getByTestId("net-investment")).toHaveText(money(plan(["CA_ZONE0_1_CLEARANCE", "CA_EMBER_VENTS_EAVES", "CA_IBHS_WPH_CLASS_A_ROOF"]).net_capex_usd));
  await page.getByRole("button", { name: "Issue 60-day conditional bind" }).click();
  await expect(page.getByRole("dialog")).toContainText('"status": "CONDITIONAL_60_DAY"');
  await expect(page.getByRole("dialog")).toContainText('"review_due_days": 60');
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "Reset plan" }).click();
  await expect(page.getByTestId("score")).toHaveText(String(ca.resili_score));
  await expect(page.getByTestId("annual-savings")).toHaveText("$0");
  await expect(page.getByRole("checkbox", { name: /Zone 0\/1 clearance/ })).not.toBeChecked();
  expect(apiRequests).toEqual([]);
});

test("Escondido holds auto-bind until demo smartphone evidence is reviewed", async ({ page }) => {
  const apiRequests = await openOfflineDemo(page);
  await page.getByRole("button", { name: /Verification guardrail/ }).click();
  await expect(page.getByTestId("score")).toHaveText(String(escondido.resili_score));
  await page.getByRole("checkbox", { name: /Simulate satellite change-detection alert/ }).check();
  await expect(page.getByRole("alert").filter({ hasText: "240 sq ft" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Binding paused for verification" })).toBeDisabled();
  await page.getByRole("button", { name: "Open review workbench" }).click();
  const workbench = page.getByRole("dialog");
  await expect(workbench.getByRole("button", { name: "Verify & restore auto-bind" })).toBeDisabled();
  await workbench.getByRole("button", { name: "Request smartphone verification" }).click();
  await workbench.getByRole("button", { name: "Run demo capture" }).click();
  await workbench.getByRole("button", { name: "Verify & restore auto-bind" }).click();
  await expect(workbench).not.toBeVisible();
  await expect(page.getByTestId("score")).toHaveText(String(escondido.resili_score));
  await expect(page.getByRole("status")).toContainText(`Auto-bind restored at ${escondido.resili_score}`);
  await page.getByRole("button", { name: "Auto-bind in PolicyCenter" }).click();
  await expect(page.getByRole("dialog")).toContainText("Demo policy issued");
  expect(apiRequests).toEqual([]);
});

test("accepting the unpermitted structure only permits a conditional receipt", async ({ page }) => {
  await openOfflineDemo(page);
  await page.getByRole("button", { name: /Verification guardrail/ }).click();
  await page.getByRole("checkbox", { name: /Simulate satellite change-detection alert/ }).check();
  await page.getByRole("button", { name: "Open review workbench" }).click();
  await page.getByRole("dialog").getByRole("button", { name: /Apply structure loading/ }).click();
  await expect(page.getByRole("status")).toContainText("+35 bps LCR and $60,000 RCV");
  await expect(page.getByRole("button", { name: "Auto-bind in PolicyCenter" })).not.toBeVisible();
  await page.getByRole("button", { name: "Issue 60-day conditional bind" }).click();
  await expect(page.getByRole("dialog")).toContainText('"status": "CONDITIONAL_60_DAY"');
  await expect(page.getByRole("dialog")).toContainText(`"posterior_lcr": ${fixtures.SCENARIO_3_ESCONDIDO_HITL__UNPERMITTED.actuarial_breakdown.posterior_lcr + .0035}`);
});

test("regulatory audit keeps missing evidence explicit and exports the parcel dossier", async ({ page }) => {
  const apiRequests = await openOfflineDemo(page);
  await page.getByRole("tab", { name: "Regulatory audit" }).click();
  await expect(page.getByText("Evidence not provided", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("Not provided", { exact: true }).first()).toBeVisible();
  const downloadEvent = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download full JSON dossier" }).click();
  expect((await downloadEvent).suggestedFilename()).toMatch(/\.json$/);
  expect(apiRequests).toEqual([]);
});

for (const failure of ["unavailable", "invalid contract"] as const) {
  test(`Live API ${failure} falls back to a usable demo`, async ({ page }) => {
    await page.route(apiPattern, route => failure === "unavailable"
      ? route.abort("connectionrefused")
      : route.fulfill({ json: { score: 765 } }));
    await page.goto("/assessment?demo=true");
    await page.getByRole("checkbox", { name: "Live API", exact: true }).check();
    await expect(page.getByRole("status")).toContainText("Showing the local demo. All controls remain available.");
    await expect(page.getByTestId("score")).toHaveText(String(la.resili_score));
    await page.getByRole("button", { name: /Wildfire remediation/ }).click();
    await page.getByRole("checkbox", { name: /Zone 0\/1 clearance/ }).check();
    await expect(page.getByTestId("score")).toHaveText(String(plan(["CA_ZONE0_1_CLEARANCE"]).resili_score));
    await expect(page.getByRole("status")).toContainText("Showing the local demo");
  });
}

test("a failed live reconnect discards the previous live response and shows the local parcel", async ({ page }) => {
  let available = true;
  const liveParcel = structuredClone(fixtures.SCENARIO_1_LA_FLOOD);
  liveParcel.actuarial_breakdown.resili_score = 800;
  await page.route(apiPattern, route => available
    ? route.fulfill({ json: liveParcel })
    : route.abort("connectionrefused"));
  await page.goto("/assessment?demo=true");
  const liveToggle = page.getByRole("checkbox", { name: "Live API", exact: true });
  await liveToggle.check();
  await expect(page.getByRole("status")).toContainText("Live API response validated");
  await expect(page.getByTestId("score")).toHaveText("800");
  await liveToggle.uncheck();
  await expect(page.getByTestId("score")).toHaveText(String(la.resili_score));
  available = false;
  await liveToggle.check();
  await expect(page.getByRole("status")).toContainText("Showing the local demo");
  await expect(page.getByTestId("score")).toHaveText(String(la.resili_score));
  await expect(page.getByText("Golden demo parcel", { exact: true })).toBeVisible();
});

test("a late live response cannot overwrite a newly selected scenario", async ({ page }) => {
  let releaseFirst!: () => void;
  let firstStarted!: () => void;
  let firstSettled!: () => void;
  const held = new Promise<void>(resolve => { releaseFirst = resolve; });
  const started = new Promise<void>(resolve => { firstStarted = resolve; });
  const settled = new Promise<void>(resolve => { firstSettled = resolve; });
  await page.route(apiPattern, async route => {
    const body = route.request().postDataJSON();
    if (body.scenario_id === "SCENARIO_1_LA_FLOOD") {
      firstStarted();
      await held;
      try {
        await route.fulfill({ json: fixtures.SCENARIO_1_LA_FLOOD });
      } finally {
        firstSettled();
      }
    } else {
      await route.fulfill({ json: fixtures.SCENARIO_2_CA_WUI });
    }
  });
  await page.goto("/assessment?demo=true");
  await page.getByRole("checkbox", { name: "Live API", exact: true }).check();
  await started;
  await page.getByRole("button", { name: /Wildfire remediation/ }).click();
  await expect(page.getByRole("status")).toContainText("Live API response validated");
  await expect(page.getByTestId("score")).toHaveText(String(ca.resili_score));
  releaseFirst();
  await settled;
  await expect(page.getByRole("heading", { name: "1840 Canyon Crest Dr" })).toBeVisible();
  await expect(page.getByTestId("score")).toHaveText(String(ca.resili_score));
});
