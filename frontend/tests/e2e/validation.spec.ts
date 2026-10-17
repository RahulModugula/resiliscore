import { expect, test } from "@playwright/test";
import report from "../../../contracts/validation_report.json";
import parcel from "../../../contracts/golden_scenarios.json";
import flood from "../fixtures/validation-flood.json";

test("offline validation shows source data, all fires, verdicts, and an export without API requests", async ({ page }) => {
  const requests: string[] = [];
  page.on("request", request => { if (request.url().includes("/v1/")) requests.push(request.url()); });
  await page.route("**/v1/**", route => route.abort("connectionrefused"));
  await page.goto("/");
  await page.getByRole("tab", { name: "Model Validation", exact: true }).click();
  const workspace = page.getByRole("tabpanel");
  await expect(workspace.getByText(report.wildfire!.verdict, { exact: true })).toBeVisible();
  await expect(workspace.getByText(report.wildfire!.adoption_note!, { exact: true })).toBeVisible();
  await expect(workspace.locator(".validation-fires .validation-row-label")).toHaveCount(report.wildfire!.fires.length);
  await expect(workspace.locator(".validation-forest .validation-row-label")).toHaveCount(report.wildfire!.features.length);
  await expect(page.getByRole("heading", { name: "Results pending", exact: true })).toBeVisible();
  const selected = [...report.wildfire!.fires].sort((a, b) => b.n_structures - a.n_structures)[0];
  await expect(page.getByRole("combobox", { name: "Wildfire holdout fire" })).toHaveValue(`${selected.fire}-${selected.year}`);
  const other = report.wildfire!.fires.at(-1)!;
  await page.getByRole("combobox", { name: "Wildfire holdout fire" }).selectOption(`${other.fire}-${other.year}`);
  await expect(workspace.locator(".validation-kpis")).toContainText(other.auc_current.toFixed(3));
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download report", exact: true }).click();
  expect((await download).suggestedFilename()).toBe("model-validation-report.json");
  expect(requests).toEqual([]);
});

test("live flood renders uncertainty, signed bias, zero values, and keyboard caveats", async ({ page }) => {
  await page.route("**/v1/**", route => route.fulfill({ json: route.request().url().endsWith("/model/validation") ? { ...report, flood, status: "COMPLETE" } : parcel.SCENARIO_1_LA_FLOOD }));
  await page.goto("/");
  await page.getByRole("tab", { name: "Model Validation", exact: true }).click();
  await page.getByRole("checkbox", { name: "Live API", exact: true }).check();
  await expect(page.getByRole("status")).toContainText("Live validation report checked");
  await expect(page.getByText(flood.verdict, { exact: true })).toBeVisible();
  await expect(page.getByText(flood.adoption_note, { exact: true })).toBeVisible();
  await expect(page.getByRole("img", { name: /^Flood damage ratio by depth/ })).toBeVisible();
  await expect(page.locator(".validation-fitted-point")).toHaveCount(flood.severity_by_depth.filter(bucket => bucket.fitted_pred_dr !== null).length);
  const storm = page.getByRole("row").filter({ hasText: "Test storm" });
  await expect(storm).toContainText("20%");
  await expect(storm).toContainText("-10 pp");
  await storm.getByLabel("Result caveat").focus();
  await expect(page.getByRole("tooltip")).toHaveText(flood.events[0].note!);
  await page.keyboard.press("Escape");
  await expect(page.getByRole("tooltip")).toHaveCount(0);
  await storm.getByLabel("Result caveat").blur();
  await storm.getByLabel("Result caveat").hover();
  await page.getByRole("tooltip").hover();
  await expect(page.getByRole("tooltip")).toHaveText(flood.events[0].note!);
  await page.getByRole("tooltip").focus();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("tooltip")).toHaveCount(0);
  await expect(page.getByRole("row").filter({ hasText: "Test zero storm" })).toContainText("Unbiased");
  expect(await page.locator(".validation-flood-chart").evaluate(element => /NaN|Infinity/.test(element.outerHTML))).toBe(false);
  await page.getByRole("checkbox", { name: "Live API", exact: true }).uncheck();
  await expect(page.getByRole("status")).toContainText("Available offline");
  await expect(page.getByText(flood.verdict, { exact: true })).toHaveCount(0);
});

test("a fully pending report does not display invented metrics", async ({ page }) => {
  await page.route("**/v1/**", route => route.fulfill({ json: route.request().url().endsWith("/model/validation") ? { ...report, status: "PENDING", flood: null, wildfire: null, benchmarks: [] } : parcel.SCENARIO_1_LA_FLOOD }));
  await page.goto("/");
  await page.getByRole("tab", { name: "Model Validation", exact: true }).click();
  await page.getByRole("checkbox", { name: "Live API", exact: true }).check();
  await expect(page.getByRole("status")).toContainText("Live validation report checked");
  await expect(page.getByRole("heading", { name: "Results pending", exact: true })).toHaveCount(3);
  await expect(page.getByRole("combobox", { name: "Wildfire holdout fire" })).toHaveCount(0);
  await expect(page.locator(".validation-kpis")).toContainText(`${report.model_card.constants_validated}`);
});

for (const failure of ["unavailable", "invalid"] as const) {
  test(`validation API ${failure} retains the offline report`, async ({ page }) => {
    await page.route("**/v1/**", route => failure === "unavailable" ? route.abort("connectionrefused") : route.fulfill({ json: {} }));
    await page.goto("/");
    await page.getByRole("tab", { name: "Model Validation", exact: true }).click();
    await page.getByRole("checkbox", { name: "Live API", exact: true }).check();
    await expect(page.getByRole("status")).toContainText("Showing the bundled validation report.");
    await expect(page.getByText(report.wildfire!.verdict, { exact: true })).toBeVisible();
  });
}

test("four-tab keyboard navigation and narrow layouts remain usable", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await page.getByRole("tab", { name: "Underwriting copilot", exact: true }).focus();
  await page.keyboard.press("End");
  const validation = page.getByRole("tab", { name: "Model Validation", exact: true });
  await expect(validation).toBeFocused();
  await expect(validation).toHaveAttribute("aria-selected", "true");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.keyboard.press("ArrowRight");
  await expect(page.getByRole("tab", { name: "Underwriting copilot", exact: true })).toBeFocused();
});
