The existing Manhattan demo now retains its scene when terrain or drainage is toggled. The island terrain-on stall fell from a median 4,889 ms to 28 ms. Fresh-session island loading fell from 7.11 s to 3.89 s across five runs, a 45% reduction. All 44,935 buildings and the original footprint triangulation, heights, opacity, material passes, source data and camera controls remain in place.

The expensive work was repeated construction of geometry and SAH picking trees. A terrain-dependent React key remounted the entire scene. The replacement gives each interactive geometry a Drei `useBVH` tree using CENTER construction, keeps it across layer changes, and refits it after ground-height changes. Terrain mode updates the existing color attribute. Relief updates existing position and normal attributes using original elevations plus separate building-height/overlay offsets. Drainage retains its point/line buffers and switches visibility. Dynamic attributes use `DynamicDrawUsage`; replaced resources and trees are disposed. Parsed local assets are shared with the property block view, avoiding repeat downloads and JSON parsing when opening that view or revisiting tabs.

Demand rendering and the existing DPR cap of 1.5 remain. Selection, visibility and ground-scale changes invalidate the scene; Drei CameraControls handles camera invalidation. No React state is updated per frame. Diagnostics, frame sampling, GPU queries and polling mount only with `?scenePerf=1`.

Measurements used production Next.js builds, Chromium 156.0.8078.4, a 1440 × 1000 viewport, actual renderer DPR 1, and the same bundled geography. WebGL reported `ANGLE (Apple, ANGLE Metal Renderer: Apple M3 Pro, Unspecified Version)` for both versions. GPU queries used `EXT_disjoint_timer_query_webgl2`, with disjoint results discarded. No SwiftShader timings are presented. Fresh browser contexts isolate each application load; the browser/GPU shader caches may warm across runs. Final camera and load timing passes ran sequentially, without test or build workloads.

Load times cover navigation through the first instrumented render and ready property directory, followed by two animation-frame boundaries. Toggle latency covers checkbox activation through two animation-frame boundaries and includes React, geometry work, BVH work and submission. Values are milliseconds unless marked seconds. Brackets show the minimum and maximum of five runs.

| Fresh-session load | Before, seconds | After, seconds |
| --- | ---: | ---: |
| Full island | 7.11 [6.98, 7.27] | 3.89 [3.73, 3.90] |
| Financial District, MN0101 | 1.71 [1.63, 1.76] | 1.58 [1.48, 1.70] |
| Inwood Hill Park, MN1292 | 1.56 [1.55, 1.63] | 1.48 [1.39, 1.58] |

| Layer action | Before | After |
| --- | ---: | ---: |
| Island terrain on | 4,889 [4,783, 4,957] | 28 [23, 89] |
| Island terrain off | 4,833 [4,754, 4,856] | 29 [28, 29] |
| Financial terrain on | 267 [263, 301] | 31 [30, 40] |
| Financial terrain off | 259 [255, 266] | 31 [30, 31] |
| Inwood terrain on | 184 [183, 200] | 31 [29, 35] |
| Inwood terrain off | 176 [176, 181] | 31 [30, 31] |
| Island drainage on | 64 [29, 80] | 28 [28, 260] |
| Island drainage off | 19 [14, 24] | 28 [24, 29] |
| Financial drainage on | 33 [29, 43] | 31 [27, 31] |
| Financial drainage off | 26 [23, 32] | 29 [17, 32] |
| Inwood drainage on | 30 [22, 35] | 31 [30, 32] |
| Inwood drainage off | 27 [17, 29] | 31 [30, 34] |

Drainage latency remains variable, including one 260 ms optimized sample. There is no consistent drainage speedup across neighborhoods. Retention removes repeated allocation and preserves resources between toggles.

Draw calls at the original camera were unchanged in both versions:

| View | Opaque | Terrain | Terrain + drainage |
| --- | ---: | ---: | ---: |
| Island | 41 | 42 | 46 |
| Financial District | 4 | 5 | 9 |
| Inwood | 4 | 5 | 9 |

The original implementation already batches buildings in one indexed mesh and drains in a single points draw. The 2,843-to-7 reference describes a different scene. This change preserves the existing transparent triangle order and two-sided passes.

Camera measurements below are medians of the per-frame medians from five repeated drag runs. Renderer CPU measures `renderer.render`; frame CPU starts before CameraControls' frame update and ends after rendering. This includes all scene frame callbacks and renderer sorting. There is no separate building sorting pass outside the renderer. Browser input dispatch, compositing and initial geometry preparation are outside that CPU interval; toggle latency above includes geometry preparation. Replayed input throughput is not display FPS. The fixed camera definitions and pointer paths are recorded in `scripts/performance/manhattan.mjs`.

