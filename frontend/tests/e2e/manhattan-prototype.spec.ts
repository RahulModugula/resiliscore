import { readFile } from "node:fs/promises";
import { expect, test, type Page } from "@playwright/test";
import { assessManhattanProperty } from "../../src/lib/manhattan/assessment";
import type { NeighborhoodDetail } from "../../src/lib/manhattan/types";

async function prepare(page: Page) {
  const detail: NeighborhoodDetail = JSON.parse(await readFile("public/manhattan/neighborhoods/MN0603.json", "utf8"));
  const building = detail.buildings.find(b => b.id === "1112075")!;
  const result = await assessManhattanProperty(building, { preferLive: false });
  await page.addInitScript(result => sessionStorage.setItem("resiliscore:manhattan:assessment:v1:1112075", JSON.stringify({ savedAt: Date.now(), result })), result);
  await page.route("https://elevation.nationalmap.gov/**", route => route.abort("internetdisconnected"));
}

async function settledDrawCount(page: Page) {
  let previous = -1, stable = 0;
  await expect.poll(async () => {
    const count = await page.evaluate(() => Number(Reflect.get(window, "__terrainDraws")));
    stable = count === previous ? stable + 1 : 0;
    previous = count;
    return stable;
  }, { intervals: [200, 300, 400], timeout: 15000 }).toBeGreaterThanOrEqual(3);
  return previous;
}

