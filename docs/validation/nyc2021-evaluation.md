# NYC 2021 LiDAR investigation

Evaluated 2026-10-18 around Murray Hill building `1112075`, labeled `2 AVENUE` in the application. This follows the [native 2017 evaluation](nyc2017-native-evaluation.md).

**Decision: the 2021 classified points are a stronger candidate for developing a newer historical ground layer. They are not a ready-made replacement DEM or verified current ground.** The application source, building geometry, camera, simulation and build/export configuration remain unchanged.

[Comparison figure](nyc2021-evaluation.png) · [Measurements and source hashes](nyc2021-evaluation.json) · [Compact reproducible evidence](nyc2021-evidence.zip)

## Acquisition, coordinates and availability

The [public NYS archive](ftp://ftp.gis.ny.gov/elevation/LIDAR/NYC_2021/) contains 1,740 LAS tiles, a mapping report and index sidecars. The Eagleview report describes a May 12–21, 2021 acquisition, corroborated by [USGS source metadata](https://cmgds.marine.usgs.gov/catalog/spcmsc/2021-357-DD_morphology_metadata.html). The sampled ground records independently decode to GPS measurement dates during May 15–20, 2021. This is a newer acquisition, not a republication of the 2017 survey.

Embedded coordinate WKT in both inspected LAS files confirms NAD83(2011), State Plane Long Island, EPSG:6539, and NAVD88 heights in US survey feet, EPSG:6360, using GEOID18. All three coordinate axes were converted using exactly `1200/3937` metres per US survey foot. The LAS records use version 1.4, format 6.

There are two documentation traps:

- The report's flight table prints 2019, despite the 2021 acquisition narrative and `2105…` mission IDs. The actual point-record times corroborate 2021.
- The adjacent index XML contains copied 2017 Quantum Spatial metadata. It is unsuitable for dating this survey or determining its vertical realization. Embedded LAS WKT and the 2021 report agree on GEOID18.

No 2021 DEM is listed in the archive or the report's deliverables. The checked NYS/NOAA service catalogs did not expose a 2021 DEM, COPC or EPT equivalent. NYS's live `Latest_DEM` still identifies the 2017 product at the selected building. These are bounded availability checks, not proof that no other distribution exists.

Public access was verified, but an unambiguous redistribution license for the raw 2021 survey was not found. The separate Nature Conservancy land-cover products have their own terms; they are not the raw terrain source and their license should not be assumed to apply to it.

## What was measured

The two relevant tiles, `990210.las` and `990207.las`, contain 27,603,532 source points. Their source files total 829,729,520 bytes. They were streamed through bounded buffers; **full LAS files were never written to disk**. Only a local geographic crop of non-withheld classes 2 and 8, and raw 20 m probe windows, were retained temporarily. Full cropped ground arrays were removed after constructing the support grids.

The local crop contained **1,912,540 class-2 ground points** and **152,790 class-8 model-key points**, or 2,065,330 together. Withheld records were excluded from terrain comparisons. Classes 7 and 18 were not treated as ground. Class 8 was evaluated separately because the survey's reported validation uses classes 2 and 8 together.

Comparisons use the earlier audit's exact **452 by 373 grid, or 168,596 cells**. At each location, the nearest observed 2021 ground height and its horizontal distance were recorded. The figure masks heights whose nearest ground/key point is more than 1 m away. White cells therefore remain unsupported in that display; no interpolated DEM is presented as observed ground.

The 56.99 m query halo exceeds the maximum 32.01 m nearest-ground distance, preventing artificial gaps caused by clipping the input query. Source file sizes, complete point counts, class histograms, full-file hashes, headers and embedded coordinate WKT were checked. The LAS files contain metadata after the point records; the decoder stops at the declared point count and parses those trailing EVLRs separately.

## Local findings

| Location | 2021 observation | Implication |
| --- | --- | --- |
| A, older USGS pit | 38 class-2 returns within 1 m, ranging **+2.81 to +2.90 m**; 43 including class 8 | Supports a higher historical surface than the USGS raster's −3.17 m |
| B, 2017 depression | **29 class-7 low/noise returns within 1 m**, median **−4.63 m** | Low measurements persist in 2021; they were classified differently |
| Ground around B | No class-2/8 returns within 2 m. Nearest is **2.46 m away at +6.14 m**. Within 5 m there are 373 class-2 returns, or 397 including class 8 | A surface derived from 2021 ground classes would interpolate across this gap from higher surrounding ground |
| Selected building centre | No class-2/8 returns within 5 m; nearest is **11.56 m away**, versus 8.39 m in 2017 | Newer data does not directly observe the ground beneath this building |

Probe B is the main finding. The 2017 survey classified low returns as ground and its native DEM reaches −4.61 m there. The 2021 survey still measures similar low elevations, but labels them class 7. This supports a **classification difference**, not a conclusion that the physical pit was filled, removed or necessarily erroneous. The low returns span three point-source IDs. Their physical meaning still needs imagery, site context or survey confirmation.

The left and middle lower panels show returns within 1 m north/south of east/west sections through A and B. The selected-building panel instead shows ground heights against radial distance from the centre. These plots preserve observed gaps and keep noise separate from ground.

## Coverage and differences

| Ground selection | Cells with a return within 1 m | Maximum nearest-return distance |
| --- | ---: | ---: |
| 2017 class 2, earlier audit | 63.31% | 26.47 m |
| 2021 class 2 | 60.58% | 32.01 m |
| 2021 classes 2 + 8 | 61.67% | 31.63 m |

These percentages include building interiors. They are not exposed-street accuracy rates. The newer survey's larger local point count does not eliminate ground shadows or classification exclusions.

At 88,090 locations with a return within 0.5 m in both the 2017 point cloud and 2021 classes 2+8, the median signed 2021-minus-2017 difference is **+1.16 cm**. The middle 90% ranges from **−7.34 to +10.43 cm**. There are 702 differences over 1 m, or 0.80%, and 399 over 3 m. These are differences between historical observations and classifications, not independent survey errors. Nearest observations also have finite horizontal separation, particularly significant at steps and retaining walls.

The two point-cloud distributions use NAVD88/GEOID18. Comparisons with the native 2017 DEM additionally involve its GEOID12B realization; no geoid-realization correction was applied to that DEM comparison.

## Reported survey accuracy

The [Eagleview mapping report](ftp://ftp.gis.ny.gov/elevation/LIDAR/NYC_2021/65220909_Eagleview_NYC_Mapping_Report_EV.pdf), PDF page 16, printed page 15, reports a TIN using classes 2 and 8:

| Check | Reported result |
| --- | --- |
| Nonvegetated checkpoints | 39 |
| Nonvegetated vertical RMSE | **3.846 cm, PASS** |
| Nonvegetated 95% accuracy | **7.539 cm, PASS** |
| Vegetated checkpoints | 40 |
| Vegetated 95th-percentile accuracy | **39.432 cm, FAIL** |

The 12 points/m² target in the report is a project specification, not the local density of classified ground returns. These project-wide results do not validate individual building interiors or disputed low points. The reported vegetation failure should not be hidden behind the passing open-ground result.

## Recommended next implementation

Develop a dated 2021 ground layer from classes 2 and 8, with explicit support distances and controlled interpolation across gaps. Review the disputed low returns and bridge/retaining-wall context before accepting the resulting surface. Class-6 automated building points can inform a separate building audit; they are not surveyed footprint or foundation geometry.

Precompute and cache small terrain tiles outside the browser. The public FTP LAS distribution is unsuitable for downloading directly during view changes. Preserve the existing demand rendering and geometry reuse when integrating a derived raster. Until those steps are validated, keep the application's current source unchanged. No additional field accuracy or performance claim follows from this investigation.

## Reproduction and validation

Use `frontend/scripts/nyc2017-evaluation-requirements.txt` in an isolated Python environment. Unpack `nyc2021-evidence.zip` into a scratch directory and run:

```sh
python frontend/scripts/evaluate-nyc2021-terrain.py --cache /private/tmp/nyc2021-replay
```

The compact archive contains raw probe records, source headers and coordinate WKT, a stream manifest and derived support grids. It deliberately omits full LAS tiles and full-block point arrays. Existing 2017 archives supply the comparison inputs. Add `--fetch` to stream the two original source files, rebuild the local support grids and remove the temporary full-crop arrays. That option uses about 830 MB of network transfer, not 830 MB of saved LAS files.

The initial extraction and the reusable streaming implementation produced identical original-file hashes, counts and probe results. Floating-point support statistics agree within `1e-9` metres. Offline replay checks retained-file hashes, source coordinate systems, point-count reconciliation, query coverage, class-8 sensitivity and reproduction of the noise/ground distinction. A separate agent independently decoded the raw probe records and confirmed the key findings.

A fresh replay from the compact archive exactly reproduced the saved JSON, independently repeated by that agent. All 11 archived input hashes matched. Deliberately corrupted evidence and incorrectly declared vertical units were rejected. Frontend lint and production build passed. No full LAS files or full-crop ground arrays remain in the analysis cache.
