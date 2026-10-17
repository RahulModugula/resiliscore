# ResiliScore frontend

Next.js 15 Manhattan property explorer and underwriting workspace. The map uses locally bundled NYC geometry and needs no backend, map token, remote font, or runtime imagery service. The golden underwriting demo remains available at `/assessment?demo=true`.

```sh
npm ci
npm run dev
```

Open http://localhost:3000. Optionally copy `.env.example` to `.env.local` to change the backend address.

## Manhattan walkthrough

1. Click a neighborhood boundary or choose a neighborhood from the searchable directory. The camera focuses that area, isolates it from the rest of Manhattan, and loads its detailed footprints, parks, and measured ground terrain.
   **Terrain relief** fades buildings to reveal the measured USGS 3DEP ground surface. **1× actual** retains real ground elevations; **3× relief** explicitly exaggerates ground heights for inspection. This viewing scale does not change building heights or assessment inputs.
   On a phone, open **Map layers** to change terrain or drainage settings, then close it to inspect the map. The closed control keeps the active layers and ground scale visible.
2. Toggle **Underground drainage** to make buildings and ground transparent. Cyan points are NYC DEP storm drains. Amber lines are historical Open Sewer Atlas interceptors and force mains. These lines are partial and unofficial; their depths are unknown and the vertical offset is schematic. Connections between drains and pipes are not inferred.
3. Properties use sourced street addresses where available. Click a building or choose it from the property directory. Its assessment opens with a 3D block view showing the selected footprint, neighboring buildings, adjoining streets, and measured elevation. Ground elevation is shown separately from building height. The app requests the actual parcel risk API with its NYC coordinates, footprint, and known construction year. If the API is unavailable, it opens clearly labeled, cached screening from the canonical risk engine using national defaults and a nonlocal NRI reference tract. This screening does not rank geographic risk and supplies no quote or binding authority.
4. **Back to Manhattan map** returns to the selected neighborhood. **Island view** resets the camera and directory. The same directory supports keyboard use and remains available without WebGL.

Assessment handoff uses session storage, with a six-hour expiry. Reloading within that session preserves the assessment. A missing or expired assessment links back to the map. See `public/manhattan/README.md` for geographic source coverage and `MANHATTAN_ASSESSMENT.md` for offline model provenance.

## Demo walkthrough

Open `/assessment?demo=true` or choose **Open demo workspace**. Its `Live API` checkbox is off by default. Scores and action savings follow the current shared golden contract.

1. Coastal flood compares parcel and tract risk. Inspect the freeboard diagram and generate a demo PolicyCenter receipt. The existing FORTIFIED roof credit is already included.
2. Wildfire remediation lets you select unapplied actions, inspect investment and annual savings, generate a simulated receipt when eligible, and reset the plan.
3. Verification guardrail pauses binding when the satellite change alert is enabled. Open the workbench, request smartphone verification, run the demo capture, and restore auto-bind. Alternatively, apply +35 bps structure loading to route to a conditional bind.
4. Regulatory audit shows all 12 California factors, supplied model declarations and dataset vintages. Download the JSON dossier or sample consumer notice.
5. Model Validation shows the backend report, including real flood uncertainty, wildfire holdouts, event/cohort backtests, benchmark measurements, and verbatim adoption decisions. It is also available when assessing a selected Manhattan property.

The address search matches the three demo addresses and APNs. Map overlays use the contract's GeoJSON and support pan, zoom, layer toggles, and feature inspection. The California basemaps use locally cached aerial imagery with provenance in `public/imagery/sources.json`. Louisiana uses an illustrative basemap because the imagery request failed. Synthetic parcel polygons are not surveyed to the imagery.

## Live API

The UI posts to the following spec endpoints, validates responses against the canonical JSON Schema, and returns to local fixtures on a timeout, HTTP failure, network failure, or invalid payload. Abort signals and request keys prevent older responses from replacing a newly selected scenario or plan.

| Endpoint | Request fields |
| --- | --- |
| `/v1/parcel/score` | `scenario_id` |
| `/v1/parcel/simulate-mitigation` | `apn_uid`, `action_ids` |
| `/v1/hitl/verify-override` | `apn_uid`, `resolution`, `approved`, `verification_method`, `simulate` |

The backend is developed separately. These requests follow the spec; live integration must be checked against the backend implementation as it lands. Guidewire receipts and mobile inspections are simulations in both modes. QR links open `/inspect?apn=...`; a phone needs a reachable app hostname. Captures stay on their page and do not synchronize between devices.

Offline mitigation projections read `golden_simulations.json`, generated by the backend engine, as required by `../docs/DECISIONS.md` D2. Combined scores, premiums, and net capital are not sums of independent action rows. Baseline uncertainty, premium-build details, and attribution are cleared on projections because those details are absent from the summary table. The existing demo peril allocation is retained and rescaled to the projected total; it is not a newly fitted allocation. Structure loading assumes $250/sq ft for 240 sq ft, retains the golden score, adjusts loss cost and replacement value, and imposes conditional review.

Audit declarations are supplied payload values. The UI does not invent individual channel precision weights, live derivatives, BISG results, or regulatory approval.

## Validation

```sh
npm run lint && npm run build
npm test
npx playwright install chromium
npm run test:e2e
```

Playwright starts the frontend on port 3100 and exercises offline demo journeys, API failures, contract validation, and stale-response handling. Set `PLAYWRIGHT_BASE_URL` to use an existing frontend server.

Frontend Codex guidance lives in `AGENTS.md`. Shared contracts and backend files are outside this work's ownership boundary.

## Model validation tab

The Model Validation tab bundles `../contracts/validation_report.json` directly through `src/data/validationReport.ts`. All metrics, ratios, confidence intervals, verdicts, and adoption notes come from that report. The roof headline is calculated from its odds ratio, so it changes with the evidence. The holdout selector identifies the fire being compared; each fire is scored out of sample. The header latency is the maximum p95 across the reported benchmark rows, with its aggregation labeled.

With Live API enabled, the tab requests `GET /v1/model/validation`, checks the response against `validation_report_schema.json`, and retains the bundled report on invalid responses, HTTP errors, or timeouts. Returning to offline mode discards the live response. Null sections display results pending. The bundled flood section includes real observations, per-bucket confidence intervals, fitted predictions, hurricane and basement-cohort rows, and the backend adoption note.

Charts include source, vintage, and fetch date. Caveat icons support hover, keyboard focus, and Escape. Narrow screens scroll within charts and tables. Download report exports exactly the active report. `tests/e2e/validation.spec.ts` covers these flows; its flood fixture is synthetic test data and is never bundled into the application.

To exercise the running backend in the browser suite, build with `NEXT_PUBLIC_API_BASE_URL` set to its origin, then run Playwright with `VALIDATION_API_URL` set to that same origin. The integration test compares the HTTP response and downloaded live report with the committed JSON.
