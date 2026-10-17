import { chromium } from 'playwright';
import { mkdir, writeFile } from 'node:fs/promises';
import assert from 'node:assert/strict';

const base = process.env.PERF_URL ?? 'http://127.0.0.1:3101';
const output = process.env.PERF_OUT ?? '/private/tmp/manhattan-perf-before';
const capture = !process.argv.includes("--no-screenshots");
const cameraOnly = process.argv.includes("--camera-only");
const checkReuse = process.argv.includes('--check-reuse');
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true, args: ['--use-angle=metal'] });
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 1, reducedMotion: 'reduce' });
const page = await context.newPage();
const errors = [];
page.on('pageerror', e => errors.push(e.message));
const results = { browser: browser.version(), viewport: [1440, 1000], deviceScaleFactor: 1, backend: '', cases: [], errors };
async function idle() {
  let previous = -1, settled = false;
  for (let attempt = 0; attempt < 30; attempt++) {
    await page.waitForTimeout(250);
    const frames = await page.evaluate(() => window.__scenePerf.frames);
    if (frames === previous) { settled = true; break; }
    previous = frames;
  }
  assert.ok(settled, 'controls did not settle');
  const first = await page.evaluate(() => window.__scenePerf.frames);
  await page.waitForTimeout(500);
  assert.equal(await page.evaluate(() => window.__scenePerf.frames), first, 'idle scene rendered');
}
async function action(name, label, checked) {
  return page.evaluate(async ({ name, label, checked }) => {
    const api = window.__scenePerf;
    api.reset();
    const before = api.snapshot();
    const input = [...document.querySelectorAll('input')].find(el => el.closest('label')?.textContent?.trim() === label);
    if (!input) throw new Error(`Missing input: ${label}`);
    const start = performance.now();
    if (input.checked !== checked) input.click();
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    return { name, elapsedMs: performance.now() - start, before, after: api.snapshot(), samples: [...api.samples] };
  }, { name, label, checked });
}
try {
  for (const [id, title] of [['', 'island'], ['MN0101', 'financial'], ['MN1292', 'inwood']]) {
    const start = performance.now();
    await page.goto(`${base}/?scenePerf=1${id ? `&neighborhood=${id}` : ''}`);
    await page.waitForFunction(() => window.__scenePerf?.frames > 0, { timeout: 90000 });
    await page.locator('[aria-busy="true"]').waitFor({ state: 'hidden', timeout: 90000 });
    const loadMs = performance.now() - start;
    await idle();
    results.backend = await page.evaluate(() => ({ renderer: window.__scenePerf.backend, vendor: window.__scenePerf.vendor, gpuTimer: window.__scenePerf.gpuTimer }));
    const item = { title, loadMs, initial: await page.evaluate(() => window.__scenePerf.snapshot()), toggles: [], movement: [] };
    if (capture) await page.locator('canvas').screenshot({ path: `${output}/${title}-default.png` });
    // Use native pointer outside the map so no building hover contaminates screenshots.
    await page.mouse.move(10, 10);
    for (let run = 0; run < (cameraOnly ? 0 : 5); run++) {
      for (const [name, label, checked] of [['terrain-on', 'Terrain relief', true], ['drainage-on', 'Underground drainage', true], ['drainage-off', 'Underground drainage', false], ['terrain-off', 'Terrain relief', false]]) {
        const result = await action(name, label, checked);
        item.toggles.push({ run, ...result });
        if (checkReuse && name === 'terrain-on') {
          assert.deepEqual(result.after.geometries.map(g => [g.id, g.position, g.color, g.index]), result.before.geometries.map(g => [g.id, g.position, g.color, g.index]), 'terrain toggle replaced scene geometry');
        }
        if (capture && run === 0 && checked) await page.locator('canvas').screenshot({ path: `${output}/${title}-${name}.png` });
      }
    }
    // Matched alternate angles with overlapping transparent buildings.
    await action('terrain-on', 'Terrain relief', true);
    // Keep all cameras deterministic across baseline and optimized builds.
    const cameras = title === 'island'
      ? [[[18000, 12000, 9000], [0, 100, 0]], [[-13000, 5000, -11000], [0, 100, 0]]]
      : title === 'financial'
        ? [[[-2500, 850, 8800], [-3534, 150, 7794]], [[-4500, 650, 8500], [-3534, 150, 7794]]]
        : [[[5600, 700, -9000], [4649, 40, -9952]], [[3700, 700, -9300], [4649, 40, -9952]]];
    for (let i = 0; i < cameras.length; i++) {
      await page.evaluate(([position, target]) => window.__scenePerf.camera(position, target), cameras[i]);
      await idle();
      if (capture) await page.locator('canvas').screenshot({ path: `${output}/${title}-angle-${i}.png` });
    }
    for (let run = 0; run < 5; run++) {
      await page.evaluate(() => window.__scenePerf.reset());
      const box = await page.locator('canvas').boundingBox();
      await page.mouse.move(box.x + box.width * .5, box.y + box.height * .6);
      await page.mouse.down();
      for (let step = 1; step <= 20; step++) await page.mouse.move(box.x + box.width * .5 + step * 3, box.y + box.height * .6 + step, { steps: 1 });
      await page.mouse.up();
      await idle();
      item.movement.push(await page.evaluate(() => [...window.__scenePerf.samples]));
    }
    results.cases.push(item);
    console.log(title, 'load ms', item.loadMs.toFixed(1), 'toggles', item.toggles.map(t => `${t.name}:${t.elapsedMs.toFixed(1)}`).join(' '));
  }
  assert.deepEqual(errors, []);
} finally {
  await writeFile(`${output}/${cameraOnly ? "camera-results" : "results"}.json`, JSON.stringify(results, null, 2));
  await browser.close();
}
