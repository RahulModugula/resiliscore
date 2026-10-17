import { readFile, writeFile } from 'node:fs/promises';
const read = async path => JSON.parse(await readFile(path, 'utf8'));
const median = values => { const a = [...values].sort((a,b) => a-b); return a.length % 2 ? a[(a.length-1)/2] : (a[a.length/2-1]+a[a.length/2])/2; };
const stats = values => ({ median: median(values), min: Math.min(...values), max: Math.max(...values), samples: values.length });
const loads = await read('/private/tmp/manhattan-perf-loads.json');
const summary = { browser: loads.browser, loads: {}, toggles: {}, camera: {}, screenshots: await read('/private/tmp/manhattan-perf-diff/results.json') };
for (const label of ['before', 'after']) {
 summary.loads[label] = Object.fromEntries(['island','MN0101','MN1292'].map(id => [id, stats(loads.samples.filter(s => s.label === label && s.id === id).map(s => s.ms))]));
 const toggles = await read(`/private/tmp/manhattan-perf-${label}/results.json`);
 summary.backend = toggles.backend;
 summary.toggles[label] = Object.fromEntries(toggles.cases.map(c => [c.title, Object.fromEntries(['terrain-on','terrain-off','drainage-on','drainage-off'].map(name => [name, stats(c.toggles.filter(t => t.name === name).map(t => t.elapsedMs))]))]));
 const camera = await read(`/private/tmp/manhattan-perf-${label}/camera-results.json`);
 summary.camera[label] = Object.fromEntries(camera.cases.map(c => [c.title, {
  ...Object.fromEntries(['cpuMs','frameCpuMs','gpuMs'].map(key => [key, stats(c.movement.map(run => median(run.filter(s => s[key] !== null).map(s => s[key]))))])),
  calls: [...new Set(c.movement.flat().map(s => s.calls))].sort((a,b) => a-b),
 } ]));
}
const stationary = await read('/private/tmp/manhattan-perf-stationary.json');
summary.stationary = Object.fromEntries(['before', 'after'].map(label => [label,
 Object.fromEntries(['cpuMs', 'frameCpuMs', 'gpuMs'].map(key => [key, stats(stationary.filter(run => run.label === label).map(run => median(run.samples.filter(s => s[key] !== null).map(s => s[key]))))]))
]));
await writeFile('/private/tmp/manhattan-perf-summary.json', JSON.stringify(summary, null, 2));
console.log(JSON.stringify(summary, null, 2));
