# NYC basement severity against NFIP basement claims

Run date 2026-10-17. Code: `backend/validation/nyc_basement_{fetch,sample,run}.py`. The NYC model is `backend/app/actuarial/nyc.py`.

## Verdict

**Use Hazus 129 at the water depth above the basement floor, scaled by 0.91. Drop the structure-curve-plus-finish
design of the first NYC draft.**

- **The first-draft design fails.** Each of the four Hazus basement structure curves (FIA 121, FIA 122, FIA (MOD.) 108,
  USACE-Chicago 133) plus a finish-and-contents term has a higher squared error than Hazus 129 on the held-out event,
  with a 95% interval wholly above zero, in both directions. With the finish term fitted on the training event it is
  still worse. The first-draft finish (0.075) leaves the prediction 0.17 to 0.22 below the observed mean.
- **Hazus 129 is close to unbiased on basement claims** (bias -0.019 on Ida NY/NJ, -0.035 on Sandy). The adopted
  change is a small downward scale: **k = 0.91**, the scale that minimises squared error on the pooled claims
  (0.87 and 0.91 when fitted on one event and tested on the other). It beats unscaled Hazus 129 on absolute error
  with an interval wholly below zero in both directions (adopt rule of `docs/validation/flood.md`).
- **The absolute-error scale (0.66 to 0.71) also passes that rule but is not used.** It under-predicts the mean by
  0.06 to 0.10 and does not improve squared error (it is significantly worse on Sandy). An expected-loss model
  should match the mean, so the squared-error scale is used.
- **An isotonic fit on depth wins on squared error but not on absolute error**, and is not adopted. Claims are
  conditional on a claim having been made, so their damage ratio is nearly flat in depth (0.19 at zero depth to 0.27
  above 3 ft). That says how much a claimed basement loses, not how much a basement loses when it floods.

The level of the NYC perils is set by the NRI tract rate, so the scale only changes how a basement home's severity
compares with a home without one.

## Data

| Item | Value |
|---|---|
| Dataset | OpenFEMA NfipClaims v3, https://www.fema.gov/api/open/v3/NfipClaims, fetched 2026-10-17 |
| Filter | Single-family (`occupancyType` 1 or 11), `basementEnclosureCrawlspaceType` 1 or 2, `waterDepth` 0 to 240 in, `buildingPropertyValue` at least $20,000, `buildingDamageAmount` at least 0, state NY or NJ |
| Events | Sandy: loss date 2012-10-27 to 2012-11-05, **n = 27,014**. Ida NY/NJ pluvial: 2021-09-01 to 2021-09-04, **n = 2,572** |
| Ratio | `buildingDamageAmount` / `buildingPropertyValue`, capped at 1. Mean 0.236 (Sandy), 0.175 (Ida) |
| Depth | `waterDepth` / 12, in ft, used as the water depth above the basement floor |
| Cluster | census tract (first 11 digits of `censusGeoid`): 756 tracts in Sandy, 660 in Ida |

Counts match the basement split in `docs/validation/flood.md`.

## Method

Leave one event out, both ways: fit on Sandy and test on Ida NY/NJ, then fit on Ida and test on Sandy. Every
candidate is fitted on the training event only. The paired error difference to Hazus 129 on the test event has a
95% interval from 2,000 bootstrap resamples of census tracts (two events cannot be resampled as events).

**Adopt rule:** a candidate replaces Hazus 129 only if the 95% interval of its paired error difference lies wholly
below zero in both directions. Absolute error is the rule of the flood validation; squared error is reported beside
it. Candidate verdicts are in `backend/validation/results/nyc_basement.csv` and `.json`.

## Results (full pull)

Mean absolute error (MAE), mean squared error (MSE) and bias (predicted minus observed) on the held-out event; the
differences are to Hazus 129 with the 95% interval.

