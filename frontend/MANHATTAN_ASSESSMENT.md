# Manhattan property assessment

`assessManhattanProperty` sends the selected building's coordinates, exterior footprint, Manhattan FIPS and available construction year to `POST /v1/parcel/score`. It validates the contract and property location before accepting the response. Requests time out after ten seconds and accept cancellation.

If the API is unavailable, the workspace opens an **offline model screening**. This uses cached output from the same Python actuarial engine, not a second frontend formula or a golden demo parcel. Two construction-era cache entries cover the engine's pre/post-2002 wind coefficient. Runtime replaces only identity, exact footprint, mapped year and provenance. No risk result varies with map height or ground elevation.

The cache uses the backend's national-default hazards, $350,000 default replacement value, missing elevation and zero private verification. The canonical engine selects its nearest available NRI reference tract as an explicit nonlocal stand-in. These assumptions do not measure Manhattan hazard exposure or rank nearby properties. The engine currently assigns a LiDAR credibility weight even when no elevation is measured; the UI and provenance disclose this inherited assumption. Missing flood elevation and freeboard stay null. The recorded assessment has no credit, quote, verification or binding authority. The optional building demo described below keeps its simulated state separate.

Regenerate using a Python environment with the backend dependencies:

```sh
python frontend/scripts/generate-manhattan-screening.py
python frontend/scripts/generate-manhattan-screening.py --check
```

The generator imports the canonical engine, national defaults and pipeline replacement-value default directly. It makes no HTTP calls and does not read golden responses as inputs. `--check` compares deterministic output exactly. The frontend unit suite also hashes every engine source and reference-rate input recorded in the cache, so a backend model change requires regeneration.

`saveManhattanAssessment(id, result)` writes a validated assessment handoff to session storage; `/assessment?property=id` loads it. Handoffs expire after six hours. Missing, corrupted or blocked storage produces a link back to property selection. `/assessment?demo=true` preserves the existing standalone golden-scenario underwriting workflows.


## Underwriting demo on a selected building

Select a real building on the Manhattan map and choose **Open underwriting demo** in its assessment header. The same 3D block and selected-building marker stay visible. The demo compares the canonical engine's baseline with an assumed Class 4 impact-resistant roof, then walks through simulated capture, human review and a building-specific demo receipt. Changing the retrofit revokes review; reset clears the plan and review. Return to assessment restores the recorded risk view. Its session handoff and JSON export are unchanged.

These scenarios use the canonical NY national-default screening inputs, a nonlocal NRI reference and $350,000 assumed replacement value, even when the recorded assessment came from the live API. No California or Louisiana golden parcel is substituted. Real building identity, construction era and footprint stay attached to the scenario. This initial cache covers the roof action supported by the default NY screen; it does not infer flood hazards or eligibility for grants from the map. Modeled premium comes from the engine's indicated-premium calculation, not a filed New York quote.

`generate-building-demo.py` computes all eight era/roof/review combinations through `optimizer.simulate`, using `screening.json` as its input. Its hash guard and frontend tests require regeneration if the engine or screening inputs change. UI code reads complete cached model outputs rather than adding individual credits. Regenerate/check using a Python 3.11+ environment with the backend dependencies:

```sh
python frontend/scripts/generate-building-demo.py
python frontend/scripts/generate-building-demo.py --check
```

Demo review assumes CV confidence 0.99 after simulated capture and approval. It does not access sensors or establish an inspection, elevation certificate, registry lookup or completed work. The receipt has `demo: true`, `no_policy_issued: true`, a real building id/footprint, explicit assumptions, and null policy/quote fields. It creates no external workflow. Live mitigation and verification endpoints currently resolve only golden APNs, so this first building demo runs offline and never submits a synthetic building APN to those endpoints.
