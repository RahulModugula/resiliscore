import { expect, test } from "@playwright/test";
import { assessManhattanProperty } from "../../src/lib/manhattan/assessment";
import type { Building } from "../../src/lib/manhattan/types";
import validationReport from "../../../contracts/validation_report.json";

const building: Building = { id: "123456", bin: "1000001", bbl: "1000010001", address: null, name: null, center: [-74.005, 40.715], footprint: [[[-74.0051, 40.7149], [-74.0049, 40.7149], [-74.0049, 40.7151], [-74.0051, 40.7151], [-74.0051, 40.7149]]], heightM: 15, groundElevationM: 7.2, neighborhoodId: "MN0101", yearBuilt: null, featureCode: "2100" };

test("selected property survives reload and shows an offline canonical screen without binding", async ({ page }) => {
  const result = await assessManhattanProperty(building, { preferLive: false });
  await page.addInitScript(({ id, result }) => sessionStorage.setItem(`resiliscore:manhattan:assessment:v1:${id}`, JSON.stringify({ savedAt: Date.now(), result })), { id: building.id, result });
  await page.route("**/v1/**", route => route.abort("connectionrefused"));
  await page.goto(`/assessment?property=${building.id}`);
  await expect(page.getByRole("heading", { name: "BIN 1000001", exact: true })).toBeVisible();
  await expect(page.getByRole("status")).toContainText("Offline model screening");
  await expect(page.getByText(`ResiliScore ${result.parcel.actuarial_breakdown.resili_score} / 850`, { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: /auto-bind|conditional bind/i })).toHaveCount(0);
  await expect(page.getByText("Golden demo parcel", { exact: true })).toHaveCount(0);
  await expect(page.getByText("Verified parcel", { exact: true })).toHaveCount(0);
  await page.getByRole("tab", { name: "Regulatory audit" }).click();
  await expect(page.getByText("REFERENCE_PARCEL", { exact: true })).toBeVisible();
  await expect(page.getByText(/nonlocal FEMA NRI reference tract/).first()).toBeVisible();
  await page.getByRole("tab", { name: "Model Validation", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Model Validation", exact: true })).toBeVisible();
  await expect(page.getByText(validationReport.flood!.adoption_note!, { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: /auto-bind|conditional bind/i })).toHaveCount(0);
  await page.reload();
  await expect(page.getByRole("heading", { name: "BIN 1000001", exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "Back to Manhattan map" })).toHaveAttribute("href", "/?neighborhood=MN0101");
});

test("missing property session shows recovery instead of a different parcel", async ({ page }) => {
  await page.goto("/assessment?property=missing");
  await expect(page.getByRole("heading", { name: "Select a Manhattan property" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Back to Manhattan map" })).toBeVisible();
  await expect(page.getByTestId("score")).toHaveCount(0);
});
