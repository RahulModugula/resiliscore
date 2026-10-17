import { chromium } from 'playwright';
import { writeFile } from 'node:fs/promises';
const browser = await chromium.launch({ headless: true, args: ['--use-angle=metal'] });
const results = [];
try {
 for (const [label, url] of [['before','http://127.0.0.1:3101'],['after','http://127.0.0.1:3103']]) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 1, reducedMotion: 'reduce' });
  const page = await context.newPage();
  await page.goto(`${url}/?neighborhood=MN0101&scenePerf=1`);
  await page.waitForFunction(() => window.__scenePerf?.frames > 0);
  await page.locator('[aria-busy="true"]').waitFor({ state: 'hidden' });
  await page.getByRole('checkbox', { name: 'Terrain relief', exact: true }).check();
  await page.mouse.move(10,10);
  await page.evaluate(() => window.__scenePerf.camera([-2500,850,8800], [-3534,150,7794]));
  await page.waitForTimeout(750);
  for (let run = 0; run < 5; run++) {
   await page.evaluate(async () => {
    const api = window.__scenePerf;
    api.reset();
    for (let frame = 0; frame < 30; frame++) {
     api.invalidate();
     await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    }
   });
   await page.waitForTimeout(150);
   results.push({ label, run, ...(await page.evaluate(() => ({ samples: [...window.__scenePerf.samples], snapshot: window.__scenePerf.snapshot(), backend: window.__scenePerf.backend }))) });
  }
  await context.close();
 }
} finally { await writeFile('/private/tmp/manhattan-perf-stationary.json', JSON.stringify(results,null,2)); await browser.close(); }
