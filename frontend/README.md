# ResiliScore frontend

Next.js 15 underwriting workspace for the three golden demo parcels. The default demo uses `../contracts/golden_scenarios.json` and needs no backend, map token, remote font, or runtime imagery service.

```sh
npm ci
npm run dev
```

Open http://localhost:3000. The `Live API` checkbox is off by default. Optionally copy `.env.example` to `.env.local` to change the backend address.

## Demo walkthrough

1. Coastal flood opens at 765, compared with a tract score of 430. Inspect the +4.2 ft freeboard diagram and generate a demo PolicyCenter receipt. The existing FORTIFIED roof credit is already included.
2. Wildfire remediation opens at 385. Select all three actions to reach 630, $19,500 net investment, and $2,140 annual savings. Generate a 60-day conditional receipt or reset the plan.
3. Verification guardrail opens at 815. Enable the satellite change alert to pause binding. Open the workbench, request smartphone verification, run the demo capture, and restore auto-bind. Alternatively, apply +35 bps structure loading to route to a conditional bind.
4. Regulatory audit shows all 12 California factors, supplied model declarations and dataset vintages. Download the JSON dossier or sample consumer notice.

The address search matches the three demo addresses and APNs. Map overlays use the contract's GeoJSON and support pan, zoom, layer toggles, and feature inspection. The California basemaps use locally cached aerial imagery with provenance in `public/imagery/sources.json`. Louisiana uses an illustrative basemap because the imagery request failed. Synthetic parcel polygons are not surveyed to the imagery.

## Live API

The UI posts to the following spec endpoints, validates responses against the canonical JSON Schema, and returns to local fixtures on a timeout, HTTP failure, network failure, or invalid payload. Abort signals and request keys prevent older responses from replacing a newly selected scenario or plan.

| Endpoint | Request fields |
| --- | --- |
| `/v1/parcel/score` | `scenario_id` |
| `/v1/parcel/simulate-mitigation` | `apn_uid`, `action_ids` |
| `/v1/hitl/verify-override` | `apn_uid`, `resolution`, `approved`, `verification_method`, `simulate` |

The backend is developed separately. These requests follow the spec; live integration must be checked against the backend implementation as it lands. Guidewire receipts and mobile inspections are simulations in both modes. QR links open `/inspect?apn=...`; a phone needs a reachable app hostname. Captures stay on their page and do not synchronize between devices.

Local mitigation projections add only unapplied action deltas from the contract. Existing verified actions cannot earn duplicate credits. No alternate score curve is introduced while `../docs/DECISIONS.md` D1 remains open. Structure loading assumes $250/sq ft for 240 sq ft, retains the golden score, adjusts loss cost and replacement value, and imposes conditional review.

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
