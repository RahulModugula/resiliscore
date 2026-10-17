The interface between backend and frontend. `parcel_score_schema.json` is canonical, and
`backend/app/models/schemas.py` and `frontend/src/types/resiliscore.ts` mirror it. Change all of them together.

`validation_report_schema.json` and `frontend/src/types/validation.ts` are copied unchanged from
`origin/b/validation-report` at `17b29b2`. The offline validation report combines that branch's model card
with these existing result artifacts, without changing their section values:

- Wildfire: `origin/b/validate-wildfire` at `2420e0c`, `backend/validation/results/wildfire_summary.json`.
- Benchmarks: `origin/b/benchmark` at `38ad5d7`, `backend/validation/results/benchmarks.json`.

The report retains the backend model commit and records its assembly date. Flood remains null because
`origin/b/validate-flood` at `b17c9ce` uses an older summary format and does not publish the observed
confidence intervals required by the report contract. Do not substitute zero-width intervals or
combine fitted holdout values with full-sample observations. Refresh the report from the backend's
`scripts/build_validation_report.py` once those results are available in the shared format.
