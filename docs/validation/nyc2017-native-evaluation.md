# Native NYC 2017 terrain evaluation

Evaluated 2026-10-18 around Murray Hill building `1112075`, labeled `2 AVENUE` in the application.

**Decision: the native 2017 bare-earth DEM is the preferred historical replacement candidate for this block, with conditions. It is not verified present-day ground, and switching to it will not remove every depression.** Application terrain and rendering are unchanged by this evaluation.

The [comparison figure](nyc2017-native-evaluation.png) shows matched terrain maps, source differences, distance to ground returns, and profiles through two disputed locations. [Results and input checksums](nyc2017-native-evaluation.json) and a [compact evidence archive](nyc2017-native-evidence.zip) accompany it.

## What was evaluated

- NOAA's native `be_NYC_025.tif`, dataset `9307`, cropped without resampling to 1,580 by 1,348 original cells.
- The two 2017 classified COPC tiles intersecting the block. Full-resolution spatial queries returned 1,324,279 non-withheld class-2 ground points. No LOD downsampling was requested. A 57.66 m minimum query halo exceeds the maximum 26.47 m nearest-return distance, so query clipping cannot inflate the reported support distances.
- The exact USGS and NYS 2017 service rasters retained in the earlier audit, on the same 452 by 373 grid. The native DEM was nearest-neighbour reprojected to their 168,596 sample locations for comparisons. The maps use that common grid; profiles use the native raster directly.

The [official DEM metadata](https://www.fisheries.noaa.gov/inport/item/64732) identifies a 2017 acquisition, a hydro-flattened bare-earth product and a 1-foot grid. The native tile uses EPSG:6539 horizontal coordinates and NAVD88 elevation values in US survey feet. Both units require conversion. Elevations were multiplied by exactly `1200/3937` to obtain metres. This is dataset `9307`, distinct from the hydro-enforced product `9310`.

The [classified-point distribution](https://noaa-nos-coastal-lidar-pds.s3.amazonaws.com/laz/geoid18/9306/index.html) uses EPSG:6347 horizontal coordinates in metres and NAVD88 heights using GEOID18. The raster metadata specifies GEOID12B. No geoid-realization correction was applied. This prevents interpreting centimetre residuals as an absolute accuracy result; it does not explain the multi-metre differences below.

## Findings

At probe A, `[-73.97249300533004, 40.74487191784359]`, the older USGS raster is **−3.17 m**, while the native 2017 pixel is **+2.49 m**. There are 16 classified ground returns within 1 m, ranging from +2.45 to +2.78 m. Their nearest return is 0.15 m away at +2.46 m. The 2017 data supports a surface about 5.66 m above the older raster here. This establishes a historical disagreement, not the reason the older source is low.

At probe B, `[-73.97495797901215, 40.7425999087431]`, the native 2017 DEM is **−4.61 m**, while USGS is **+6.19 m**. The low surface has **45 classified ground returns within 1 m**, spanning −4.66 to −4.55 m, from five point-source IDs. Within 2 m there are 163 ground returns. This is not an isolated low raster pixel or a service-only interpolation artifact. It could represent a real historical lower surface or systematic classification; its present-day physical meaning remains unresolved. Filling this depression merely to make the display smooth would discard supported historical observations.

At the selected building centre, native 2017 elevation is **+4.61 m**, close to the retained USGS sample of +4.62 m. The nearest classified ground return is **8.39 m away**, with none within 5 m. A fine DEM cell under a building is therefore not a direct observation of the ground beneath it. Across the complete matched grid, **36.69% of cells have no classified ground return within 1 m**, and 6.71% have none within 10 m. These percentages include building interiors; they are not a rejection rate for exposed streets.

The selected building's native perimeter samples span **+2.29 to +5.44 m**. A single centre or minimum-perimeter value cannot establish a uniform foundation elevation across that relief. The recorded 44.65 m building height is a separate measurement and should remain unchanged.

## Source consistency measurements

At the 97,844 common grid locations with a classified 2017 ground return within 0.5 m:

| Raster | Median absolute difference from nearest 2017 ground return | 95th percentile absolute difference | Samples differing by more than 1 m |
| --- | ---: | ---: | ---: |
| USGS 2013–14 | 5.32 cm | 37.32 cm | 2,692 / 97,844, or 2.75% |
| NYS 2017 1 m service | 2.87 cm | 14.51 cm | 331 / 97,844, or 0.34% |
| Native 2017 1-foot DEM | 0.85 cm | 4.43 cm | 58 / 97,844, or 0.059% |

**These are internal consistency measurements against the 2017 acquisition, not independent accuracy or present-day survey errors.** The native DEM derives from these classified points, so its stronger agreement is expected. Nearest-neighbour sampling, finite grid spacing, registration, geoid realization and actual vertical boundaries can contribute to residuals. This test does not classify the remaining large residuals as artifacts.

Across all matched cells, native 2017 differs from USGS by more than 1 m at 9,978 cells, or 5.92%, and by more than 3 m at 4,454 cells, or 2.64%. Its difference from the NYS 2017 service is much smaller overall, with a median absolute difference of 3.05 cm, although 520 cells differ by more than 1 m. Finer source sampling improves representation of narrow features and boundaries; it is not evidence that every additional detail is correct.

The [project's independent survey assessment](https://noaa-nos-coastal-lidar-pds.s3.amazonaws.com/laz/geoid18/9306/supplemental/New_York_City_2017_Topobathymetric_LiDAR_Report_FINAL.pdf) reports 3.8 cm RMSE using 151 withheld check points on open, relatively level ground. That project-wide assessment does not validate an interpolated building centre, a disputed depression, or conditions after 2017. No local current survey or contemporary imagery was used here.

## Adoption conditions

Use the native 2017 product as a dated historical terrain layer if a source change proceeds. Preserve its elevations and provenance, distinguish interpolated building interiors from nearby observed ground, and review building placement across substantial perimeter relief. Do not fill pits or flatten slopes solely for appearance. Keep hydro-enforced drainage surfaces separate from physical ground display.

For a claim about current ground, resolve probes A and B with dated imagery or surveyed elevations and account for bridge decks, retaining walls, stairs, excavations and other surfaces that a bare-earth model can omit. This one-block result does not establish citywide quality or deployment performance.

## Reproduction

Install `frontend/scripts/nyc2017-evaluation-requirements.txt` in a separate Python environment. The evaluated environment was Python 3.9.6; package versions are pinned. Unpack `nyc2017-native-evidence.zip` into a scratch cache, then run from the repository root:

```sh
python frontend/scripts/evaluate-nyc2017-terrain.py --cache /private/tmp/nyc2017-evaluation
```

Add `--fetch` to reacquire the public raster window, full-resolution spatial COPC queries and ground-support grid. The earlier service rasters are extracted from the existing audit archive. The compact archive retains the native crop, all point returns around the three probes, a derived nearest-ground support grid, query manifest and official metadata snapshots. Full-block point clouds are fetched again when regenerating the support grid; the archive does not duplicate them.

The script checks original service-input hashes and archive-manifest hashes, source CRS, height units, grid alignment, complete coverage, query halo, finite values, expected source consistency and reproduction of the disputed depression. The offline replay passed using a freshly unpacked archive. Deliberately altered evidence and incorrectly labeled elevation units were both rejected. Frontend lint and production build passed.

A separate read-only agent reviewed the methodology, conclusions and figure, freshly unpacked the updated evidence archive, and reproduced the complete results JSON exactly. No blocking issues were found. This evaluates source data only; application behavior and build/export configuration did not change.
