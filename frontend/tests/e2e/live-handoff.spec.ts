import { expect, test, type Page } from "@playwright/test";
import fixtures from "../../../contracts/golden_scenarios.json";

async function liveReview(page: Page) {
  const overrides: unknown[] = [];
  await page.route("**/v1/parcel/score", route => {
    if (process.env.VALIDATION_API_URL) return route.continue();
    const id = route.request().postDataJSON().scenario_id as keyof typeof fixtures;
    return route.fulfill({ json: fixtures[id] });
  });
  await page.route("**/v1/hitl/verify-override", route => {
    overrides.push(route.request().postDataJSON());
    // The real endpoint verifies the base parcel; extra loading flags are ignored.
    return process.env.VALIDATION_API_URL ? route.continue()
      : route.fulfill({ json: fixtures.SCENARIO_3_ESCONDIDO_HITL });
  });
  await page.goto("/assessment?demo=true");
  await page.getByRole("button", { name: /Verification guardrail/ }).click();
  await page.getByRole("checkbox", { name: "Live API", exact: true }).check();
  await expect(page.getByRole("status").filter({ hasText: "Live API response validated" })).toBeVisible();
  await page.getByRole("checkbox", { name: /Simulate satellite change-detection alert/ }).check();
  await expect(page.getByRole("button", { name: "Binding paused for verification" })).toBeDisabled();
  await page.getByRole("button", { name: "Open review workbench" }).click();
  return overrides;
}

test("structure loading stays a conditional local demo and never calls verification", async ({ page }) => {
  const overrides = await liveReview(page);
  await page.getByRole("dialog").getByRole("button", { name: /Apply structure loading/ }).click();
  await expect(page.getByRole("checkbox", { name: "Live API", exact: true })).not.toBeChecked();
  await expect(page.getByRole("status").filter({ hasText: "Demo structure loading" })).toContainText("Live API off");
  await expect(page.getByRole("button", { name: "Auto-bind in PolicyCenter", exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "Issue 60-day conditional bind", exact: true }).click();
  await expect(page.getByRole("dialog")).toContainText('"status": "CONDITIONAL_60_DAY"');
  await page.keyboard.press("Escape");
  await page.getByRole("checkbox", { name: "Live API", exact: true }).check();
  await expect(page.getByRole("status").filter({ hasText: "Live API response validated" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Binding paused for verification" })).toBeDisabled();
  expect(overrides).toEqual([]);
});

test("verified review uses only the supported override body", async ({ page }) => {
  const overrides = await liveReview(page);
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("button", { name: "Request smartphone verification" }).click();
  await dialog.getByRole("button", { name: "Run demo capture" }).click();
  await dialog.getByRole("button", { name: "Verify & restore auto-bind" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Live API response validated" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Auto-bind in PolicyCenter", exact: true })).toBeVisible();
  expect(overrides).toEqual([{ apn_uid: fixtures.SCENARIO_3_ESCONDIDO_HITL.parcel_identity.apn_uid }]);
});

test("a cold address lookup can finish after five seconds", async ({ page }) => {
  await page.route("**/v1/parcel/score", async route => {
    expect(route.request().postDataJSON()).toEqual({ address: "5 Luquer St, Brooklyn, NY" });
    // The real handoff's cold US-address request took 5.02 seconds.
    await new Promise(resolve => setTimeout(resolve, 5_000));
    await route.fulfill({ json: fixtures.NYC_RED_HOOK });
  });
  await page.goto("/assessment?demo=true");
  await page.getByRole("textbox", { name: "Search address or APN" }).fill("5 Luquer St, Brooklyn, NY");
  await page.getByRole("textbox", { name: "Search address or APN" }).press("Enter");
  await expect(page.getByRole("status").filter({ hasText: "Live API response validated" })).toBeVisible({ timeout: 8_000 });
  await expect(page.getByRole("heading", { name: "NYC Lot", exact: true })).toBeVisible();
  await expect(page.getByRole("checkbox", { name: /backwater valve/i })).toHaveCount(0);
});