for (const viewport of [{ name: "desktop", width: 1440, height: 1000 }, { name: "mobile", width: 390, height: 844 }]) {
  test(`${viewport.name}: bounded 2021 terrain works offline and retains camera, heights and idle rendering`, async ({ page }) => {
    test.setTimeout(60000);
    const errors: string[] = [];
    page.on("pageerror", error => errors.push(error.message));
    await page.setViewportSize(viewport);
    await prepare(page);
    await page.addInitScript(() => {
      Reflect.set(window, "__terrainDraws", 0);
      for (const prototype of [WebGLRenderingContext.prototype, WebGL2RenderingContext.prototype]) {
        for (const method of ["drawArrays", "drawElements"] as const) {
          const original = prototype[method];
          Object.defineProperty(prototype, method, { value: function (this: WebGLRenderingContext | WebGL2RenderingContext, ...args: Parameters<typeof original>) {
            Reflect.set(window, "__terrainDraws", Number(Reflect.get(window, "__terrainDraws")) + 1);
            return Reflect.apply(original, this, args);
          } });
        }
      }
    });
    let rasterRequests = 0;
    page.on("request", request => { if (request.url().endsWith("nyc2021-murray-hill.tif")) rasterRequests++; });
    const began = performance.now();
    await page.goto("/assessment?property=1112075&terrain=nyc2021");
    const block = page.getByRole("region", { name: "Building block context" });
    const status = block.getByTestId("block-elevation-status");
    await expect(status).toContainText("1.0 m derived ground grid · NYC 2021 prototype");
    const readyMs = performance.now() - began;
    const marker = block.getByTestId("selected-building-marker");
    await expect(marker).toBeVisible();
    await expect(marker).toHaveAttribute("data-property-id", "1112075");
    await expect(block.getByText(/Ground at the building base:/)).toContainText("First-floor elevation remains unknown");
    const height = await block.locator("dl > div").filter({ hasText: "Building height above ground" }).innerText();
    await expect(block.getByText(/Ground at the building base:/)).toContainText("43 of 191 perimeter samples are supported");
    await expect(block.getByText(/Experimental terrain from May 2021/)).toBeVisible();
    await settledDrawCount(page);
    await block.screenshot({ path: test.info().outputPath("2021-initial.png") });
    const canvas = block.locator("canvas");
    await canvas.scrollIntoViewIfNeeded();
    const box = (await canvas.boundingBox())!;
    await page.mouse.move(box.x + box.width * .4, box.y + box.height * .5);
    await page.mouse.down();
    await page.mouse.move(box.x + box.width * .7, box.y + box.height * .55, { steps: 20 });
    await page.mouse.up();
    await page.mouse.wheel(0, -150);
    await settledDrawCount(page);
    const before = (await marker.boundingBox())!;
    await block.screenshot({ path: test.info().outputPath("2021-orbit.png") });
    const switches: number[] = [];
    for (let i = 0; i < 3; i++) {
      await status.getByRole("button", { name: "Use USGS terrain" }).click();
      await expect(status).toContainText("Finer terrain unavailable");
      await settledDrawCount(page);
      if (i === 0) await block.screenshot({ path: test.info().outputPath("cached-usgs-same-camera.png") });
      const start = performance.now();
      await status.getByRole("button", { name: "Try 2021 terrain" }).click();
      await expect(status).toContainText("1.0 m derived ground grid");
      await settledDrawCount(page);
      switches.push(performance.now() - start);
      const after = (await marker.boundingBox())!;
      expect(Math.abs(after.x - before.x)).toBeLessThan(2);
      expect(Math.abs(after.y - before.y)).toBeLessThan(2);
      expect(await block.locator("dl > div").filter({ hasText: "Building height above ground" }).innerText()).toBe(height);
    }
    expect(rasterRequests).toBe(1);
    expect(page.url()).toContain("terrain=nyc2021");
    const draws = await settledDrawCount(page);
    expect(draws).toBeGreaterThan(0);
    await page.waitForTimeout(600);
    expect(await page.evaluate(() => Reflect.get(window, "__terrainDraws"))).toBe(draws);
    await page.getByRole("button", { name: "Use light theme" }).click();
    await expect(status).toContainText("NYC 2021 prototype");
    await page.getByRole("tab", { name: "Model Validation", exact: true }).click();
    await page.getByRole("tab", { name: "Underwriting copilot", exact: true }).click();
    await expect(status).toContainText("NYC 2021 prototype");
    await expect(marker).toBeVisible();
    expect(rasterRequests).toBe(1);
    await block.getByRole("button", { name: "Reset block view" }).click();
    await settledDrawCount(page);
    await block.screenshot({ path: test.info().outputPath("2021-light-reset.png") });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    const resources = await page.evaluate(() => performance.getEntriesByType("resource").filter(e => e.name.includes("/prototypes/")).map(e => ({ url: e.name, durationMs: e.duration, bytes: (e as PerformanceResourceTiming).decodedBodySize })));
    const gpu = await canvas.evaluate((element: HTMLCanvasElement) => { const gl = element.getContext("webgl2")!; const debug = gl.getExtension("WEBGL_debug_renderer_info"); return debug ? gl.getParameter(debug.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER); });
    await test.info().attach("terrain-validation.json", { body: JSON.stringify({ viewport, browser: page.context().browser()?.version(), gpu, navigationToStatusReadyMs: readyMs, cachedSwitchIncludingIdleSettleMs: switches, idleExtraDraws: 0, rasterRequests, resources }, null, 2), contentType: "application/json" });
    expect(errors).toEqual([]);
  });
}

test("2021 asset failure retains cached terrain and supports retry", async ({ page }) => {
  await prepare(page);
  let fail = true;
  await page.route("**/nyc2021-murray-hill.tif", route => fail ? route.fulfill({ status: 503 }) : route.fulfill({ path: "public/manhattan/prototypes/nyc2021-murray-hill.tif", contentType: "image/tiff" }));
  await page.goto("/assessment?property=1112075&terrain=nyc2021");
  const block = page.getByRole("region", { name: "Building block context" });
  const status = block.getByTestId("block-elevation-status");
  await expect(status).toContainText("10 m cached ground grid");
  await expect(status).toContainText("2021 terrain unavailable; cached elevations retained");
  await expect(block.getByTestId("selected-building-marker")).toBeVisible();
  fail = false;
  await status.getByRole("button", { name: "Retry 2021 terrain" }).click();
  await expect(status).toContainText("1.0 m derived ground grid");
  await expect(block.getByText(/Ground at the building base:/)).toContainText("First-floor elevation remains unknown");
});
