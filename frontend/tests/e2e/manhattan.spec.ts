import { expect, test, type Page } from "@playwright/test";
import { PerspectiveCamera, Vector3 } from "three";
import { cameraFrame, combineBounds, worldPoint } from "../../src/lib/manhattan/sceneGeometry";
import type { Bounds, Building, ManhattanOverview, Neighborhood, NeighborhoodDetail } from "../../src/lib/manhattan/types";

test.use({ launchOptions: { args: ["--enable-unsafe-swiftshader"] } });

const district = "Financial District-Battery Park City";

async function withoutWebGL(page: Page) {
  await page.addInitScript(() => {
    const original = HTMLCanvasElement.prototype.getContext;
    Object.defineProperty(HTMLCanvasElement.prototype, "getContext", {
      value(context: string, ...args: unknown[]) {
        return context.includes("webgl") ? null : Reflect.apply(original, this, [context, ...args]);
      },
    });
  });
}

test.describe("Manhattan directory works without WebGL or a backend", () => {
  test.beforeEach(async ({ page }) => {
    await withoutWebGL(page);
    await page.route("**/v1/**", route => route.abort("connectionrefused"));
  });

  test("real neighborhoods, drainage attribution, and offline property handoff", async ({ page }) => {
    const externalRequests: string[] = [];
    page.on("request", request => {
      if (!request.url().startsWith("http://127.0.0.1:") && !request.url().includes("/v1/") && !request.url().startsWith("data:")) externalRequests.push(request.url());
    });
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Manhattan", exact: true })).toBeVisible();
    await expect(page.getByText("The 3D map is unavailable.", { exact: false }).first()).toBeVisible();
    await page.getByRole("checkbox", { name: "Underground drainage" }).check();
    await expect(page.getByText("DEP storm drains · 13,292")).toBeVisible();
    await expect(page.getByText(/Depths unavailable; vertical offset is schematic/)).toBeVisible();
    await page.getByText("Map sources & accuracy", { exact: true }).click();
    await expect(page.getByRole("link", { name: /Open Sewer Atlas/ })).toBeVisible();
    await page.getByText("Map sources & accuracy", { exact: true }).click();
    await page.getByRole("button", { name: new RegExp(district) }).click();
    const property = page.getByRole("button", { name: /^Assess / }).first();
    await property.waitFor();
    const name = (await property.locator("strong").innerText()).trim();
    await property.click();
    await expect(page).toHaveURL(/\/assessment\?property=/);
    await expect(page.getByRole("heading", { name, exact: true })).toBeVisible();
    await expect(page.getByText("Offline model screening", { exact: true }).first()).toBeVisible();
    await expect(page.getByRole("status").filter({ hasText: "Offline model screening." })).toContainText(/national.default/);
    await expect(page.getByRole("button", { name: /bind.*PolicyCenter|Issue.*bind/ })).toHaveCount(0);
    await page.reload();
    await expect(page.getByRole("heading", { name, exact: true })).toBeVisible();
    await page.getByRole("link", { name: "Back to Manhattan map" }).click();
    await expect(page.getByRole("heading", { name: district, exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Return to all Manhattan" }).click();
    await expect(page.getByRole("heading", { name: "Manhattan", exact: true })).toBeVisible();
    expect(externalRequests).toEqual([]);
  });

  for (const failure of ["HTTP error", "invalid payload"] as const) test(`map asset ${failure} can be retried`, async ({ page }) => {
    let fail = true;
    await page.route("**/manhattan/manifest.json", route => fail ? route.fulfill(failure === "HTTP error" ? { status: 503, body: "unavailable" } : { json: { details: {}, sources: [] } }) : route.continue());
    await page.goto("/");
    await expect(page.getByRole("alert").filter({ hasText: "Map data" })).toBeVisible();
    await expect(page.locator('[aria-busy="true"]')).toHaveCount(0);
    fail = false;
    await page.getByRole("button", { name: "Reload map data" }).click();
    await expect(page.getByRole("button", { name: new RegExp(district) })).toBeVisible();
  });

  test("late detail data cannot replace the newly selected neighborhood", async ({ page }) => {
    let release!: () => void;
    let started!: () => void;
    const held = new Promise<void>(resolve => { release = resolve; });
    const requested = new Promise<void>(resolve => { started = resolve; });
    await page.route("**/manhattan/neighborhoods/MN0101.json", async route => {
      started();
      await held;
      await route.continue().catch(() => undefined);
    });
    await page.goto("/");
    await page.getByRole("button", { name: new RegExp(district) }).click();
    await requested;
    await page.getByRole("button", { name: "All Manhattan", exact: true }).click();
    await page.getByRole("button", { name: /Tribeca-Civic Center/ }).click();
    await expect(page.getByRole("list", { name: "Properties", exact: true })).toBeVisible();
    release();
    await expect(page.getByRole("heading", { name: "Tribeca-Civic Center", exact: true })).toBeVisible();
    await expect(page).toHaveURL(/neighborhood=MN0102/);
  });

  test("mobile directory and map controls fit the screen", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/");
    await page.getByRole("searchbox", { name: "Find a neighborhood" }).fill("Tribeca");
    await expect(page.getByRole("list", { name: "Neighborhoods", exact: true }).getByRole("button")).toHaveCount(1);
    await page.getByRole("button", { name: /Tribeca-Civic Center/ }).click();
    await expect(page.getByRole("button", { name: /^Assess / }).first()).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
});

test("real WebGL renderer loads and the transparent layer remains usable", async ({ page }) => {
  test.setTimeout(60_000);
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.route("**/v1/**", route => route.abort("connectionrefused"));
  let failDetail = true;
  await page.route("**/manhattan/neighborhoods/MN0101.json", route => {
    if (failDetail) { failDetail = false; return route.fulfill({ json: { neighborhoodId: "wrong-neighborhood", buildings: [] } }); }
    return route.continue();
  });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  await expect(page.getByRole("button", { name: new RegExp(district) })).toBeVisible();
  await expect(page.getByText("Click a neighborhood to explore", { exact: false })).toBeVisible({ timeout: 30_000 });
  await expect(page.locator("canvas")).toBeVisible({ timeout: 30_000 });
  const overview: ManhattanOverview = await (await page.request.get("/manhattan/overview.json")).json();
  const neighborhoods: Neighborhood[] = await (await page.request.get("/manhattan/neighborhoods.json")).json();
  const detail: NeighborhoodDetail = await (await page.request.get("/manhattan/neighborhoods/MN0101.json")).json();
  const tower = detail.buildings.reduce((highest, next) => (next.heightM ?? 0) > (highest.heightM ?? 0) ? next : highest);
  // Project a known real roof into the rendered camera, then exercise actual raycast picking.
  async function clickRoof(bounds: Bounds, buildings: Building[]) {
    const rect = (await page.locator("canvas").boundingBox())!;
    const skyline = buildings.reduce((max, building) => Math.max(max, (building.groundElevationM ?? 0) + (building.heightM ?? 0)), 0);
    const frame = cameraFrame(bounds, rect.width / rect.height, skyline);
    const camera = new PerspectiveCamera(38, rect.width / rect.height, 2, 150000);
    camera.position.set(...frame.position); camera.lookAt(...frame.target); camera.updateMatrixWorld();
    const roof = new Vector3(...worldPoint(tower.center, (tower.groundElevationM ?? 0) + (tower.heightM ?? 0))).project(camera);
    await page.mouse.click(rect.x + (roof.x + 1) / 2 * rect.width, rect.y + (1 - roof.y) / 2 * rect.height);
  }
  await clickRoof(combineBounds(neighborhoods), overview.buildings);
  await expect(page.getByRole("heading", { name: district, exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Retry neighborhood" })).toBeVisible();
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  // Reselecting the same map neighborhood must retry its failed, uncached detail.
  await clickRoof(neighborhoods.find(item => item.id === "MN0101")!.bounds, detail.buildings);
  await expect(page.getByRole("list", { name: "Properties", exact: true })).toBeVisible();
  await page.getByRole("checkbox", { name: "Underground drainage" }).check();
  await expect(page.getByText("Historic illustrative interceptors", { exact: true })).toBeVisible();
  await expect(page.locator("canvas")).toBeVisible();
  await page.getByRole("checkbox", { name: "Underground drainage" }).uncheck();
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  await clickRoof(neighborhoods.find(item => item.id === "MN0101")!.bounds, detail.buildings);
  await expect(page).toHaveURL(`/assessment?property=${tower.id}`);
  await expect(page.getByRole("heading", { name: "Property risk assessment", exact: true })).toBeVisible();
  expect(errors).toEqual([]);
});
