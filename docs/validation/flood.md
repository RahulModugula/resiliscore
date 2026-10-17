# Flood model validation against NFIP claims

Status: partial. The severity backtest, the held-out fit and the event table are done. The tract ranking test is in
the last section. Everything below was computed on 2026-10-17. The engine under test is model v2 (PR #18); no file
under `app/` was changed.

## Verdict

**Keep Hazus 129. Do not adopt the fitted curve.** On the held-out New York, New Jersey and Hurricane Ida claims
the fitted curve has a lower MAE than Hazus (0.220 vs 0.247), but the 95% bootstrap interval on the difference runs
from -0.047 to +0.069, so it includes zero, and the adopt rule needs it to be entirely below zero.

The more useful finding is a warning about the data rather than the curve. Hazus 129 under-predicts the observed
damage ratio in every event, by 0.11 to 0.45 in absolute damage ratio (the mean observed ratio is 0.25 to 0.64; the
Hazus prediction is 0.14 to 0.22). It is close to unbiased only between 3 and 6 ft. Most of the gap sits at recorded
depths under 6 inches, which is 86% of the claims, and the depth field has clear quality problems (below). So
"Hazus is too low at shallow depth" is what the numbers say, but they do not prove it.

## Data

| Item | Value |
|---|---|
| Dataset | OpenFEMA NfipClaims v3, https://www.fema.gov/api/open/v3/NfipClaims (2,725,989 records, last refreshed 2026-09-09) |
| Fetched | 2026-10-17 |
| Field names | Read from `OpenFemaDataSetFields` the same day. `waterDepth` is "depth of flood water in inches" (the reference level is not stated; "there are instances where measurements were provided in feet"). `buildingDamageAmount` and `buildingPropertyValue` are actual cash value in dollars. `latitude` and `longitude` are rounded to one decimal. |
| Filter | Single-family (`occupancyType` 1 or 11), `numberOfFloorsInTheInsuredBuilding` 1, `basementEnclosureCrawlspaceType` 0, `waterDepth` 0 to 240 in, `buildingPropertyValue` at least $20,000 (drops placeholder values such as $100), `buildingDamageAmount` at least 0, `yearOfLoss` 2005 or later |
| States | LA, TX, FL, NJ, NY, MS, NC, SC (MS, NC and SC are added for Katrina, Florence and Helene) |
| n | 97,480 no-basement claims for the severity tables; 191,525 rows fetched in all, including basement claims (`basementEnclosureCrawlspaceType` 1 or 2) |
| Method | Observed damage ratio = `buildingDamageAmount` / `buildingPropertyValue`, capped at 1. Depth in ft = `waterDepth` / 12, taken as depth above the first floor. Every matching row was fetched (paged with `$skip`), so there is no sampling. |

The curves are read from the engine: Hazus DmgFnId 129 (USACE-IWR RES1, one story, no basement) through
`compound_model.ddf`, and the FIA A-zone curve (DmgFnId 105) from the constants registry. Both give a damage
fraction by depth above the first floor.

## Severity backtest, all 97,480 claims

Mean observed against mean predicted per depth bucket. Bias is predicted minus observed, so negative means the
curve is too low. MAE is the mean absolute error per claim.

| Depth (ft) | n | Observed | Hazus 129 | bias | MAE | FIA 105 | bias | MAE |
|---|---|---|---|---|---|---|---|---|
| 0-0.5 | 83,773 | 0.348 | 0.140 | -0.208 | 0.261 | 0.184 | -0.164 | 0.247 |
| 0.5-1 | 4,529 | 0.484 | 0.196 | -0.288 | 0.346 | 0.206 | -0.277 | 0.342 |
| 1-2 | 3,642 | 0.410 | 0.257 | -0.153 | 0.235 | 0.229 | -0.181 | 0.248 |
| 2-3 | 1,562 | 0.440 | 0.348 | -0.092 | 0.203 | 0.260 | -0.179 | 0.247 |
| 3-4 | 931 | 0.473 | 0.423 | -0.050 | 0.206 | 0.287 | -0.186 | 0.266 |
| 4-6 | 935 | 0.528 | 0.509 | -0.019 | 0.232 | 0.315 | -0.213 | 0.308 |
| 6-8 | 290 | 0.503 | 0.614 | +0.111 | 0.298 | 0.415 | -0.087 | 0.302 |
| 8+ | 1,818 | 0.297 | 0.682 | +0.386 | 0.418 | 0.436 | +0.139 | 0.251 |
| All | 97,480 | 0.360 | 0.168 | -0.192 | 0.265 | 0.196 | -0.165 | 0.252 |

Hazus is close to unbiased from 3 to 6 ft and over-predicts above 6 ft. It under-predicts below 3 ft. FIA 105 is
lower still in the middle depths, so it does worse there.

### Depth data quality

| Check | Value |
|---|---|
| Claims with `waterDepth` of exactly 0 in | 25.0% |
| Claims with `waterDepth` of 5 in or less | 85.9% |
| Claims with `waterDepth` of 12 in or more | 9.4% |
| Count at exact multiples of 12 in (12 to 120) over the count at their neighbours | 4.2 times |

A quarter of the claims record zero depth yet have a mean damage ratio of about a third, and values heap on whole
feet. That fits depths entered in feet, depths measured against the ground rather than the first floor, or missing
depths entered as 0. `interiorWaterDepth` and `exteriorWaterDepth` exist, measured against the lowest adjacent grade,
and are filled for 71,677 and 82,742 of 109,952 matching claims nationally (about half of the interior values are 0
inches); I did not use them. Treat the shallow-depth rows as the least reliable.

## Held-out fit (phase 2)

**Split, by region and event, never by random rows.** Holdout = New York and New Jersey (all years) plus Hurricane
Ida (any state): n = 5,620. Train = everything else (LA, TX, FL, MS, NC, SC, excluding Ida): n = 91,860.

**Fit.** A monotone non-decreasing (isotonic, pool-adjacent-violators) fit of damage ratio on depth in feet, on
train, evaluated on a 0.5 ft grid from 0 to 16 ft. Basement and floors are not covariates in the fit: the fetch kept
one-floor, no-basement claims only, so the curve is for that building type. Basement claims are shown separately
below.

| Depth (ft) | n | Observed | Hazus 129 | bias | MAE | FIA 105 MAE | Fitted | bias | MAE |
|---|---|---|---|---|---|---|---|---|---|
| 0-0.5 | 4,331 | 0.344 | 0.140 | -0.204 | 0.254 | 0.241 | 0.303 | -0.040 | 0.215 |
| 0.5-1 | 82 | 0.230 | 0.194 | -0.037 | 0.178 | 0.182 | 0.465 | +0.234 | 0.308 |
| 1-2 | 691 | 0.350 | 0.237 | -0.113 | 0.223 | 0.224 | 0.465 | +0.115 | 0.244 |
| 2-3 | 166 | 0.367 | 0.348 | -0.019 | 0.203 | 0.207 | 0.465 | +0.098 | 0.223 |
| 3-4 | 160 | 0.434 | 0.422 | -0.012 | 0.203 | 0.236 | 0.465 | +0.031 | 0.207 |
| 4-6 | 121 | 0.490 | 0.504 | +0.014 | 0.219 | 0.259 | 0.465 | -0.025 | 0.217 |
| 6-8 | 23 | 0.412 | 0.606 | +0.194 | 0.289 | 0.208 | 0.465 | +0.053 | 0.219 |
| 8+ | 46 | 0.402 | 0.688 | +0.285 | 0.365 | 0.259 | 0.526 | +0.124 | 0.286 |
| All | 5,620 | 0.350 | 0.181 | -0.169 | 0.247 | 0.237 | 0.341 | -0.009 | 0.220 |

| Holdout MAE | Value |
|---|---|
| Hazus 129 | 0.2466 |
| FIA 105 | 0.2373 |
| Fitted | 0.2204 |
| Fitted minus Hazus, paired per claim | -0.0262 |
| 95% interval, bootstrap resampling whole events (2,000 resamples) | -0.0474 to +0.0692 |

**Adopt rule:** propose the fitted curve only if its holdout MAE beats Hazus with an interval that excludes zero. It
does not, so no `validation/fitted/flood_ddf.json` was written. Two reasons the fit should not be trusted anyway: it
is nearly flat at 0.465 from 0.5 ft to 6 ft because train is 86% shallow-recorded claims, so it mostly learns a level
shift (the holdout 0-0.5 ft bucket improves and the buckets from 0.5 to 4 ft get worse), and the interval is wide because the
holdout has few independent events.

## Event backtest (leave one event out)

Each event is held out in turn. The fitted column is trained on every other claim, so it never sees the event.
Events are claims in the listed states with `dateOfLoss` inside the window. MS, NC and SC are included in the fetch
for Katrina, Florence and Helene.

| Event | States, window | n | Observed | Hazus 129 | bias | MAE | Fitted | bias | MAE |
|---|---|---|---|---|---|---|---|---|---|
| Katrina 2005 | LA, MS, 2005-08-23 to 09-05 | 4,437 | 0.640 | 0.187 | -0.454 | 0.475 | 0.360 | -0.280 | 0.349 |
| Sandy 2012 | NY, NJ, 2012-10-27 to 11-05 | 2,469 | 0.376 | 0.216 | -0.159 | 0.241 | 0.378 | +0.002 | 0.225 |
| Harvey 2017 | TX, 2017-08-23 to 09-05 | 20,910 | 0.408 | 0.146 | -0.262 | 0.295 | 0.309 | -0.098 | 0.208 |
| Florence 2018 | NC, SC, 2018-09-12 to 09-24 | 1,273 | 0.255 | 0.146 | -0.110 | 0.199 | 0.315 | +0.060 | 0.234 |
| Ida 2021, LA surge | LA, 2021-08-28 to 09-04 | 2,416 | 0.368 | 0.141 | -0.227 | 0.275 | 0.301 | -0.067 | 0.217 |
| Ida 2021, NY/NJ pluvial | NY, NJ, 2021-09-01 to 09-04 | 105 | 0.265 | 0.147 | -0.118 | 0.171 | 0.311 | +0.046 | 0.179 |
| Ian 2022 | FL, 2022-09-27 to 10-03 | 10,314 | 0.385 | 0.176 | -0.209 | 0.310 | 0.305 | -0.080 | 0.247 |
| Helene 2024 | NC, FL, 2024-09-24 to 09-30 | 9,802 | 0.491 | 0.160 | -0.332 | 0.366 | 0.302 | -0.190 | 0.250 |

Hazus 129 is low in all eight events. It is worst for Katrina (-0.454) and Helene (-0.332). A likely reason, which
I did not test, is the kind of flooding: Katrina was dominated by storm surge and levee failure with long-lasting
water, and Helene by fast river flooding in mountain terrain. A still-water depth-damage curve does not capture
velocity, duration or debris. It is closest for Florence (-0.110) and the Ida NY/NJ pluvial event (-0.118). The
fitted curve beats Hazus on MAE in six of eight events and loses on Florence (0.234 vs 0.199) and Ida NY/NJ
(0.179 vs 0.171). It is trained on the same questionable depth field, so a win says it matches the field better,
not that it is more correct. The Ida NY/NJ row has only 105 claims; read it as an indication only.

### Basement split (Sandy and Ida NY/NJ)

Basement claims (`basementEnclosureCrawlspaceType` 1 or 2) against the same no-basement Hazus 129 curve. The engine
has no basement curve, so this shows what a no-basement curve does to a basement building, not how good a basement
curve would be.

| Event | Group | n | Observed | Hazus 129 | bias | MAE |
|---|---|---|---|---|---|---|
| Sandy 2012 | no basement | 2,469 | 0.376 | 0.216 | -0.159 | 0.241 |
| Sandy 2012 | basement | 27,014 | 0.236 | 0.201 | -0.035 | 0.173 |
| Ida 2021, NY/NJ pluvial | no basement | 105 | 0.265 | 0.147 | -0.118 | 0.171 |
| Ida 2021, NY/NJ pluvial | basement | 2,572 | 0.175 | 0.157 | -0.019 | 0.139 |

Basement claims show a lower damage ratio than no-basement claims at the same recorded depth, because the damage is
to the basement level only and the ratio is against the whole building value. The no-basement curve is therefore
closer to unbiased for them, which is a coincidence of two effects and not evidence the curve fits basements. For
NYC a basement-specific curve and a basement flag are still needed.

## Tract ranking test

See the section at the end of this file once the run is complete.

## Limitations

- **No policy-years.** The redacted claims file has no exposure, so incidence below is claims per exposed building
  value, not claims per policy-year. A real frequency check needs the NFIP policies file.
- **Claims are a selected sample.** A claim exists only where flooding caused a loss the owner reported and the
  insurer opened, while a depth-damage curve is a mean over all flooded buildings. Observed ratios among claims
  run high for that reason alone.
- **Actual cash value denominator.** The ratio uses actual cash value. Hazus damage is a fraction of replacement
  cost, which is higher, so the observed ratio is inflated against Hazus.
- **Depth.** The reference level of `waterDepth` is not stated and the field has the problems listed above.
- **Rounded coordinates.** Latitude and longitude are rounded to 0.1 degree, so claims cannot be tied to parcels or
  to elevation data; tract is taken from the census block group.
- **Event windows.** Events are state plus `dateOfLoss` windows I chose, not the `floodEvent` label (which is null for
  many claims). Other storms inside a window are included.
- **One fit.** The held-out result is one split with a handful of events. The interval is wide for that reason.
- **Not done:** floors as a fit covariate (the fetch kept one-floor buildings only), a basement-specific curve, and
  a frequency relativity for flood zone or elevation difference (needs policies for the denominator).

## Reproduce

```bash
cd backend
uv run pytest tests/test_validation_flood.py              # committed sample, no network
RS_LIVE=1 uv run python -m validation.flood_fetch          # ~15 min, writes validation/data/claims_full.csv (23 MB, not committed)
RS_LIVE=1 uv run python -m validation.flood_report --claims validation/data/claims_full.csv
RS_LIVE=1 uv run python -m validation.flood_ranking
```

`validation/data/claims_sample.csv` is a stratified sample of 10,625 rows (about 1.2 MB) used by the tests; its
means are not representative.
