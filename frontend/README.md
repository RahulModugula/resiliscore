# SaveMyHome frontend

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
4. **Try building demo** in the map header starts the real-building underwriting flow. Choose a neighborhood and a building to open its controls directly, without waiting for the risk API. The `/?workflow=demo` URL keeps this mode active across neighborhood selection, reload and return from a building. **Exit building demo** restores normal assessments. **Open underwriting demo** in a selected building assessment also tests a hypothetical impact-resistant roof, simulated capture/review and a downloadable demo binding receipt. The real 3D block stays visible. Scenarios use explicit default hazards and an assumed $350,000 valuation, and do not change the recorded assessment. Changing the roof requires fresh demo review. **Return to assessment** closes the scenario. No quote, actual verification or policy is established.
5. **Back to Manhattan map** returns to the selected neighborhood. **Island view** resets the camera and directory. The same directory supports keyboard use and remains available without WebGL.

Assessment handoff uses session storage, with a six-hour expiry. Reloading within that session preserves the assessment. A missing or expired assessment links back to the map. See `public/manhattan/README.md` for geographic source coverage and `MANHATTAN_ASSESSMENT.md` for offline model provenance.

## Demo walkthrough

Open `/assessment?demo=true` or choose **Sample scenarios** in the map directory. Offline demo data comes from `golden_scenarios.json` and `golden_simulations.json`.

1. Coastal flood compares the supplied parcel score with the tract score. Inspect the freeboard diagram and generate a demo PolicyCenter receipt. Existing verified improvements cannot earn another credit.
2. Wildfire remediation lets you select actions, compare the combined score and premium, generate a conditional receipt, or reset the plan.
3. Verification guardrail lets you enable the satellite change alert, run the demo smartphone capture, and restore eligibility. Alternatively, apply the demo structure loading for a conditional bind.
4. NYC Red Hook, Hollis, and Rockaway select `NYC_RED_HOOK`, `NYC_HOLLIS`, and `NYC_ROCKAWAY`. Their addresses are 5 Luquer St in Brooklyn, 81-52 192 St in Queens, and 74-02 Beach Channel Dr in Queens. The pills load their canonical shared golden payloads and complete action-subset tables without a backend. Live API can request the same scenario IDs.
5. NYC Lot appears only when the response has a `nyc` block. Missing values say “No data”; reported zero counts say “None reported”. Nearby 311 reports use a 500 m radius and five-year window; catch basins use 150 m. FloodNet depth is in inches and ground elevation is in feet. PLUVIAL and SEWER_BACKUP appear as “Street/rain flooding” and “Sewer backup” in the peril breakdown.
6. Model Validation shows the backend report, including flood uncertainty, wildfire holdouts, event/cohort backtests, benchmark measurements, and verbatim adoption decisions. It is also available for a selected Manhattan property.
7. Regulatory audit shows supplied model declarations and dataset vintages. Download the JSON dossier or sample consumer notice.

Search matches demo titles, addresses, boroughs, and APNs. Select a demo match to retain its golden mitigation controls. Submit an address with Enter or the “Look up” button to enable Live API and request `{address}`. Address lookups show supplied mitigation rows without simulation checkboxes or plan totals. A failed lookup shows an error and retry control without presenting another parcel as the requested address.

Map overlays use the contract's GeoJSON and support pan, zoom, layer toggles, and feature inspection. California basemaps use locally cached aerial imagery with provenance in `public/imagery/sources.json`. Other parcels use an illustrative basemap. Synthetic parcel polygons are not surveyed to imagery.

## Live API

The UI posts to the following spec endpoints, validates responses against the canonical JSON Schema, and falls back to the selected golden fixture on a timeout, HTTP failure, network failure, or invalid payload. Live addresses have no offline fallback. Abort signals and request keys prevent older responses from replacing a newly selected scenario or plan.

| Endpoint | Request fields |
| --- | --- |
| `/v1/parcel/score` | `scenario_id` or `address` |
| `/v1/parcel/simulate-mitigation` | `apn_uid`, `action_ids` |
| `/v1/hitl/verify-override` | `apn_uid`, `resolution`, `approved`, `verification_method`, `simulate` |

The backend is developed separately. These requests follow the spec; live integration must be checked against the backend implementation as it lands. Guidewire receipts and mobile inspections are simulations in both modes. QR links open `/inspect?apn=...`; a phone needs a reachable app hostname. Captures stay on their page and do not synchronize between devices.

Offline mitigation projections read complete action-subset summaries from `golden_simulations.json`, keyed by sorted action IDs joined with `+`. Score, credibility, loss, premium, and net investment use those combined results rather than summed action deltas. Incremental savings compare the baseline premium with the projected premium. Baseline uncertainty, premium-build details, and attribution are cleared on projections because these details are absent from the summary table. Offline peril amounts retain the baseline allocation, scaled to projected total loss, and are labeled accordingly. Unknown action IDs are ignored and duplicate selections count once. Structure loading keeps the existing demo assumptions of $250/sq ft for 240 sq ft and a conditional review.

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
