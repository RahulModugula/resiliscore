import sharp from 'sharp';
import { readdir, writeFile, mkdir } from 'node:fs/promises';
const beforeDir = process.env.PERF_BEFORE ?? '/private/tmp/manhattan-perf-before';
const afterDir = process.env.PERF_AFTER ?? '/private/tmp/manhattan-perf-after';
const output = process.env.PERF_DIFF ?? '/private/tmp/manhattan-perf-diff';
await mkdir(output, { recursive: true });
const results = [];
for (const name of (await readdir(beforeDir)).filter(name => name.endsWith('.png'))) {
 const a = await sharp(`${beforeDir}/${name}`).removeAlpha().raw().toBuffer({ resolveWithObject: true });
 const b = await sharp(`${afterDir}/${name}`).removeAlpha().raw().toBuffer({ resolveWithObject: true });
 if (JSON.stringify(a.info) !== JSON.stringify(b.info)) throw new Error(`Image sizes differ: ${name}`);
 let sum = 0, changed = 0, max = 0;
 const pixels = Buffer.alloc(a.data.length);
 for (let i = 0; i < a.data.length; i += 3) {
  let delta = 0;
  for (let c = 0; c < 3; c++) { const d = Math.abs(a.data[i+c] - b.data[i+c]); sum += d; delta = Math.max(delta, d); pixels[i+c] = Math.min(255, d * 10); }
  if (delta > 2) changed++;
  max = Math.max(max, delta);
 }
 results.push({ name, meanAbsoluteChannelError: sum / a.data.length, changedPixelsAbove2: changed, totalPixels: a.info.width * a.info.height, maxChannelError: max });
 await sharp(pixels, { raw: { width: a.info.width, height: a.info.height, channels: 3 } }).png().toFile(`${output}/${name}`);
}
await writeFile(`${output}/results.json`, JSON.stringify(results, null, 2));
console.log(JSON.stringify(results, null, 2));
