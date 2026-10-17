# Manhattan property assessment

`assessManhattanProperty` sends the selected building's coordinates, exterior footprint, Manhattan FIPS and available construction year to `POST /v1/parcel/score`. It validates the contract and property location before accepting the response. Requests time out after ten seconds and accept cancellation.

If the API is unavailable, the workspace opens an **offline model screening**. This uses cached output from the same Python actuarial engine, not a second frontend formula or a golden demo parcel. Two construction-era cache entries cover the engine's pre/post-2002 wind coefficient. Runtime replaces only identity, exact footprint, mapped year and provenance. No risk result varies with map height or ground elevation.

The cache uses the backend's national-default hazards, $350,000 default replacement value, missing elevation and zero private verification. The canonical engine selects its nearest available NRI reference tract as an explicit nonlocal stand-in. These assumptions do not measure Manhattan hazard exposure or rank nearby properties. The engine currently assigns a LiDAR credibility weight even when no elevation is measured; the UI and provenance disclose this inherited assumption. Missing flood elevation and freeboard stay null. No credit, quote, verification or binding action is enabled.

Regenerate using a Python environment with the backend dependencies:

```sh
python frontend/scripts/generate-manhattan-screening.py
python frontend/scripts/generate-manhattan-screening.py --check
```

The generator imports the canonical engine, national defaults and pipeline replacement-value default directly. It makes no HTTP calls and does not read golden responses as inputs. `--check` compares deterministic output exactly. The frontend unit suite also hashes every engine source and reference-rate input recorded in the cache, so a backend model change requires regeneration.

`saveManhattanAssessment(id, result)` writes a validated assessment handoff to session storage; `/assessment?property=id` loads it. Handoffs expire after six hours. Missing, corrupted or blocked storage produces a link back to property selection. `/assessment?demo=true` preserves the existing standalone golden-scenario underwriting workflows.
