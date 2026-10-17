import { expect, test } from "@playwright/test";

test.use({ launchOptions: { args: ["--enable-unsafe-swiftshader"] } });

test("measured ground relief has explicit actual and exaggerated viewing scales", async ({ page }) => {
  test.setTimeout(60_000);
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/?neighborhood=MN1292");
  await expect(page.getByRole("heading", { name: "Inwood Hill Park", exact: true })).toBeVisible();
  await expect(page.locator("canvas")).toBeVisible({ timeout: 30_000 });
  const terrain = page.getByRole("checkbox", { name: "Terrain relief", exact: true });
  await terrain.check();
  await expect(page.getByRole("radio", { name: "1× actual", exact: true })).toBeChecked();
  await expect(page.getByText("USGS ground elevation · metres", { exact: true })).toBeVisible();
  await page.getByRole("radio", { name: "3× relief", exact: true }).check();
  await expect(page.getByRole("status").filter({ hasText: "Ground heights exaggerated" })).toContainText("Assessment inputs stay unchanged");
  await page.getByRole("checkbox", { name: "Underground drainage", exact: true }).check();
  await expect(page.getByText(/Depths unavailable; vertical offset is schematic/)).toBeVisible();
  await terrain.uncheck();
  await expect(page.getByRole("radio", { name: "3× relief", exact: true })).toHaveCount(0);
  await expect(page.locator("canvas")).toBeVisible();
  expect(errors).toEqual([]);
});

test("terrain controls fit a phone and remain keyboard accessible without WebGL", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.addInitScript(() => {
    const original = HTMLCanvasElement.prototype.getContext;
    Object.defineProperty(HTMLCanvasElement.prototype, "getContext", {
      value(context: string, ...args: unknown[]) { return context.includes("webgl") ? null : Reflect.apply(original, this, [context, ...args]); },
    });
  });
  await page.goto("/");
  const terrain = page.getByRole("checkbox", { name: "Terrain relief", exact: true });
  await terrain.focus();
  await page.keyboard.press("Space");
  await expect(terrain).toBeChecked();
  const actual = page.getByRole("radio", { name: "1× actual", exact: true });
  await actual.focus();
  await page.keyboard.press("ArrowRight");
  await expect(page.getByRole("radio", { name: "3× relief", exact: true })).toBeChecked();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
