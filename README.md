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