| Camera movement | Renderer CPU before → after | Frame CPU before → after | GPU before → after |
| --- | --- | --- | --- |
| Island | 0.50 [0.40, 0.70] → 0.80 [0.50, 0.80] | 0.60 [0.50, 0.80] → 1.00 [0.60, 1.00] | 7.83 [6.65, 8.77] → 8.12 [7.87, 8.71] |
| Financial District | 0.40 [0.30, 0.40] → 0.40 [0.40, 0.50] | 0.50 [0.40, 0.60] → 0.50 [0.50, 0.60] | 1.62 [1.32, 2.11] → 2.26 [1.88, 2.58] |
| Inwood | 0.40 [0.40, 0.60] → 0.40 [0.30, 0.60] | 0.60 [0.50, 0.70] → 0.50 [0.50, 0.65] | 0.71 [0.69, 1.49] → 0.73 [0.70, 0.78] |

No camera or GPU speedup is claimed. Some optimized medians were higher. Pointer-driven camera damping and hover changes can alter the rendered trajectory; GPU timings also vary with driver scheduling and system load. An additional identical-viewpoint Financial District check used five runs of 30 forced frames per build, without pointer input. Renderer CPU was 0.40 [0.30, 0.40] → 0.45 [0.40, 0.50] ms; frame CPU was 0.50 [0.40, 0.50] → 0.50 [0.45, 0.60] ms; GPU was 1.13 [0.99, 1.18] → 1.36 [1.25, 1.73] ms, with five calls throughout. This confirms that stall elimination did not produce a steady-render GPU improvement. The small higher GPU cost remains a measured limitation.

Validation retained the unoptimized source at commit `9bce2c7dd47271a71c532a2f41cf173fb4b4619c`, extracted to `/private/tmp/manhattan-performance-baseline` before editing. Its only render instrumentation is the included `baseline-instrumentation.patch` and the shared `SceneDiagnostics.tsx`. The optimized work is on `f/manhattan-render-performance`. No contract, simulation fixture, geographic asset, Next configuration, build script or export handler changed.

The final lint, production build and 63 unit tests pass. The full browser suite passes 46 tests; one real-backend test is skipped because it requires a running backend. Browser checks cover real roof picking, transparent layers, orbit/zoom, island/neighborhood navigation, relief 1×/3×, terrain/drainage controls, mobile and WebGL fallback, scenario workflows, export, themes, and reopening the block without asset requests. New browser checks verify stable geometry/attribute identities, retained picking trees and zero renders during a stationary 750 ms window after controls settled. Unit checks compare updated terrain, buildings, parks and borders against freshly generated reference geometry, including unchanged physical building heights and valid picking after BVH refits.

Fifteen matched image pairs cover the three default views, terrain, drainage, and two alternate cameras per view, including close overlapping transparent buildings. Eleven pairs are pixel-identical, including all six alternate cameras. The other four differ in only two or six pixels above a channel tolerance of 2, out of 1,044,120 pixels per image. The evidence archive contains originals and difference statistics. The few outline pixels in early toggle captures preceded the final correction to update border lift directly; the final default and alternate captures match exactly.

Remaining costs include the 27 MB overview JSON, footprint triangulation, initial terrain clipping, tree construction and first-use shader/driver work. Initial island loading still takes several seconds. Retaining original elevations and parsed assets uses additional memory; the building ground/offset arrays occupy about 18.3 MiB in the full-island scene. This pass does not add missing playback, drain picking, plan-view or building-toggle features. Direct `tsc --noEmit` also reports existing fixture typing errors in `evidence-status.spec.ts` and `nyc.spec.ts`, reproduced against the baseline; the required Next build passes.

Reproduce from `frontend/` after starting the baseline on port 3101 and optimized production build on 3103:

```sh
PERF_URL=http://127.0.0.1:3101 node scripts/performance/manhattan.mjs
PERF_URL=http://127.0.0.1:3103 PERF_OUT=/private/tmp/manhattan-perf-after node scripts/performance/manhattan.mjs --check-reuse
node scripts/performance/loads.mjs
node scripts/performance/stationary.mjs
node scripts/performance/compare.mjs
node scripts/performance/summarize.mjs
```

To reconstruct the baseline, extract `git archive 9bce2c7 frontend contracts` into a separate directory, apply `baseline-instrumentation.patch` with `git apply`, copy `SceneDiagnostics.tsx` into its matching component directory, install its locked dependencies and build it. `--camera-only --no-screenshots` repeats camera timings without recapturing images. The source-level CPU probe is `node --import tsx scripts/performance/geometry.ts`.

[Full measurement summary](manhattan-summary.json) and [screenshots plus raw samples](manhattan-evidence.zip) are preserved with this report.
