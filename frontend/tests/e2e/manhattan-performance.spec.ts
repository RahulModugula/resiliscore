import { expect, test } from "@playwright/test";

test.use({ launchOptions: { args: ["--use-angle=metal"] } });

interface Perf {
  frames: number;
  snapshot(): { frames: number; geometries: { id: string; position?: number; color?: number; index?: number; bvh: boolean }[]; memory: { geometries: number } };
}

test("layers and relief retain GPU attributes, picking trees and zero idle renders", async ({ page }) => {
  test.setTimeout(60_000);
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/?neighborhood=MN0101&scenePerf=1");
  await expect(page.getByRole("list", { name: "Properties", exact: true })).toBeVisible();
  await page.waitForFunction(() => (window as typeof window & { __scenePerf?: Perf }).__scenePerf?.frames);
  const snapshot = () => page.evaluate(() => (window as typeof window & { __scenePerf: Perf }).__scenePerf.snapshot());
  const first = await snapshot();
  expect(first.geometries.filter(g => g.bvh)).toHaveLength(3);
  const identity = (value: typeof first) => value.geometries.map(g => [g.id, g.position, g.color, g.index, g.bvh]);
  for (let run = 0; run < 3; run++) {
    await page.getByRole("checkbox", { name: "Terrain relief", exact: true }).check();
    await page.getByRole("radio", { name: "3× relief", exact: true }).check();
    await page.getByRole("checkbox", { name: "Underground drainage", exact: true }).check();
    expect(identity(await snapshot())).toEqual(identity(first));
    await page.getByRole("radio", { name: "1× actual", exact: true }).check();
    await page.getByRole("checkbox", { name: "Underground drainage", exact: true }).uncheck();
    await page.getByRole("checkbox", { name: "Terrain relief", exact: true }).uncheck();
    expect(identity(await snapshot())).toEqual(identity(first));
  }
  // Move off the scene to remove hover highlights before counting idle draws.
  await page.mouse.move(10, 10);
  await page.waitForTimeout(750);
  const frames = (await snapshot()).frames;
  await page.waitForTimeout(750);
  expect((await snapshot()).frames).toBe(frames);
  expect(errors).toEqual([]);
});