| Train -> test | Candidate | MAE | MSE | Bias | MSE diff [95%] | MAE diff [95%] |
|---|---|---|---|---|---|---|
| Sandy -> Ida | Hazus 129 | 0.1387 | 0.0444 | -0.019 | | |
| | Hazus 129 x 0.91 (MSE fit) | 0.1350 | 0.0439 | -0.033 | -0.0005 [-0.0012, +0.0002] | **-0.0037 [-0.0050, -0.0024]** |
| | Hazus 129 x 0.71 (MAE fit) | 0.1303 | 0.0446 | -0.064 | +0.0002 [-0.0020, +0.0024] | -0.0083 [-0.0126, -0.0043] |
| | FIA 121 + first-draft finish | 0.1711 | 0.0660 | -0.169 | +0.0216 [+0.0144, +0.0289] | +0.0324 [+0.0215, +0.0425] |
| | FIA 121 + fitted finish (0.315) | 0.1656 | 0.0629 | -0.153 | +0.0185 [+0.0125, +0.0248] | +0.0269 [+0.0171, +0.0359] |
| | FIA (MOD.) 108 + fitted finish (0.230) | 0.1411 | 0.0535 | -0.116 | +0.0091 [+0.0046, +0.0138] | +0.0024 [-0.0060, +0.0103] |
| | Isotonic on depth | 0.1603 | 0.0392 | +0.051 | -0.0052 [-0.0096, -0.0011] | +0.0217 [+0.0129, +0.0300] |
| Ida -> Sandy | Hazus 129 | 0.1731 | 0.0602 | -0.035 | | |
| | Hazus 129 x 0.87 (MSE fit) | 0.1680 | 0.0599 | -0.061 | -0.0003 [-0.0010, +0.0004] | **-0.0052 [-0.0063, -0.0040]** |
| | Hazus 129 x 0.66 (MAE fit) | 0.1658 | 0.0632 | -0.103 | +0.0030 [+0.0013, +0.0048] | -0.0073 [-0.0102, -0.0043] |
| | FIA 121 + first-draft finish | 0.2205 | 0.0969 | -0.219 | +0.0367 [+0.0321, +0.0416] | +0.0474 [+0.0404, +0.0539] |
| | FIA 121 + fitted finish (0.510) | 0.2089 | 0.0854 | -0.126 | +0.0253 [+0.0230, +0.0278] | +0.0358 [+0.0320, +0.0393] |
| | FIA (MOD.) 108 + fitted finish (0.250) | 0.1803 | 0.0731 | -0.140 | +0.0129 [+0.0103, +0.0157] | +0.0072 [+0.0027, +0.0116] |
| | Isotonic on depth | 0.1633 | 0.0509 | -0.033 | -0.0093 [-0.0104, -0.0083] | -0.0099 [-0.0121, -0.0076] |

Pooled scale on all 29,586 claims: 0.71 (absolute error), 0.91 (squared error). FIA 122 and USACE-Chicago 133 behave
like FIA 121 (see the CSV). FIA (MOD.) 108 is the closest of the structure curves and still loses on squared error.

Observed mean damage ratio by recorded depth (all claims): 0.19 at zero depth (n = 5,969), 0.23 up to 6 in, 0.24 from
6 in to 2 ft, 0.26 from 2 to 3 ft, 0.27 from 3 to 5 ft, 0.26 above 5 ft. Hazus 129 climbs from 0.13 to 0.60 over the
same range.

## Limitations

- **Depth reference.** `waterDepth` has an unstated reference level. For basement claims it is not known whether it is
  measured above the basement floor, the first floor or grade. Between 19% (Sandy) and 33% (Ida) of claims record zero,
  and the field heaps on whole feet (see the data-quality table in `docs/validation/flood.md`).
- **Claims are conditional on a claim.** The ratio is among buildings with an open claim, so it overstates the loss for
  a flooded basement that produces no claim and says little about the probability of a claim at a given depth.
- **Actual cash value.** Both the damage and the denominator are actual cash value, not replacement cost.
- **Building coverage only.** Contents are a separate coverage and are not in `buildingDamageAmount`; NFIP building
  coverage for basements is limited to specific items. A finished-basement contents loss is outside this validation.
- **Two events, one region.** The split has two events in the New York region. Intervals resample tracts, which
  understates between-event variation.
- **Basement size and finish are priors.** The partial-basement scale (0.6), the finish relativity for a DOB-flagged
  conversion (1.25) and the basement entry rate stay `validated: false` in the registry; the claims data cannot
  separate them.

## Reproduce

```bash
cd backend
uv run pytest tests/test_validation_nyc_basement.py                        # committed sample, no network
RS_LIVE=1 uv run python -m validation.nyc_basement_fetch                   # about 1 min, writes validation/data/nyc_basement_full.csv
uv run python -m validation.nyc_basement_run --claims validation/data/nyc_basement_full.csv
uv run python -m validation.nyc_basement_sample                            # re-cut the committed sample
```

`validation/data/nyc_basement_sample.csv` holds all 2,572 Ida claims and 5,000 of the Sandy claims (seeded), 7,572
rows. Its means are not representative; the committed results come from the full pull.
