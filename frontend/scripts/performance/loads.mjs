import { chromium } from 'playwright';
import { writeFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
const browser = await chromium.launch({ headless: true, args: ['--use-angle=metal'] });
const output = [];
try {
 for (let run = 0; run < 5; run++) {
  for (const [label, base] of [['before', 'http://127.0.0.1:3101'], ['after', process.env.PERF_AFTER_URL ?? 'http://127.0.0.1:3103']]) {
   for (const id of ['', 'MN0101', 'MN1292']) {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 1, reducedMotion: 'reduce' });
    const page = await context.newPage();
    const errors = []; page.on('pageerror', e => errors.push(e.message));
    const start = performance.now();
    await page.goto(`${base}/?scenePerf=1${id ? `&neighborhood=${id}` : ''}`);
    await page.waitForFunction(() => window.__scenePerf?.frames > 0, { timeout: 90000 });
    await page.locator('[aria-busy="true"]').waitFor({ state: 'hidden', timeout: 90000 });
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    const ms = performance.now() - start;
    const backend = await page.evaluate(() => window.__scenePerf.backend);
    assert.deepEqual(errors, []);
    output.push({ run, label, id: id || 'island', ms, backend });
    console.log(run, label, id || 'island', ms.toFixed(1));
    await context.close();
   }
  }
 }
} finally {
 await writeFile('/private/tmp/manhattan-perf-loads.json', JSON.stringify({ browser: browser.version(), samples: output }, null, 2));
 await browser.close();
}
