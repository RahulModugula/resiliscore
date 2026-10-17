# ResiliScore

ResiliScore is a parcel-level property catastrophe resilience score on a 300–850 scale, with an underwriting copilot built around it.
It pairs public hazard data (OpenFEMA, USGS 3DEP, NOAA Atlas 15 and LANDFIRE) with verified parcel mitigations.
Bühlmann-Straub credibility then moves the census-tract prior toward the parcel's own risk.

| Path | What |
|---|---|
| `contracts/` | Canonical JSON schema + the 3 golden demo scenarios |
| `backend/` | FastAPI: ingestion, vision rings, actuarial engine, Guidewire mock, MCP server |
| `frontend/` | Next.js 15 underwriting cockpit |
| `docs/SPEC.md` | Full technical spec |
| `docs/DECISIONS.md` | Decisions that refine the spec |

## Run

```bash
cd backend && uv sync && uv run uvicorn app.main:app --reload --port 8000
cd frontend && npm ci && npm run dev
```

## Verification credit, rules and brokers

Hazard scoring for carriers is a crowded field. This layer covers what it leaves out: verification credit, homeowner ROI, grant navigation and distribution through agents.

- **Rules and grants registry** (`backend/app/rules/`): each entry has a jurisdiction, type, amount, effective date, source URL and the date the source was read. `verified: false` marks anything not confirmed (for example, the reported Louisiana SB 355). The Guidewire quote's `appliedRules` and the MCP answers cite these ids.
- **Evidence loop** (`POST /v1/verification/evidence`): a verified LIDAR, ELEVATION_CERT, IBHS_CERT, PHOTO_SELF_INSPECT or IOT channel adds its credibility weight, and `optimizer.simulate` rescores the parcel. The response is the parcel with an `evidence_log` entry (Z and score before and after). More evidence moves the score toward the parcel's own verified risk, so it can fall as well as rise: on the Altadena parcel an elevation certificate lifts Z from 0.62 to 0.91 and the score from 385 to 381.
- **Consortium prototype** (`GET /v1/consortium/credibility`): **synthetic**. Two made-up carriers pool verified-outcome cohorts, and the spread of k and Z across 200 simulated runs shrinks as pooled exposure grows. It shows the mechanism, not real carrier outcomes.
- **Broker MCP tools**: `what_if_mitigation` (score, premium, mandates, grants and cited rules for a set of upgrades) and `explain_score` (factor contributions when the model fills them, otherwise the peril split).

TODO: the evidence store is in memory behind the `EvidenceStore` interface and forgets everything on restart; persist it before using it for anything but a demo.

Market context (figures as read 2026-10-17, from the coordinator's research and not re-checked here): CA FAIR Plan 668,609 policies and $724B exposure (Dec 2025, CDI via the Assembly); FL Citizens 293,772 policies (2026-05-31, citizensfla.com).
