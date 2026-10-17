# Wildfire relativities against real structure outcomes

Run date 2026-10-17. Code: `backend/validation/wildfire_*.py`. Reproduce with
`cd backend && uv run python -m validation.wildfire_run` (committed sample, no network).

## Verdict

Validated against the engine on `main` after model v2 (#18), where each of the five wildfire features carries the
same IBHS-derived immunity lift and no severity attenuation, so each modelled relativity is 0.92.

- **The direction is right; the model understates the protection.** Class A roof, enclosed eaves and screened
  vents each cut the destroyed share by 17–28% within a fire. The model credits each with 8%.
- **Observed / modelled is below 1 for three features, with CIs wholly below 1:** Class A roof 0.78 (0.71–0.86),
  enclosed eaves 0.86 (0.80–0.93), screened vents 0.91 (0.86–0.95). The model is too weak here, most for the roof.
- **The Zone 1 "no shed" proxy is consistent with the model.** Observed 0.96 (0.91–1.01), ratio 1.04 (0.99–1.10).
- **Zone 0 clearance cannot be tested.** DINS has no vegetation field, so that feature has no outcome evidence
  here either way.
- **Discrimination from these features alone is weak.** Leave-one-fire-out AUC of the current relativities is
  about 0.55 on complete-case homes (0.5 is chance); a refit gets 0.63. That is expected, since hazard is held
  constant and ember exposure and neighbours dominate, but it means hardening features should adjust a hazard
  score, not stand in for one.
- **Before model v2** the same test gave modelled relativities of 0.78 (roof), 0.84 (eaves), 0.73 (vents) and
  0.85 (shed): close for roof and eaves, too strong for vents. v2 flattened them to 0.92, which moved the
  verdict from "vents too strong" to "all three too weak".
- **Do not claim more than the data shows.** DINS attributes are written after the fire, and "Unknown" is mostly
  recorded on destroyed homes. Details under Limitations.

## Data

CAL FIRE Damage Inspection (DINS) database, ArcGIS FeatureServer
`https://services1.arcgis.com/jUJYIo9tSA7EHvfZ/ArcGIS/rest/services/POSTFIRE_MASTER_DATA_SHARE/FeatureServer/0`
(found by web search and read on 2026-10-17; max 2,000 records per page, DINS 2013-present). Fields used: `DAMAGE`,
`ROOFCONSTRUCTION`, `EAVES`, `VENTSCREEN`, `EXTERIORSIDING`, `WINDOWPANE`, `DECKPORCH*`, `PATIOCOVERCARPORT`,
`UTILITYMISCSTRUCTUREDISTANCE`, `YEARBUILT`.

- **Outcome:** destroyed (>50%) versus every other inspected class. "Inaccessible" is dropped.
- **Unit:** single residences only.
- **Fires:** every fire with at least 300 inspected structures, at least 5% of them undamaged (DINS records
  undamaged structures only from 2018), and at least 30 destroyed single residences. That gives **32 fires**,
  **12,362 sampled homes**. Eaton 2025, Palisades 2025 and Camp 2018 are all in.
- **Not available as requested:** Tubbs 2017 and Thomas 2017 hold damaged structures only, so there are no survivors
  to compare against. Woolsey 2018 and Carr 2018 have under 5% undamaged records. Dixie, CZU, LNU and the others are in.
- **Sample:** a seeded random sample of 1,500 homes for Eaton, Palisades and Camp and 300 for every other fire,
  to stay under 2 MB. Sampling is uniform within a fire, so within-fire estimates are unbiased. Fire-level counts
  come from the full population (`data/wildfire_population.json`).

## Method

- **Coding.** Each feature is favourable, unfavourable or unknown. Class A roof means asphalt, metal, tile, concrete
  or fire-resistant (wood and "combustible" are unfavourable). Enclosed eaves versus unenclosed. Screened vents means
  mesh of 1/8 inch or finer versus coarser mesh or unscreened. The shed proxy is a utility or misc structure
  within 30 ft. DINS has no true distance to the nearest structure, so this is the closest field.
- **Modelled relativity.** Read from the engine's own constants (`EFFECTS`, `ETA0`, `TAIL`) with hazard held
  constant. Destroyed = a loss event (1 minus the immunity probability) that lands in the catastrophic tail.
  The expected-loss relativity is in `results/wildfire_features.csv`.
- **Observed ratio.** Mantel-Haenszel risk ratio of destroyed, stratified by fire, known values only, with a
  Greenland-Robins 95% CI.
- **Fit.** Logistic regression of destroyed on the coded features, year-built era (before 1980, 1980–2007, 2008 on)
  and fire fixed effects. Unknown is its own level. Coefficients have Wald 95% CIs.
- **Split.** Leave-one-fire-out: each fire is scored by a model fitted on the other 31. The stated Phase 2 split
  holds out Palisades 2025 and trains on all other fires. The narrower Eaton 2025 + Camp 2018 to Palisades split
  is reported as well.
- **Scoring.** Unknown levels earn zero credit in both the current and the fitted score, as at underwriting.
  Intercepts are re-centred to each holdout's base rate, so AUC, log-loss and slope measure ranking and spread only.
- **Headline set.** Complete-case homes (roof, eaves and vent screen all recorded). The all-homes AUC is also reported.

## Results

### Observed versus modelled relativity (fire-stratified, pooled)

| Feature (favourable vs not) | n known | Observed RR (95% CI) | Modelled RR | Observed / modelled | Fitted OR (95% CI) |
|---|---|---|---|---|---|
| Class A roof | 10,188 | 0.72 (0.66–0.79) | 0.92 | **0.78 (0.71–0.86)** | 0.35 (0.22–0.53) |
| Enclosed eaves | 6,418 | 0.79 (0.73–0.86) | 0.92 | **0.86 (0.80–0.93)** | 0.80 (0.67–0.94) |
| Screened vents (≤1/8 in) | 6,609 | 0.83 (0.79–0.88) | 0.92 | **0.91 (0.86–0.95)** | 0.76 (0.65–0.90) |
| No shed within 30 ft (proxy) | 3,454 | 0.96 (0.91–1.01) | 0.92 | 1.04 (0.99–1.10) | 0.76 (0.60–0.96) |
| Multi-pane windows | 9,382 | 0.69 (0.66–0.72) | not modelled | | 0.55 (0.48–0.63) |
| Non-combustible siding | 10,261 | 1.32 (1.27–1.38) | not modelled | | 1.68 (1.47–1.93) |
| No wood deck | 9,454 | 1.13 (1.08–1.17) | not modelled | | 1.09 (0.95–1.25) |
| Built 2008 or later (vs before 1980) | | | | | 0.51 (0.35–0.74) |

A ratio below 1 means the data show more protection than the model credits. The fitted OR is
fire-adjusted on all 12,362 homes; it is an odds ratio, so it sits further from 1 than the risk ratio does.

Siding and deck point the wrong way (hardened homes destroyed more often). This is most likely a recording artifact, not a
finding (my reading, untested): wood siding that burned away is probably recorded as Unknown, while surviving
stucco is easy to see. They are
excluded from the proposal.

### Hardening count

Homes with all five of roof, eaves, vents, siding and windows recorded (n = 4,631):

| Favourable features | n | Destroyed share (95% CI) | Mean modelled relativity |
|---|---|---|---|
| 0 | 15 | 0.60 (0.36–0.80) | 0.97 |
| 1 | 746 | 0.37 (0.34–0.41) | 0.90 |
| 2 | 1,430 | 0.35 (0.33–0.37) | 0.88 |
| 3 | 1,344 | 0.28 (0.26–0.30) | 0.84 |
| 4+ | 1,096 | 0.23 (0.21–0.26) | 0.78 |

From 1 to 4+ features the destroyed share falls to 0.63 of its starting level; the model's mean relativity
falls to 0.86 (0.90 to 0.78). The 0-feature row is too small to use. This pooled table is not
fire-adjusted; the per-feature table above is.

### Discrimination (leave-one-fire-out; full table in `results/wildfire_fires.csv`)

| Fire | Inspected | Destroyed share | n complete | AUC current | AUC fitted | AUC current, all homes | AUC fitted, all homes |
|---|---|---|---|---|---|---|---|
| Camp 2018 | 23,624 | 0.80 | 718 | 0.56 | 0.56 | 0.59 | 0.58 |
| Eaton 2025 | 18,388 | 0.51 | 680 | 0.59 | 0.73 | 0.66 | 0.78 |
| Palisades 2025 | 12,081 | 0.57 | 502 | 0.53 | 0.57 | 0.62 | 0.67 |
| Glass 2020 | 4,762 | 0.26 | 169 | 0.65 | 0.71 | 0.69 | 0.71 |
| Caldor 2021 | 4,442 | 0.24 | 179 | 0.42 | 0.72 | 0.52 | 0.68 |
| North Complex 2020 | 3,204 | 0.77 | 77 | 0.72 | 0.73 | 0.69 | 0.66 |
| Borel 2024 | 505 | 0.50 | 109 | 0.66 | 0.70 | 0.66 | 0.74 |

- **Weighted mean across fires** (complete-case, weighted by n): current 0.55, fitted 0.63.
- **Eaton and Palisades** (wind-driven urban conflagration): current 0.56, fitted 0.66.
  **All other fires:** current 0.54, fitted 0.61. The current relativities are no better in the WUI fires they
  were designed for.
- **Palisades holdout** (trained on the other 31 fires): current 0.530 (0.473–0.586), fitted 0.572 (0.515–0.629).
  On all homes: 0.623 versus 0.674. Log-loss 0.597 versus 0.595: the fitted model wins on both, by a small
  margin on log-loss. Calibration slope 1.43 (current) and 0.51 (fitted), where 1 is ideal: the current score
  spreads risk too little, while the fitted one overstates it on this holdout (a sign it partly learned
  fire-specific patterns).
- **Eaton 2025 + Camp 2018 to Palisades:** current 0.530, fitted 0.555 (0.498–0.611). With only two training
  fires the AUC gain is within noise, and log-loss is slightly worse for the fitted model (0.633 versus 0.628).
- **Thin fires.** Nineteen of the 32 fires have fewer than 20 destroyed (or surviving) complete-case homes, so only the
  all-homes AUC is shown for them. Many show an AUC far from 0.5 (Creek 0.05, Kincade 0.04, LNU 0.13), which is
  the artifact above: there, destroyed homes were recorded with *more* favourable known features than survivors.
  These are not evidence that the model is inverted.
- **Calibration by decile** is in `results/wildfire_details.json`. `results/wildfire_summary.json` holds the fixed report shape the frontend
reads (fire AUCs there are on all homes with unknowns neutral). After re-centring, the pooled deciles mostly
  track fire base rates, so use the within-fire AUC above, not the deciles, as evidence of discrimination.

### Fitted proposal

`backend/validation/fitted/wildfire_relativities.json` (fit date 2026-10-17, holdout Palisades 2025, trained on 31
fires) proposes odds ratios for Class A roof, enclosed eaves, screened vents, multi-pane windows and the 2008+ era.
The holdout beats the current model on AUC and log-loss, and each CI excludes 1. Non-combustible siding is withheld
(wrong sign). Deck and the shed proxy do not qualify (no CI wholly below 1 in the 31-fire fit). `app/actuarial` is untouched; the
actuarial lane decides adoption.

## What this means for the demo (S2)

| Action | Supported? | Strength |
|---|---|---|
| Class A roof | Yes, strongly | RR 0.72 (0.66–0.79); model says 0.92. Proxy: non-wood roof |
| Enclosed eaves | Yes | RR 0.79 (0.73–0.86); model says 0.92 |
| Screened vents | Yes | RR 0.83 (0.79–0.88); model says 0.92 |
| Zone 1 shed removal | Not shown | RR 0.96, CI includes 1; proxy field only |
| Zone 0 clearance | Not testable | No vegetation field in DINS |

The S2 story (Class A roof, vent screening, enclosed eaves) stands, and the data say the model, if anything,
undersells it. The Zone 0 and Zone 1 claims should be presented as engineering judgement rather than as
validated.

## Limitations

- **Selection and post-fire observation.** DINS covers only structures inspected inside or near a burned perimeter.
  Attributes are recorded after the fire, from what remains. "Unknown" is common on destroyed homes (eaves Unknown:
  74% destroyed; known eaves: 23–30%), so missingness correlates with the outcome. The fit keeps Unknown as a
  separate level and the score ignores it, but known values can still be biased the same way.
- **Proxies.** Class A roof is "not wood". Eaves, vents and siding are as recorded by inspectors, who differ.
  The shed variable is a utility/misc structure distance, mostly blank (72% unknown).
- **Hazard is not held constant by the data.** Fire fixed effects absorb fire-level differences, but not
  within-fire differences in ember exposure, slope or neighbour spacing. Hardened homes may sit in less exposed
  places.
- **Sample.** A seeded sample (1,500 per key fire, 300 per other fire) of single residences. Some fires have
  only a few dozen complete-case homes. AUC CIs use Hanley-McNeil.
- **Fires are not independent draws** (regimes differ; Eaton and Palisades are Santa Ana wind-driven urban fires).
  The fire-level AUCs are the honest spread.
- **No independent post-2025 test.** Eaton and Palisades are the most relevant fires and also the most
  wind-driven, where structure features matter least.
