# SaveMyHome: 2-Person Parallel Execution Plan & Prompt Engineering Blueprint

This execution blueprint divides the **SaveMyHome** build across two engineers working in parallel—**Builder 1 (Backend, Spatial Pipeline, Actuarial Engine & MCP/Core Integration)** and **Builder 2 (Frontend, Geospatial Map Canvas, Underwriting Copilot UI & HITL Workflows)**—so neither person blocks the other during the hackathon while establishing a clean, modular monorepo that scales directly into long-term production.

## 1\. Parallel Architecture & Division of Labor

To prevent integration bottlenecks, both builders agree on a single **JSON API Contract** in the first 15 minutes. **Builder 2** develops immediately against deterministic local fixtures representing the three golden demo parcels, while **Builder 1** builds the live FastAPI spatial and actuarial pipeline to emit that exact schema (with an automatic cache/fallback layer so rural/venue Wi-Fi or third-party API latency never breaks the live pitch).

| Module / Domain | Owner | Hackathon Implementation (24–48 Hours) | Long-Term Production Evolution |
| ----- | ----- | ----- | ----- |
| **API & Data Contract** | Shared (Min 0–15) | Shared TypeScript interfaces \+ Pydantic v2 models (`schemas.py` & `types.ts`). | OpenAPI 3.1 \+ AsyncAPI spec Registry with strict semantic versioning \[cite: \]. |
| **Geospatial & Federal Ingestion** | **Builder 1 (Backend)** | Async Python (`httpx`) hitting live OpenFEMA v2 \[cite: \], USGS 3DEP EPQS \[cite: \], and pre-indexed Parquet/DuckDB slices for NOAA Atlas 14/15 \[cite: \], LANDFIRE \[cite: \], and USGS HAND. | Apache Sedona \+ PostGIS \+ Apache Iceberg partitioned by `state_fips` and Uber H3 Res 6/11/13. |
| **Parcel Buffer & CV Inspector** | **Builder 1 (Backend)** | `Shapely`/`GeoPandas` generates concentric rings (0\\text{–}5\\text{ ft}, 5\\text{–}30\\text{ ft}, 30\\text{–}100\\text{ ft}) \[cite: \]; multimodal Vision API \+ ONNX segmentation extracts roof class, canopy overhang, and sheds. | Dedicated Triton Inference Server running custom ViT \+ Mask R-CNN on 7.5cm Nearmap WMTS & 30cm Pléiades Neo tiles. |
| **Actuarial & Credibility Core** | **Builder 1 (Backend)** | Pure Python/NumPy implementation of ZIP Frequency \+ USACE/GPD Severity \[cite: \] \+ Bühlmann-Straub Credibility \[cite: \] \+ 300–850 Sigmoid \+ Monotonicity unit test. | C++/Rust actuarial kernel with Consortium CDA federated likelihood calibration \[cite: \]. |
| **Enterprise & Agentic Integration** | **Builder 1 (Backend)** | FastAPI REST endpoints (`/v1/parcel/score`, `/v1/parcel/simulate`) \+ Python `FastMCP` server exposing 4 tools for Guidewire Underwriting Assistant \[cite: \]. | Guidewire Cloud Integration Gateway (Apache Camel), IDM storage, PricingCenter BYOM, and Gosu rules \[cite: \]. |
| **Copilot App Shell & State** | **Builder 2 (Frontend)** | Next.js 15 (App Router, TypeScript, Tailwind CSS, Shadcn UI) with instant Scenario Switcher (LA Flood, CA WUI, Escondido Suburb) and live API toggle. | Multi-tenant Enterprise SSO (Okta/SAML) embedded via Guidewire Jutro micro-frontend / PCF iframe \[cite: \]. |
| **2D/3D Geospatial Canvas** | **Builder 2 (Frontend)** | Mapbox GL JS / Deck.gl rendering parcel boundaries, building footprint, Zone 0/1/2 concentric rings, CV anomaly bounding boxes, and a Flood Freeboard Cross-Section widget \[cite: \]. | Vector tile server (Martin/Tippecanoe) streaming nationwide H3 hex grids and 3D LiDAR point clouds \[cite: \]. |
| **Counterfactual ROI & Audit UI** | **Builder 2 (Frontend)** | Interactive 300–850 FICO-style gauge, Bühlmann-Straub credibility bar, live Mitigation Action Plan toggles \[cite: \], and NY DFS / CA 10 CCR § 2644.9 audit drawer \[cite: \]. | Automated PDF rate-filing exhibit generator (FCHLPM Forms M-1, S-1, A-1) & Zillow/Redfin consumer widget \[cite: \]. |
| **HITL & Mobile Self-Inspect** | **Builder 2 (Frontend)** | Guidewire UnderwritingCenter escalation banner (`HITL_TRIGGER_01` to `04`) \+ QR-code mobile web capture view with GPS/LiDAR check \[cite: \]. | Cryptographically attested iOS/Android RoomPlan \+ RTK-GPS WebRTC verification flow. |

## 2\. Monorepo Directory Structure

Set up a single Git repository so both builders can work in isolated directories (`/backend` for Builder 1, `/frontend` for Builder 2\) while sharing `/contracts`:

resiliscore/ ├── contracts/ │ ├── parcel\_score\_schema.json \# Canonical JSON Schema locked at Minute 15 │ └── golden\_scenarios.json \# Deterministic data for Scenarios 1, 2, and 3 ├── backend/ \# BUILDER 1 WORKSPACE (Python 3.11+ / FastAPI) │ ├── app/ │ │ ├── main.py \# FastAPI app, CORS, latency middleware │ │ ├── models/schemas.py \# Pydantic v2 models matching contract │ │ ├── ingestion/ │ │ │ ├── openfema.py \# Live FimaNfipClaims v2 client │ │ │ ├── usgs\_3dep.py \# Live USGS EPQS client \+ LiDAR FFE delta\_h │ │ │ └── rasters.py \# NOAA Atlas 15, LANDFIRE FBFM40, USGS HAND lookup │ │ ├── vision/ │ │ │ ├── parcel\_rings.py \# Shapely EPSG:5070 Zone 0/1/2 ring generator │ │ │ └── cv\_inspector.py \# Aerial segmentation & confidence scorer │ │ ├── actuarial/ │ │ │ ├── compound\_model.py \# ZIP Frequency \+ USACE Depth-Damage \+ GPD Tail │ │ │ ├── credibility.py \# Bühlmann-Straub Z\_ij \+ 300-850 Sigmoid │ │ │ ├── optimizer.py \# Counterfactual Mitigation ROI calculator │ │ │ └── compliance.py \# Monotonicity proof \+ NY DFS / CA 2644.9 audit │ │ └── integrations/ │ │ ├── guidewire\_mock.py \# Mock PolicyCenter / ClaimCenter REST & IDM │ │ └── mcp\_server.py \# Model Context Protocol (MCP) server for agents │ ├── tests/test\_monotonicity.py \# Automated actuarial compliance test suite │ └── requirements.txt └── frontend/ \# BUILDER 2 WORKSPACE (Next.js 15 / TypeScript) ├── src/ │ ├── types/resiliscore.ts \# TypeScript interfaces matching contract │ ├── data/goldenScenarios.ts \# Instant local fallback & demo scenarios │ ├── components/ │ │ ├── HeaderScenarioBar.tsx \# Address search \+ 3 Golden Scenario pills │ │ ├── ParcelMapCanvas.tsx \# Mapbox/Deck.gl Zone 0/1/2 & CV bounding boxes │ │ ├── FreeboardCrossSection.tsx \# Visual SVG diagram of FFE vs BFE & HAND │ │ ├── ScoreGaugeCard.tsx \# 300-850 gauge \+ Bühlmann-Straub Z\_ij meter │ │ ├── MitigationDrawer.tsx \# Interactive 10 CCR 2644.9 & FORTIFIED toggles │ │ ├── HitlWorkbenchModal.tsx \# UnderwritingCenter HITL triggers \+ Mobile QR │ │ └── RegulatoryAuditTab.tsx \# NY DFS CL7 & CA 2644.9 explainability view │ └── app/page.tsx \# Main Underwriting Copilot single-pane cockpit └── package.json

## 3\. Step 0: The Shared Contract Prompt (Run Together at Minute 0\)

Use this prompt first to generate the shared data contract and the 3 deterministic golden demo scenarios so Builder 1 and Builder 2 can work completely independently for the next 12 hours.

### Prompt 0: Shared API Schema & Golden Scenarios Generator

You are a Principal Insurtech Architect. Generate two files that form the strict interface contract between our FastAPI backend and Next.js 15 frontend for "SaveMyHome" (a 300–850 Property Catastrophe Resilience Score and Underwriting Copilot):

1. `backend/app/models/schemas.py` (Pydantic v2 models)  
2. `frontend/src/types/resiliscore.ts` (Exact matching TypeScript interfaces)  
3. `contracts/golden_scenarios.json` (Pre-populated realistic payload data for our 3 live demo scenarios)

### REQUIRED DATA CONTRACT STRUCTURE (`ParcelScoreResponse`):

* `request_id`: UUID string and `processing_time_ms`: float  
* `parcel_identity`:  
  * `apn_uid`: string (14-digit Assessor Parcel Number)  
  * `address`: string, `county_fips`: string, `state`: "LA" | "CA" | "FL"  
  * `h3_res11`: string, `h3_res13`: string  
  * `rcv_usd`: float (Replacement Cost Value), `year_built`: int  
  * `centroid`: `[lng, lat]`  
  * `geometries`: GeoJSON FeatureCollection containing `parcel_polygon`, `building_footprint`, `zone_0_ring_0_5ft`, `zone_1_ring_5_30ft`, `zone_2_ring_30_100ft`, and `cv_detections` (bounding polygons for overhanging canopy or detached sheds).  
* `public_hazard_layer`:  
  * `fema_flood_zone`: string, `bfe_ft_navd88`: float | null  
  * `usgs_lag_ft`: float, `est_ffe_ft`: float, `freeboard_delta_h_ft`: float  
  * `hand_rel_elev_ft`: float, `twi_index`: float  
  * `noaa_atlas15_p24h_100yr_in`: float, `atlas15_cmip6_mult`: float  
  * `landfire_fbfm40_code`: string, `slope_deg`: float, `wui_class`: string  
  * `openfema_tract_claim_count`: int, `openfema_tract_mean_lcr`: float  
* `private_verification_layer`:  
  * `cv_roof_class`: "CLASS\_A\_FORTIFIED" | "CLASS\_A\_IMPACT\_4" | "CLASS\_A\_ASPHALT" | "WOOD\_SHAKE\_UNRATED"  
  * `cv_confidence`: float (0.0 to 1.0)  
  * `cv_overhang_ft`: float, `cv_zone0_clear`: bool, `cv_zone1_no_shed`: bool, `cv_enclosed_eaves`: bool, `cv_ember_vents`: bool  
  * `elev_cert_verified`: bool, `ibhs_fortified_tier`: "ROOF" | "SILVER" | "GOLD" | "NONE"  
  * `ibhs_wph_tier`: "BASE" | "PLUS" | "NONE"  
  * `iot_shutoff_active`: bool, `unpermitted_footprint_delta_sqft`: float  
* `actuarial_breakdown`:  
  * `tract_prior_lcr`: float (e.g., 0.0185 for 185 bps)  
  * `parcel_raw_lcr`: float  
  * `credibility_weight_z`: float (Bühlmann-Straub Z in \[0, 1\])  
  * `posterior_lcr`: float  
  * `expected_annual_loss_usd`: float  
  * `peril_split`: list of `{peril: "FLOOD" | "WILDFIRE" | "WIND_HAIL", zip_immunity_pi: float, expected_freq_n: float, expected_sev_s: float, peril_aal_usd: float}`  
  * `resili_score`: int (300 to 850\)  
  * `baseline_macro_score`: int (300 to 850 based on tract\_prior\_lcr alone)  
  * `underwriting_tier`: "TIER\_1\_AUTO\_BIND" | "TIER\_2\_CONDITIONAL" | "TIER\_3\_DECLINE\_ESCALATE"  
  * `statutory_discount_pct`: float, `annual_base_premium_usd`: float, `annual_discounted_premium_usd`: float  
* `prescriptive_mitigations`: list of objects:  
  * `action_id`: string, `title`: string, `peril`: string, `statutory_authority`: string  
  * `gross_capex_usd`: float, `grant_subsidy_usd`: float, `net_capex_usd`: float  
  * `lcr_delta_bps`: float, `score_delta_pts`: int, `annual_premium_savings_usd`: float  
  * `payback_years`: float, `resale_value_bump_pct`: float, `currently_applied`: bool  
* `hitl_status`:  
  * `escalated`: bool  
  * `trigger_code`: "NONE" | "HITL\_TRIGGER\_01\_SENSOR\_DIVERGENCE" | "HITL\_TRIGGER\_02\_UNPERMITTED\_ADDITION" | "HITL\_TRIGGER\_03\_HIGH\_TIV" | "HITL\_TRIGGER\_04\_BOUNDARY\_CONFLICT"  
  * `trigger_reason`: string | null  
  * `recommended_underwriter_action`: string | null  
* `regulatory_compliance`:  
  * `monotonicity_verified`: bool  
  * `ny_dfs_cl7_ecdis_free`: bool  
  * `ca_2644_9_factors`: dict mapping all 12 Cat A, B1, B2 factors to bool  
  * `dataset_vintages`: dict of source names to version strings

### POPULATE `golden_scenarios.json` WITH THESE 3 EXACT SCENARIOS:

1. `SCENARIO_1_LA_FLOOD`: "412 Bayou Rd, Jefferson Parish, LA" \-\> RCV $450,000,FEMAZoneAE(BFE9.0ft),USGSLAG7.2ft,1mLiDARFFE13.2ft(+4.2ftfreeboard),HAND+6.4ft,IBHSFORTIFIEDRoof($10k LA grant), Tract Prior LCR 185 bps (Baseline Score 430\) \-\> Credibility Z \= 0.94, Posterior LCR \= 24 bps (\$1,080 AAL), Final SaveMyHome \= 765 (TIER\_1\_AUTO\_BIND, 38% discount).  
2. `SCENARIO_2_CA_WUI`: "1840 Canyon Crest Dr, Altadena, CA" \-\> RCV \$850,000, Pre-2008 home (1974), LANDFIRE SH7 chaparral, 28-deg slope, Wood shake roof, 16.5 ft Zone 0 canopy overhang, Zone 1 shed at 18 ft. Tract Prior LCR 210 bps, Parcel Posterior LCR 245 bps \-\> SaveMyHome \= 385 (TIER\_3\_DECLINE\_ESCALATE). Include 3 toggleable mitigations (Zone 0/1 clearance: \$1,800 \-\> \+65 pts; Ember vents \+ eaves: \$3,200 \-\> \+55 pts; IBHS WPH Class A roof: \$14,500 \-\> \+125 pts) that lift score from 385 to 630 (TIER\_2\_CONDITIONAL) and save \$2,140/yr.  
3. `SCENARIO_3_ESCONDIDO_HITL`: "742 Dixon Trail, Escondido, CA" \-\> RCV \$720,000, IBHS Wildfire Prepared Home Plus, Class 4 hail roof, Zone 0 clear, Flo by Moen active \-\> Z \= 0.97, Posterior LCR \= 18 bps, SaveMyHome \= 815 (TIER\_1\_AUTO\_BIND, 30% wildfire & 12.4% hail discount). Include a toggleable flag `simulate_unpermitted_delta` that injects a \+240 sq ft unpermitted Zone 1 structure and fires `HITL_TRIGGER_02_UNPERMITTED_ADDITION`.

## 4\. Builder 1 Prompts: Backend, Spatial Pipeline, Actuarial Engine & MCP

**Builder 1** owns `/backend`. Feed these four prompts sequentially into your coding assistant.

### Prompt 1A: Public Spatial & Federal API Ingestion Engine

You are a Senior Geospatial & Backend Engineer building `backend/app/ingestion/` for SaveMyHome in Python 3.11+ using `httpx`, `shapely`, and `duckdb`.

Implement an asynchronous ingestion service (`SpatialIngestionEngine`) that takes `(address, lat, lng, county_fips, state)` and executes parallel non-blocking fetches with a strict 2.5-second timeout and deterministic fallback to local cache (`golden_scenarios.json`) so network glitches never fail a request:

1. `openfema.py`:  
   * Query the live FEMA OpenFEMA API v2 endpoint `[https://www.fema.gov/api/open/v2/FimaNfipClaims](https://www.fema.gov/api/open/v2/FimaNfipClaims)` using OData filters: `?$filter=(countyCodeeq'count{y}_{f}ips'andyearOfLossge2010)&$top=1000&$inlinecount=allpages`.  
   * Extract `amountPaidOnBuildingClaim`, `amountPaidOnContentsClaim`, `baseFloodElevation`, `lowestFloorElevation`, `lowestAdjacentGrade`, `elevationDifference`, `ratedFloodZone`, and `elevationCertificateIndicator`.  
   * CRITICAL DATA HYGIENE RULE: If `baseFloodElevation` is null or missing on any claim record, explicitly set `elevationDifference = None` (never zero-impute missing BFE).  
   * Compute county/tract empirical prior loss cost parameters `(alpha_j, beta_j)` for our Gamma prior.  
2. `usgs_3dep.py`:  
   * Query the live USGS 3DEP Elevation Point Query Service (EPQS) at `[https://epqs.nationalmap.gov/v1/json?x=](https://epqs.nationalmap.gov/v1/json?x=){lng}&y={lat}&wkid=4326&units=Feet`.  
   * Extract bare-earth Lowest Adjacent Grade (`usgs_lag_ft`), add foundation height offset (`delta_z_foundation`) to compute First Floor Elevation (`est_ffe_ft`), and compute continuous relative freeboard `freeboard_delta_h_ft = est_ffe_ft - bfe_ft_navd88`.  
3. `rasters.py`:  
   * Implement a fast lookup service for NOAA PFDS Atlas 14/15 100-year 24-hour rainfall depth (`noaa_atlas15_p24h_100yr_in`) with CMIP6 non-stationary multiplier (`atlas15_cmip6_mult`), LANDFIRE 40 Scott & Burgan Fuel Model code (`landfire_fbfm40_code`) and topographic slope (`slope_deg`), and USGS Height Above Nearest Drainage (`hand_rel_elev_ft`) and Topographic Wetness Index (`twi_index`).  
   * Stamp every response with exact dataset vintage metadata (e.g., `"USGS_3DEP": "2025-05-01"`, `"NOAA_PFDS": "Atlas15_Vol1_Prelim_2026"`, `"OpenFEMA": "FimaNfipClaims_v2"`).

### Prompt 1B: Concentric Buffer Geometry & Computer Vision Inspector

You are a Computer Vision & Geospatial Engineer building `backend/app/vision/` for SaveMyHome.

1. `parcel_rings.py`:  
   * Given a building footprint polygon `(lng, lat)` coordinates, project the geometry into an equal-area/feet projection (or local UTM meters converted to feet) using `shapely` and `pyproj`.  
   * Generate the three exact statutory concentric defensible space ring polygons required by California Regulation 10 CCR § 2644.9, CA PRC § 4291, and IBHS Wildfire Prepared Home:  
     * `zone_0_ring_0_5ft`: `footprint.buffer(5 ft).difference(footprint)` (Immediate Noncombustible Buffer)  
     * `zone_1_ring_5_30ft`: `footprint.buffer(30 ft).difference(footprint.buffer(5 ft))` (Immediate Surroundings)  
     * `zone_2_ring_30_100ft`: `footprint.buffer(100 ft).difference(footprint.buffer(30 ft))` (Extended Defensible Space)  
   * Reproject all rings back to WGS84 (`EPSG:4326`) GeoJSON FeatureCollection so the frontend Mapbox/Deck.gl canvas can render them directly.  
2. `cv_inspector.py`:  
   * Implement `AerialCVInspector` that evaluates aerial/satellite orthophotos (and supports structured Vision LLM / ONNX Mask R-CNN inference over uploaded property images) to extract:  
     * `cv_roof_class` ("CLASS\_A\_FORTIFIED", "CLASS\_A\_IMPACT\_4", "CLASS\_A\_ASPHALT", "WOOD\_SHAKE\_UNRATED")  
     * `cv_overhang_ft` (feet of tree canopy encroaching into `zone_0_ring_0_5ft`)  
     * `cv_zone0_clear` (boolean: zero combustible mulch/vegetation in 0–5ft)  
     * `cv_zone1_no_shed` (boolean: zero detached combustible sheds/structures within 30ft)  
     * `cv_confidence` (float in `[0, 1]`)  
     * `unpermitted_footprint_delta_sqft` (difference between CV-segmented building polygon area and tax assessor footprint area).  
   * Return GeoJSON bounding polygons (`cv_detections`) for any detected tree overhang in Zone 0 or combustible shed in Zone 1 so the UI can highlight them in red on the map.

### Prompt 1C: Actuarial Compound Risk, Bühlmann-Straub Credibility & Counterfactual Optimizer

You are a Fellow of the Casualty Actuarial Society (FCAS) and Principal Python Architect building `backend/app/actuarial/` for SaveMyHome. Every equation must be mathematically exact, deterministic, and compliant with NAIC ASOP Nos. 12, 25, 38, and 56, NY DFS Insurance Circular Letter No. 7, California 10 CCR § 2644.9, and Florida FCHLPM Standard G-4.

Implement the following four modules plus a unit test suite:

1. `compound_model.py` (Two-Part Compound Frequency-Severity Engine):  
   * Total Expected Annual Loss across perils P \= {FLOOD, WILDFIRE, WIND\_HAIL}: `AAL_i = sum_p ( E[N_{i,p}] * E[S_{i,p} | N_{i,p} > 0] * RCV_i )`  
   * Frequency `E[N_{i,p}]`: Zero-Inflated Poisson (ZIP) GLM where `E[N_{i,p}] = (1 - pi_{i,p}) * lambda_{i,p}`:  
     * Flood: `logit(pi_FL) = gamma_0 + gamma_1 * max(0, delta_h) + gamma_2 * H_HAND + gamma_3 * I_backflow` and `ln(lambda_FL) = beta_0 + beta_1 * D_100 - beta_2 * TWI - beta_3 * delta_h - beta_4 * I_elev_bldg` (with all gamma\_k, beta\_k \> 0).  
     * Wildfire: `logit(pi_WF) = eta_0 + eta_1 * I_Zone0 + eta_2 * I_ClassA + eta_3 * I_vents + eta_4 * I_no_shed` and `ln(lambda_WF) = delta_0 + delta_1 * F_40 + delta_2 * Slope + delta_3 * O_canopy - delta_4 * I_Firewise` (with all eta\_k, delta\_k \> 0).  
   * Severity `E[S_{i,p} | N > 0]`: Spliced distribution combining the USACE (2000) One-Story Residential Depth-Damage Gompertz-Logistic curve in the body (`s <= u_p = 0.50`, initiating at water depth `d = -2.0 ft` with 0% damage, \~13.4% at `0 ft`, \~49.0% at `+4.0 ft`, `L_max = 0.88`, `k_DDF = 0.36`, `d_0 = 2.85`, attenuated by `exp(-psi^T * m)`) with a Truncated Generalized Pareto Distribution (GPD) on `[u_p, 1.0]` with scale `sigma(m) = sigma_0 * exp(-theta^T * m)`.  
2. `credibility.py` (Bühlmann-Straub Empirical Bayes & 300–850 Normalization):  
   * Given census-tract prior mean `mu_0_tract = alpha_j / beta_j`, within-parcel process variance `sigma^2` (EVPV), and between-parcel heterogeneity variance `tau^2` (VHM), compute Bühlmann's `k = sigma^2 / tau^2`.  
   * Sum inverse-variance verification precision weights `w_ij = sum_m w_{ij,m}` across verified channels (1m LiDAR, Aerial CV weighted by `cv_confidence`, NFIP Elevation Certificate, IBHS Registry, IoT Smart Valve).  
   * Compute Credibility Factor `Z_ij = w_ij / (w_ij + k)` in `[0, 1]` and Posterior Loss Cost Ratio: `LCR_post = Z_ij * LCR_parcel + (1 - Z_ij) * mu_0_tract`.  
   * Map `LCR_post` to the 300–850 SaveMyHome scale using the exact log-logistic sigmoid anchored at `LCR_0 = 0.0085` (85 bps \-\> 575 midpoint) and slope `kappa = 1.15`: `SaveMyHome = 300 + round( 550 / (1 + (LCR_post / 0.0085)^1.15) )`.  
   * Classify tiers: `720–850` \-\> `TIER_1_AUTO_BIND`, `580–719` \-\> `TIER_2_CONDITIONAL`, `300–579` \-\> `TIER_3_DECLINE_ESCALATE`.  
3. `optimizer.py` (Counterfactual Prescriptive Mitigation Engine):  
   * Accept a set of toggled mitigation IDs (`zone0_clear`, `ember_vents_eaves`, `ibhs_wph_plus`, `ibhs_fortified_roof`, `smart_water_shutoff`) and recompute `LCR_post`, `SaveMyHome`, statutory premium discounts (up to 30% wildfire / 55% wind), state grant offsets (\$10,000 LA/AL FORTIFIED grants), net payback period in years, and \+6.8% resale value bump.  
4. `compliance.py` & `tests/test_monotonicity.py`:  
   * Implement a numerical Jacobian check verifying `d(SaveMyHome)/d(m_k) > 0` across every mitigation variable `m_k` and verifying zero socio-economic ECDIS variables are present.  
   * Implement the 4 deterministic Human-in-the-Loop (HITL) escalation triggers (`|delta_z_LiDAR - delta_z_Cert| > 1.5 ft` or `cv_confidence < 0.85`; `unpermitted_footprint_delta_sqft > 150`; `RCV > $5,000,000`; or boundary score `[570, 590]`).

### Prompt 1D: FastAPI Endpoints, Guidewire Cloud Mock & MCP Server

You are a Staff Enterprise Systems Architect building `backend/app/main.py` and `backend/app/integrations/` for SaveMyHome.

1. `main.py` (FastAPI Service):  
   * Expose `POST /v1/parcel/score` (accepts address or `scenario_id`, runs the pipeline, returns `ParcelScoreResponse`).  
   * Expose `POST /v1/parcel/simulate-mitigation` (accepts `apn_uid` \+ list of toggled `action_ids`, returns updated `ParcelScoreResponse` in \< 50ms).  
   * Expose `POST /v1/hitl/verify-override` (accepts mobile self-inspection verification or underwriter approval, updates `cv_confidence = 0.99`, recalculates `Z_ij`, and upgrades the binding status).  
2. `guidewire_mock.py` (Guidewire PolicyCenter, IDM & ClaimCenter Simulator):  
   * Expose `POST /v1/guidewire/submissions/{submission_id}/quote` and `/issue` simulating a Guidewire Integration Gateway & PricingCenter BYOM webhook.  
   * Return a realistic Guidewire REST response payload showing `ResiliScore_Ext` data model extension fields, Integration Data Manager (IDM) document ID, applied Gosu rule IDs (e.g., `CA_CCR_2644_9_CAT_B1_B2`, `LA_FORTIFIED_ROOF_CREDIT`), and auto-bind policy number.  
3. `mcp_server.py` (Model Context Protocol Server):  
   * Using the Python `mcp` SDK (`FastMCP`), expose 4 deterministic tools so AI agents (such as Guidewire Underwriting Assistant or any MCP client) can invoke SaveMyHome natively:  
     * `get_parcel_resiliscore(address: str)`  
     * `verify_zone0_clearance(apn_uid: str)`  
     * `query_usgs_freeboard(lat: float, lng: float)`  
     * `simulate_mitigation_roi(apn_uid: str, actions: list[str])`

## 5\. Builder 2 Prompts: Frontend, Map Canvas, Copilot UI & HITL Flows

**Builder 2** owns `/frontend`. Feed these four prompts sequentially into your coding assistant to build a high-impact, institutional-grade Insurtech UI.

### Prompt 2A: Next.js 15 Enterprise Underwriting Copilot Cockpit & Scenario Switcher

You are a Staff Frontend Architect & Insurtech Product Designer building the SaveMyHome Underwriting Copilot in Next.js 15 (App Router, TypeScript, Tailwind CSS, Lucide Icons, Framer Motion).

Create a sleek, institutional-grade dark/light adaptive single-pane cockpit (`src/app/page.tsx` and `src/components/HeaderScenarioBar.tsx`) modeled after a Bloomberg Terminal meets Guidewire UnderwritingCenter:

1. Top Navigation & Scenario Bar (`HeaderScenarioBar.tsx`):  
   * Brand header: "SaveMyHome™ | AI-Native Property Catastrophe Resilience Score (300–850) & Underwriting Copilot" with a live badge showing `Guidewire Cloud PolicyCenter & MCP Connected` and processing latency (`3.1s | $1.75 Consortium Tier`).  
   * Address / APN Autocomplete search input (`"Enter Parcel Address or 14-Digit APN..."`).  
   * Quick-Load Golden Demo Scenario Pills (1-click instant switching for the live hackathon demo, backed by `goldenScenarios.ts` with optional live backend API fetch):  
     * `[Scenario 1: Coastal Flood Freeboard — 412 Bayou Rd, LA (430 -> 765 Auto-Bind)]`  
     * `[Scenario 2: WUI Wildfire Unmitigated — 1840 Canyon Crest Dr, CA (385 -> 630 Remediate)]`  
     * `[Scenario 3: IBHS Plus + HITL Guardrail — 742 Dixon Trail, Escondido, CA (815 + HITL Check)]`  
   * Mode Switcher Tabs in the main workspace:  
     * `Tab 1: Underwriting Copilot & Spatial Twin`  
     * `Tab 2: Prescriptive Mitigation & Grant ROI Simulator`  
     * `Tab 3: Regulatory Filing & Audit Dossier (NY DFS CL7 / CA 2644.9 / FL FCHLPM)`

### Prompt 2B: Geospatial Concentric Ring Map Canvas & Flood Freeboard Cross-Section

You are a Geospatial Data Visualization Engineer building `src/components/ParcelMapCanvas.tsx` and `src/components/FreeboardCrossSection.tsx` for SaveMyHome.

1. `ParcelMapCanvas.tsx`:  
   * Build an interactive satellite/aerial parcel map view (using `react-map-gl` / Mapbox GL JS or an interactive high-res SVG/Canvas satellite orthophoto viewport with smooth zoom/pan that works even without an external Mapbox token).  
   * Render toggleable geospatial vector overlays from `ParcelScoreResponse.geometries`:  
     * `building_footprint`: crisp cyan polygon outline (`#12B5CB`).  
     * `zone_0_ring_0_5ft`: 0–5 ft Immediate Noncombustible Buffer ring (colored red `#D93025` if `cv_zone0_clear == false`, emerald `#1E8E3E` if clear).  
     * `zone_1_ring_5_30ft`: 5–30 ft Defensible Space ring (amber/emerald based on `cv_zone1_no_shed`).  
     * `zone_2_ring_30_100ft`: 30–100 ft Extended Fuel Reduction ring (dashed outline).  
     * `cv_detections`: pulsing red Vision Transformer bounding boxes with floating telemetry tags (e.g., `"ViT Mask R-CNN: 16.5 ft Eucalyptus Canopy Overhang in Zone 0 [Conf: 0.96]"`, `"Detached Wood Shed @ 18 ft in Zone 1"`, or `"Unpermitted +240 sq ft Footprint Delta"`).  
   * When the user toggles mitigations in the Prescriptive Mitigation Drawer (e.g., clearing Zone 0 overhang or removing the Zone 1 shed), animate the red CV bounding boxes disappearing and the Zone 0/1 rings turning emerald green in real time.  
2. `FreeboardCrossSection.tsx`:  
   * Build a clean architectural elevation cross-section diagram beside/below the map that visually explains why macro flood scores fail:  
     * Plot bare-earth Lowest Adjacent Grade (`usgs_lag_ft`), FEMA Base Flood Elevation (`bfe_ft_navd88` water line), 100-year NOAA Atlas 15 storm surge/pluvial depth, and the structure's USGS 3DEP 1m LiDAR First Floor Elevation (`est_ffe_ft`).  
     * Highlight the vertical Freeboard arrow `Delta h = +4.2 ft above BFE` and the USACE (2000) Depth-Damage curve shift showing how \+4.2 ft of freeboard drops expected structural damage from 49.0% to \<2.0%.

### Prompt 2C: 300–850 Score Gauge, Bühlmann-Straub Credibility Meter & Mitigation ROI Drawer

You are a Senior Fintech/Insurtech UI Engineer building `src/components/ScoreGaugeCard.tsx` and `src/components/MitigationDrawer.tsx`.

1. `ScoreGaugeCard.tsx`:  
   * Render a dramatic FICO-style 300–850 SaveMyHome gauge showing BOTH:  
     * `Macro Census-Tract Prior Score` (e.g., `430 - Tier 3 Decline`, showing what First Street / legacy ZIP-code models see)  
     * `Verified Parcel SaveMyHome` (e.g., `765 - Tier 1 Instant Auto-Bind`, with an animated delta badge `+335 pts from Parcel Verification`).  
   * Render the **Bühlmann-Straub Bayesian Credibility Breakdown Bar**:  
     * Display the exact formula `LCR_post = Z * LCR_parcel + (1 - Z) * mu_tract` with live values (`Z = 0.94`, `Tract Prior = 185 bps`, `Parcel Raw = 14 bps`, `Posterior = 24 bps`, `AAL = $1,080/yr`).  
     * Show the individual precision weights `w_{ij,m}` contributing to `Z` (USGS 1m LiDAR: Verified, OpenFEMA Elevation Cert: Verified, Nearmap 7.5cm CV: 96% Conf, IBHS Registry: Verified, Flo IoT Valve: Active).  
   * Include a primary CTA button:  
     * For Tier 1 (`720–850`): Green `"Auto-Bind in Guidewire PolicyCenter (-38% Statutory Credit)"` button that fires a live webhook modal showing the generated Guidewire Policy Number and IDM JSON receipt.  
     * For Tier 2 (`580–719`): Amber `"Issue 60-Day Conditional Bind with Action Plan"` button.  
     * For Tier 3 (`300–579`): Red `"Launch Prescriptive Mitigation Simulator to Rescue from FAIR Plan"` button.  
2. `MitigationDrawer.tsx`:  
   * Build an interactive counterfactual simulator where the underwriter, broker, or homeowner can toggle individual retrofits on/off:  
     * Zone 0 (0–5ft) Noncombustible Buffer \+ PRC § 4291 Pruning (`$1,800 CapEx` | `+65 pts` | `-$680/yr` | `2.6 yr payback`)  
     * 1/4-Inch Ember-Resistant Mesh Vents \+ Enclosed Eaves (`$3,200 CapEx` | `+55 pts` | `-$540/yr` | `5.9 yr payback`)  
     * IBHS Wildfire Prepared Home Plus Upgrade (`$15,000 CapEx` | `+150 pts` | `-$1,450/yr` | `1.4 yr rebuild delta payback`)  
     * IBHS FORTIFIED Roof \+ Class 4 Shingles (`$12,500 Gross` | `-$10,000 LA/AL State Grant` \-\> `$2,500 Net CapEx` | `+115 pts` | `-$1,250/yr` | `2.0 yr net payback` | `+6.8% Home Resale Value`).  
   * As checkboxes are toggled, smoothly animate the SaveMyHome needle, Posterior LCR, Net Out-of-Pocket CapEx, Annual Premium Savings, and Map Zone 0/1 ring colors.

### Prompt 2D: HITL Escalation Workbench, Mobile Self-Inspection & Regulatory Audit Dossier

You are a Lead Enterprise Workflow Engineer building `src/components/HitlWorkbenchModal.tsx` and `src/components/RegulatoryAuditTab.tsx`.

1. `HitlWorkbenchModal.tsx` (Human-in-the-Loop Protocol):  
   * In Scenario 3 (Escondido), provide a prominent toggle `"Simulate Satellite Change-Detection Alert (+240 sq ft Unpermitted Zone 1 Structure)"`.  
   * When activated, immediately pause straight-through auto-binding and trigger a high-visibility amber/red banner: `HITL_TRIGGER_02: Unpermitted Structural Addition Detected (+240 sq ft > 150 sq ft threshold in Zone 1). Straight-Through Processing Paused — Escalated to Guidewire UnderwritingCenter.`  
   * Provide two resolution actions in the workbench modal:  
     * `"Request 60-Second Cryptographic Smartphone Verification"`: Opens a simulated mobile phone viewport showing a geofenced RTK-GPS (`Footprint Match: Verified`) \+ iPhone LiDAR depth scan confirming the structure is an open noncombustible aluminum pergola, allowing the underwriter to click `"Verify & Restore Tier 1 Auto-Bind (Score: 815)"`.  
     * `"Apply Unpermitted Structure Loading (+35 bps LCR)"`: Adjusts RCV and routes to Conditional Bind.  
2. `RegulatoryAuditTab.tsx` (State Regulator Rate-Filing Proof):  
   * Render a clean actuarial compliance dashboard proving why CDI, NY DFS, and FL OIR approve SaveMyHome:  
     * **Strict Mathematical Monotonicity Matrix**: Green checkmarks showing live partial derivatives `d(SaveMyHome)/d(m_k) > 0` for all physical mitigation variables.  
     * **NY DFS Insurance Circular Letter No. 7 (July 2024\) Audit**: Shows `Socio-Economic / Credit / Behavioral ECDIS Features Used: 0`, Step 1 BISG Adverse Impact Ratio Pass status, and downloadable Article 24 Consumer Adverse Action / Mitigation Notice.  
     * **California 10 CCR § 2644.9 Checklist**: Visual grid of all 12 mandatory Category A (Community), Category B1 (Immediate Surroundings), and Category B2 (Structure Hardening) wildfire rating factors with parcel pass/fail status.  
     * **Florida FCHLPM Standard G-4 Independence & Data Vintages**: Shows strict separation of Meteorology (NOAA Atlas 15 / USGS), Vulnerability (USACE / IBHS), and Actuarial (Bühlmann-Straub) modules with exact dataset timestamps.

## 6\. Hackathon Execution Timeline & Sync Checkpoints

Follow this synchronization schedule so both builders stay aligned without blocking each other:

| Time Block | Builder 1 (Backend, Actuarial & MCP) | Builder 2 (Frontend, Map Canvas & Copilot UI) | Joint Sync / Milestone |
| ----- | ----- | ----- | ----- |
| **Phase 1 (Hours 0–1)** | Run **Prompt 0**. Initialize FastAPI `/backend`, Pydantic models, and return `golden_scenarios.json` from `POST /v1/parcel/score`. | Run **Prompt 0**. Initialize Next.js 15 `/frontend`, TypeScript interfaces, and wire `goldenScenarios.ts` into global state. | **Sync 1:** Verify `curl localhost:8000/v1/parcel/score` matches `resiliscore.ts` 100%. |
| **Phase 2 (Hours 1–5)** | Run **Prompt 1C**. Build the exact ZIP \+ USACE/GPD \+ Bühlmann-Straub Z\_{ij} \+ 300–850 sigmoid engine and `/v1/parcel/simulate-mitigation`. | Run **Prompt 2A** & **Prompt 2C**. Build the Copilot cockpit, Scenario Switcher pills, 300–850 Gauge, Credibility bar, and Mitigation ROI Drawer. | **Sync 2:** Connect Frontend Mitigation Drawer toggles to Backend `/simulate-mitigation` endpoint. |
| **Phase 3 (Hours 5–9)** | Run **Prompt 1A** & **Prompt 1B**. Wire live OpenFEMA v2, USGS 3DEP EPQS, Shapely Zone 0/1/2 buffer ring generator, and CV bounding boxes. | Run **Prompt 2B**. Build the interactive `ParcelMapCanvas` (rendering Zone 0/1/2 rings and red CV boxes) and `FreeboardCrossSection` diagram. | **Sync 3:** Verify live Shapely GeoJSON rings and USGS EPQS elevations render accurately on the map canvas. |
| **Phase 4 (Hours 9–12)** | Run **Prompt 1D**. Build the Guidewire PolicyCenter `/quote` & `/issue` webhook simulator, monotonicity unit test, and `FastMCP` server. | Run **Prompt 2D**. Build the `HitlWorkbenchModal` (with Mobile QR self-inspect simulator), Guidewire Auto-Bind modal, and `RegulatoryAuditTab`. | **Sync 4 (Code Freeze):** Rehearse the 3-minute live pitch and click-by-click demo across Scenarios 1, 2, and 3\. |

## 7\. Long-Term Production Hardening Checklist (Post-Hackathon Roadmap)

Because the hackathon codebase enforces strict separation between **Ingestion** (`app/ingestion`), **Computer Vision** (`app/vision`), **Actuarial Pricing** (`app/actuarial`), and **Core System Delivery** (`app/integrations`), transitioning from the hackathon MVP to a Tier-1 carrier SaaS platform requires zero architectural rewrites:

1. **Spatial Feature Store Upgrade (`DuckDB` \\to `PostGIS + Apache Iceberg`):** Swap the local DuckDB/Parquet lookup in `rasters.py` for an AWS RDS PostGIS \+ Apache Sedona cluster indexed on 14-digit national `apn_uid` polygons and Uber H3 Resolution 11/13 hexagons.  
2. **Dedicated Vision Pipeline (`API/ONNX` \\to `Triton Inference Server`):** Deploy custom-trained Vision Transformer (ViT) and Mask R-CNN weights on NVIDIA Triton reading 7.5cm Nearmap WMTS and 30cm Airbus Pléiades Neo Cloud-Optimized GeoTIFFs \[cite: \].  
3. **Guidewire Cloud Marketplace Certification:** Package the `guidewire_mock.py` schemas and `mcp_server.py` tools into a certified **Guidewire Cloud Integration Framework** app utilizing the **Integration Data Manager (IDM)** for regulatory audit JSON persistence, **PricingCenter BYOM** for posterior \\widehat{\\text{LCR}}\_i ingestion, and **Guidewire Cloud Data Access (CDA)** to power the "Give-to-Get" closed-loss-run consortium flywheel \[cite: \].

SaveMyHome: Architectural and Actuarial Blueprint for an AI-Native Property Catastrophe Resilience Score and Underwriting Copilot

Section 1: System Thesis and Problem Statement

1.1 Legacy Catastrophe Model Failure Modes

The United States property and casualty (P\&C) insurance market suffers from a foundational spatial resolution mismatch: environmental hazards are modeled at the census-tract or ZIP-code level, whereas physical losses occur at the individual structure and parcel level. Legacy providers design their platforms for portfolio Probable Maximum Loss (PML) aggregation and reinsurance treaty pricing rather than point-of-sale parcel underwriting.

| Vendor / Platform | Primary Architectural Design Center | Spatial Resolution & Input Granularity | Core Underwriting Failure Mode |
| ----- | ----- | ----- | ----- |
| Moody's RMS & Verisk | Reinsurance treaty pricing, stochastic event catalogs, and solvency stress-testing. | 30m to 1km grids aggregated by postal code or census tract; relies on secondary building modifiers rarely populated in carrier policy systems. | Applies regional default assumptions when parcel mitigation fields are missing, penalizing hardened structures inside high-hazard footprints. |
| CoreLogic | Mortgage origination hazard screening, replacement cost valuation, and FEMA flood zone determination. | Parcel centroid geocoding mapped against static FEMA Flood Insurance Rate Maps (FIRMs) and coarse brush proximity buffers. | Fails to capture dynamic micro-topography (relative freeboard) or unmapped parcel-level home hardening retrofits. |
| First Street Foundation | Consumer climate risk communication and macro-environmental policy research. | 3m to 30m hazard layers (Flood, Fire, Wind Factor) scored on a 1–10 hazard severity scale without verified structural vulnerability adjustments. | Conflates environmental hazard with structural vulnerability; assigns identical 9/10 or 10/10 scores to an unmitigated 1960s wood-shake home and an adjacent IBHS-certified home. |

Empirical post-catastrophe field studies confirm that parcel-level physical engineering overrides macro-neighborhood exposure across all three primary perils:

⚬ Wildfire: Structures are overwhelmingly ignited by wind-borne embers rather than direct radiant flame fronts. In the January 2025 Palisades Fire in Los Angeles, nearly 95% of damaged or destroyed homes predated the 2008 enactment of California Building Code Chapter 7A, which mandated Class A fire-rated roofs, ember-resistant vents, and tempered multi-pane windows.

⚬ Hurricane & Wind: An Insurance Institute for Business & Home Safety (IBHS) assessment of over 4,000 structures after Category 5 Hurricane Ian found that zero buildings constructed to the modern Florida Building Code suffered wind-driven structural damage, preventing \$1 billion to \$3 billion in insured losses in a single event.

⚬ Flood: United States Army Corps of Engineers (USACE) and Federal Emergency Management Agency (FEMA) depth-damage curves operate on vertical increments of inches relative to First Floor Elevation (FFE). Adjacent parcels sharing the same census tract and 100-year rainfall grid experience opposite loss outcomes when one sits at \+2.5 ft above Base Flood Elevation (BFE) with backflow prevention valves and the neighbor sits at \-1.0 ft below BFE on a slab foundation.

1.2 Economic Breakdown, Carrier Insolvency, and Residual Market Saturation

Unable to verify parcel-level resilience at scale, primary carriers execute binary ZIP-code moratoriums and mass non-renewals, triggering adverse selection, carrier insolvencies, and extreme concentration in state-backed residual markets.

⚬ California: Proposition 103 (1988) historically forced insurers to price coverage using backward-looking 20-year loss averages while barring net reinsurance costs and forward-looking catastrophe models. Meanwhile, global property catastrophe reinsurance pricing nearly doubled post-2017, jumping 35% in 2023 alone on the Guy Carpenter Rate on Line Index. As admitted carriers retreated, the California FAIR Plan more than doubled its residential policies between 2020 and 2024 to 573,739 policies by March 2025, expanding total exposure from \$150 billion to \$645 billion (with high-wildfire-risk enrollment growing 12x faster than low-risk zones). In January 2025, the Palisades and Eaton fires caused \$20 billion to \$30 billion in industry insured losses and a \$4.8 billion claim shock to the FAIR Plan. Having paid \$914 million in the first month and \$3.5 billion in the first year, the FAIR Plan triggered Order 2025-1 (its first member carrier assessment since the 1994 Northridge earthquake), issued a \$750 million Golden Bear Re catastrophe bond in December 2025 (targeting a \$400 million second tranche in 2026), and filed for a 35.8% average rate hike for April 2026\. Restoring market equilibrium requires \$8 billion to \$10 billion in additional annual premium (a 50% to 65% market-wide rate increase) unless parcel-level physical risk is verified and mitigated.

⚬ Florida: Hurricane landfalls and litigation abuses pushed Citizens Property Insurance Corporation to a peak of 1.41 to 1.42 million policies in late 2023\. Following statutory tort and assignment-of-benefits reforms (SB 2-D, SB 2-A, HB 837, SB 7052\) and a mandatory depopulation clearinghouse, Citizens cut policies in force by 70% to 75% to 330,000–395,000 policies by early 2026 and filed for statewide average rate decreases approaching 9%. However, private take-out carriers require instant verification of roof age, FORTIFIED structural ties, and flood freeboard to avoid adverse selection when selecting policies from the clearinghouse.

⚬ Louisiana: Five hurricanes between 2020 and 2021—culminating in Category 4 Hurricane Ida (460,000+ claims, \$13.1 billion in insured payouts)—caused at least 11 property insurer insolvencies between July 2021 and late 2022\. The collapses saddled the Louisiana Insurance Guaranty Association (LIGA) with \$874 million in 15-year debt and forced \$1 billion in state bond borrowing for Louisiana Citizens Property Insurance Corporation (LCPIC). LCPIC direct written premiums surged 528.8% (from \$53.9 million in Q1–Q3 2021 to $338.8millioninQ1–Q32022),forcinga63.1%personallinesratehikeonJanuary1,2023(versus31.0%hadreinsurancestayedflat).InJune2022,privatecarriersrequested19,800of21,000LCPICdepopulationpolicies(94.2%),butagentsauthorizedonly3,947(20%)duetoworkflowfriction.Subsequent2024–2025reforms—Act3(badfaithreform),Act9(three-yearrulerepeal),Act10(30-dayfile-and-userating),andtheLouisianaFortifyHomesProgram($10,000 grants and \$10,000 tax credits for IBHS FORTIFIED roofs)—underscore the necessity of pairing regulatory reform with verified parcel hardening.

1.3 Legacy Underwriting vs. AI-Native Copilot

Legacy underwriting presents carriers with three flawed choices:

1\. Binary Territory Freezes: Declining entire 5-digit ZIP codes or census tracts, forfeiting profitable hardened risks.

2\. Manual Physical Surveys: Ordering \$250 to \$450 field inspections with 14-to-21-day turnaround cycles, destroying quote-to-bind conversion and inflating expense ratios.

3\. Unverified Self-Attestations: Granting discounts without verification, causing severe premium leakage. Milliman analyses of California Regulation 10 CCR § 2644.9 showed that carriers lacking parcel verification data suffered two-year rate adequacy erosion while awaiting California Department of Insurance (CDI) rate approvals.

SaveMyHome eliminates this trilemma via an AI-native Property Catastrophe Resilience Score (300–850 scale) and Underwriting Copilot. By fusing federal topographic/hydrological datasets with sub-decimeter computer vision, IoT telematics, and Bühlmann-Straub Bayesian credibility updating, SaveMyHome verifies parcel resilience in under 5 seconds for less than \$2.00 per API call.

Section 2: End-to-End Data Ingestion and Pipeline Architecture

2.1 Public Data Layer (Day 1 Operational Stack)

⚬ FEMA OpenFEMA API (FimaNfipClaims v2): Ingested via `https://www.fema.gov/api/open/v2/FimaNfipClaims` using deterministic pagination (`?$inlinecount=allpages&$top=1000&$skip={k*1000}`) and OData spatial filters (`&$filter=(state eq 'FL' and yearOfLoss ge 2010)`) across 2.5M+ claims and 67+ fields. Extracts county FIPS, `ratedFloodZone`, `baseFloodElevation` (ft NAVD88), `lowestFloorElevation`, `lowestAdjacentGrade`, `elevationDifference`, `elevatedBuildingIndicator`, `elevationCertificateIndicator`, `amountPaidOnBuildingClaim`, and `amountPaidOnContentsClaim`. Records with null `baseFloodElevation` have `elevationDifference` explicitly nulled to prevent zero-imputation bias.

⚬ USGS 3DEP Elevation Point Query Service (EPQS) & 1-Meter LiDAR: Queries `https://epqs.nationalmap.gov/v1/json?x={lng}&y={lat}&wkid=4326&units=Feet` and ingests 1m/10m 3D Elevation Program (3DEP) Cloud-Optimized GeoTIFFs via `py3dep`. Intersects building footprints with bare-earth Digital Terrain Models (DTM) and first-return Digital Surface Models (DSM) to determine Lowest Adjacent Grade ($LAG$), First Floor Elevation (${z}_{FF}=LAG+\Delta {z}_{foundation}$), and continuous relative freeboard $\Delta h={z}_{FF}-BFE$.

⚬ NOAA Precipitation Frequency Data Server (Atlas 14 & Atlas 15): Extracts 10-yr, 50-yr, 100-yr, and 500-yr 24-hour depth-duration-frequency (DDF) rainfall grids from the NWS Hydrometeorological Design Studies Center. Bridges NOAA Atlas 14 (Volume 12 in Sep 2024; Volume 13 in Dec 2025 using Maximum Likelihood stationary GEV) to NOAA Atlas 15 (preliminary CONUS in Sep 2026, full CONUS in Sep 2027, OCONUS in 2027–2028), which eliminates state-line discontinuities with continuous radar/mesoscale smoothing through 2022\. Ingests Atlas 15 Volume 1 (non-stationary historical baseline with Bayesian uncertainty bounds) for current rate filings and Atlas 15 Volume 2 (CMIP6 climate adjustment factors through 2100\) for multi-year mortgage and cat-bond stress testing.

⚬ USFS & LANDFIRE Fire Modeling Data: Ingests 30m multi-band 16-bit signed integer rasters for the 40 Scott and Burgan Fire Behavior Fuel Models (`FBFM40`), 13 Anderson Surface Fuel Models, Forest Canopy Base Height (`CBH`), Canopy Bulk Density (`CBD`), topographic slope, and Wildland-Urban Interface (WUI) layers.

⚬ USGS Height Above Nearest Drainage (HAND): Links 3DEP grids to NHDPlus High Resolution stream networks to compute vertical height above the nearest drainage channel (${H}_{HAND}$) and Topographic Wetness Index ($TWI$) for off-floodplain runoff accumulation.

2.2 Private Data and Computer Vision Layer (Post-Hackathon Expansion)

⚬ Aerial & Satellite Computer Vision (Nearmap, Cape Analytics, Airbus Pléiades Neo): Vision Transformer (ViT) and Mask R-CNN models process 7.5cm aerial orthophotos and 30cm daily satellite imagery across the statutory concentric buffers required by 10 CCR § 2644.9, CA PRC § 4291, and IBHS Wildfire Prepared Home:

	⚬ *Structure Envelope:* Grades Class A fire-rated vs. wood-shake roofs, UL 2218 Class 4 hail impact resistance, roof wear, enclosed eaves, and foundation elevation.

	⚬ *Zone 0 (0–5 ft Noncombustible Buffer):* Segments overhanging tree canopy perimeter (ft), combustible decking, and mulch.

	⚬ *Zone 1 (5–30 ft Immediate Surroundings):* Identifies detached combustible outbuildings (sheds, pergolas, woodpiles, propane tanks) and vertical ladder fuels.

	⚬ *Zone 2 (30–100 ft Extended Defensible Space):* Quantifies shrub and canopy fuel continuity.

⚬ Structural IoT Telematics: OAuth2 webhooks and MQTT streams from smart water shutoff valves (Flo by Moen, Phyn), monitored fire alarms, and seismic accelerometers verify daily micro-leak pressure tests and automated valve readiness.

⚬ Carrier Closed Loss Runs & IBHS Registries: Encrypted SFTP Parquet drops and Guidewire Cloud Data Access (CDA) streams ingest anonymized claim histories (`incurred_loss`, `water_line_depth`, `structural_damage_pct`) joined with verified IBHS FORTIFIED and Wildfire Prepared Home / Plus registries.

2.3 Data Harmonization Pipeline and Schema Mapping

SaveMyHome unifies point, raster, and vector layers onto a canonical 14-digit Assessor's Parcel Number (`apn_uid`), Overture/Microsoft Building Footprint (`building_id`), and Uber H3 Hierarchical Spatial Index (Resolution 11 for \~25 sq m cells; Resolution 13 for \~0.8 sq m sub-building footprints).

| Pipeline Stage | Architectural Component & Engine | Processing Logic & Spatial Transformation | Input / Output Schema Format |
| ----- | ----- | ----- | ----- |
| Stage 1: Multi-Modal Ingestion Bus | Async Python/Rust Connectors, Apache Kafka, & S3 Raw Lake | Paginates OpenFEMA REST JSON (1,000-record batches); queries USGS EPQS REST JSON; pulls NOAA Atlas 14/15 NetCDF/GeoTIFFs, LANDFIRE 16-bit GeoTIFFs, USGS HAND rasters, Nearmap WMTS tiles, and IoT webhooks. | Raw REST JSON, OGC WMTS Tiles, 16-bit Signed Integer GeoTIFF, and NetCDF4. |
| Stage 2: APN & Footprint Resolution | PostGIS & Apache Sedona Vector Engine (EPSG:5070 Albers Equal-Area) | Geocodes address; runs ST\_Intersects(parcel.geom, point.geom) to bind canonical apn\_uid polygon and building\_footprint\_geom; generates concentric ring polygons R0 (0–5ft), R1 (5–30ft), and R2 (30–100ft) via ST\_Buffer and ST\_Difference. | GeoJSON FeatureCollection (Polygon & MultiPolygon keyed to apn\_uid and building\_id). |
| Stage 3: Vector-Raster Clipping & CV | Py3DEP, Rasterio Zonal Stats, & ONNX ViT / Mask R-CNN | Clips 1m USGS 3DEP LiDAR DEM/DSM to footprint to derive LAG, FFE, and freeboard delta\_h; runs Mask R-CNN over R0, R1, R2 orthophotos to measure canopy overhang (ft) and sheds; projects metrics to H3 Res 11/13 hexagons. | Apache Iceberg / Columnar Parquet Feature Store partitioned by state\_fips and h3\_res6\_index. |
| Stage 4: Actuarial Scoring & Delivery | Bayesian Credibility Engine, Guidewire Integration Gateway, & MCP Server | Evaluates ZIP/GPD compound AAL and Bühlmann-Straub posterior LCR; normalizes to SaveMyHome \[300, 850\]; writes audit JSON with dataset vintages (USGS\_3DEP: 2025-05-01) to Guidewire Integration Data Manager (IDM). | Outbound REST JSON payload & AsyncAPI / Model Context Protocol (MCP) tool responses. |

| Data Source | Ingestion Protocol / Endpoint | Update Cadence | Spatial Resolution | Key Extracted / Engineered Attributes | Target Parquet / PostGIS Column Mapping |
| ----- | ----- | ----- | ----- | ----- | ----- |
| FEMA OpenFEMA (FimaNfipClaims v2) | REST GET .../v2/FimaNfipClaims ($skip/$top pagination) | Monthly batch delta \+ Post-Cat event trigger | County FIPS / Census Tract / Lat-Lng (truncated) | amountPaidOnBuildingClaim, amountPaidOnContentsClaim, baseFloodElevation, elevationDifference, ratedFloodZone, elevationCertificateIndicator | nfip\_bldg\_paid\_usd (DOUBLE), nfip\_bfe\_ft (DOUBLE), nfip\_elev\_diff\_ft (DOUBLE), has\_elev\_cert (BOOLEAN) |
| USGS 3DEP EPQS & LiDAR | REST GET epqs.nationalmap.gov/v1/json & S3 COG py3dep | Annual / Rolling USGS 3DEP release vintage | 1-meter LiDAR DEM/DSM & 10-meter seamless | Bare-earth Lowest Adjacent Grade (LAG), Rooftop DSM height, Relative Freeboard (delta\_h \= FFE \- BFE) | usgs\_lag\_navd88\_ft (DOUBLE), est\_ffe\_ft (DOUBLE), freeboard\_delta\_h\_ft (DOUBLE) |
| NOAA PFDS (Atlas 14 & Atlas 15\) | OWP HDSC NetCDF / WMS Grid Server | Versioned (Atlas 14 Vol 12/13; Atlas 15 Vol 1 & 2 in 2026–2027) | \~800m to 2km continuous geostatistical grid | 10-yr, 50-yr, 100-yr, 500-yr 24h rainfall depths (in); CMIP6 non-stationary adjustment factor | noaa\_p24h\_10yr\_in (FLOAT), noaa\_p24h\_100yr\_in (FLOAT), atlas15\_cmip6\_mult (FLOAT) |
| USFS & LANDFIRE | LFPS REST API / Multi-band 16-bit GeoTIFF | Biennial \+ Annual disturbance updates | 30-meter raster grid | 40 Scott & Burgan Fuel Models (FBFM40), Canopy Base Height (CBH), WUI classification | lf\_fbfm40\_code (INT16), lf\_canopy\_base\_ht\_m (FLOAT), wui\_class (VARCHAR) |
| USGS HAND | Cloud-Optimized GeoTIFF via NHDPlus HR | Annual hydro-conditioning update | 10-meter hydro-enforced grid | Height Above Nearest Drainage (H\_HAND), Topographic Wetness Index (TWI) | hand\_rel\_elev\_ft (FLOAT), twi\_index (FLOAT) |
| Aerial CV (Nearmap / Pléiades Neo) | WMTS / REST Feature API \+ Internal ViT/Mask R-CNN | Per-submission on-demand \+ Semi-annual flyover | 7.5cm (Aerial) to 30cm (Satellite) | Roof material class, Class 4 hail rating, Canopy overhang (ft), Zone 0 (0–5ft), Zone 1 (5–30ft), Zone 2 (30–100ft) clearance | cv\_roof\_class (VARCHAR), cv\_overhang\_ft (FLOAT), cv\_zone0\_clear (BOOLEAN), cv\_zone1\_clear (BOOLEAN) |
| IoT & IBHS Registries | Webhook / REST API (Flo, Phyn, IBHS Portal) | Real-time event stream / Daily heartbeat | Parcel / Building (building\_id) | Active auto-shutoff valve, IBHS FORTIFIED Roof tier, IBHS Wildfire Prepared Home / Plus status | iot\_shutoff\_active (BOOLEAN), ibhs\_fortified\_tier (VARCHAR), ibhs\_wph\_tier (VARCHAR) |
| Carrier Closed Loss Runs | Encrypted SFTP Parquet / Guidewire CDA | Monthly batch & Post-Catastrophe continuous feed | Anonymized Parcel (apn\_uid) | incurred\_loss, water\_line\_depth, structural\_damage\_pct, verified pre-loss mitigation vector | hist\_incurred\_loss\_usd (DOUBLE), water\_line\_depth\_ft (FLOAT), struct\_dmg\_pct (FLOAT) |

Section 3: Mathematical and Actuarial Model Specification

The mathematical core adheres to Actuarial Standards of Practice (ASOP Nos. 12, 25, 38, and 56\) and maintains component independence across meteorology, vulnerability, and actuarial pricing as mandated by Florida FCHLPM Standard G-4 and California 10 CCR § 2644.9.

3.1 Two-Part Compound Risk Formulation

For parcel $i$ with Replacement Cost Value $RC{V}_{i}$ across perils $P=\{Flood(FL),Wildfire(WF),Wind/Hail(WH)\}$, Expected Annual Loss ($AA{L}_{i}$) is defined as:

\$\$\\text{AAL}\_i \= \\sum\_{p \\in \\mathcal{P}} \\text{AAL}\_{i,p} \= \\sum\_{p \\in \\mathcal{P}} \\mathbb{E}\[N\_{i,p}\] \\times \\mathbb{E}\[S\_{i,p} \\mid N\_{i,p} \> 0\] \\times \\text{RCV}\_i\$\$

where \$N\_{i,p} \\in \\{0, 1, 2, \\dots\\}\$ is the annual count of structural ingress events and ${S}_{i,p}\in (0,1]$ is the conditional fractional damage ratio. Across discrete NOAA Atlas 14/15 exceedance probabilities \$\\{f\_1, f\_2, \\dots, f\_K\\}\$ (2-yr to 1,000-yr return periods), flood $AA{L}_{i,FL}$ is equivalently evaluated via trapezoidal Riemann-Stieltjes integration:

$AA{L}_{i,FL}^{num}=RC{V}_{i}\sum\limits_{k=1}^{K-1}({f}_{k}-{f}_{k+1})\cdot \left({\frac{E[{S}_{i,FL}({d}_{k})]+E[{S}_{i,FL}({d}_{k+1})]}{2}}\right)+{f}_{K}\cdot E[{S}_{i,FL}({d}_{K})]\cdot RC{V}_{i}$

1\. Frequency ($E[{N}_{i,p}]$): Zero-Inflated Poisson (ZIP) & Negative Binomial GLM

Physical mitigations (positive freeboard $\Delta {h}_{i}>0$ or a noncombustible Zone 0 perimeter) create structural immunity against minor hazard events. We parameterize ${N}_{i,p}$ via a Zero-Inflated Poisson (ZIP) GLM with immunity probability ${\pi }_{i,p}\in (0,1)$ over physical barrier covariates ${z}_{i,p}$ and conditional Poisson intensity ${\lambda }_{i,p}>0$ over environmental covariates ${x}_{i,p}$:

\$\$\\mathbb{P}(N\_{i,p} \= n) \= \\begin{cases} \\pi\_{i,p} \+ (1 \- \\pi\_{i,p})\\exp(-\\lambda\_{i,p}), & \\text{for } n \= 0 \\\\ (1 \- \\pi\_{i,p})\\frac{\\lambda\_{i,p}^n \\exp(-\\lambda\_{i,p})}{n\!}, & \\text{for } n \\in \\{1, 2, \\dots\\} \\end{cases}\$\$

⚬ Flood Parameterization ($p=FL$): Driven by relative freeboard $\Delta {h}_{i}={z}_{FF,i}-BF{E}_{i}$, drainage height ${H}_{HAND,i}$, backflow valve ${I}_{backflow,i}$, elevated structure indicator ${I}_{elev\_bldg,i}$, and non-stationary Atlas 15 100-yr 24h precipitation ${D}_{100,i}={D}_{100,i}^{Atlas15,V1}\cdot {\gamma }_{CMIP6,i}$:

$logit({\pi }_{i,FL})={\gamma }_{0}+{\gamma }_{1}\max\limits_{}(0,\Delta {h}_{i})+{\gamma }_{2}{H}_{HAND,i}+{\gamma }_{3}{I}_{backflow,i},({\gamma }_{1},{\gamma }_{2},{\gamma }_{3}>0)$

$\ln ({\lambda }_{i,FL})={\beta }_{0}+{\beta }_{1}{D}_{100,i}+{\beta }_{2}TW{I}_{i}-{\beta }_{3}\Delta {h}_{i}-{\beta }_{4}{I}_{elev\_bldg,i},({\beta }_{1},{\beta }_{2},{\beta }_{3},{\beta }_{4}>0)$

⚬ Wildfire Parameterization ($p=WF$): Driven by 10 CCR § 2644.9 and IBHS indicators (Zone 0 clearance ${I}_{Zone0,i}$, Class A roof ${I}_{ClassA,i}$, 1/4-inch ember vents ${I}_{vents,i}$, absence of sheds within 30 ft ${I}_{no\_shed,i}$, Firewise community ${I}_{Firewise,i}$) alongside LANDFIRE fuel load ${F}_{40,i}$, topographic slope $Slop{e}_{i}$, and canopy overhang ${O}_{canopy,i}$:

$logit({\pi }_{i,WF})={\eta }_{0}+{\eta }_{1}{I}_{Zone0,i}+{\eta }_{2}{I}_{ClassA,i}+{\eta }_{3}{I}_{vents,i}+{\eta }_{4}{I}_{no\_shed,i},({\eta }_{1},{\eta }_{2},{\eta }_{3},{\eta }_{4}>0)$

$\ln ({\lambda }_{i,WF})={\delta }_{0}+{\delta }_{1}{F}_{40,i}+{\delta }_{2}Slop{e}_{i}+{\delta }_{3}{O}_{canopy,i}-{\delta }_{4}{I}_{Firewise,i},({\delta }_{1},{\delta }_{2},{\delta }_{3},{\delta }_{4}>0)$

Expected annual ingress frequency is:

$E[{N}_{i,p}]=(1-{\pi }_{i,p}){\lambda }_{i,p}=\left({\frac{1}{1+\exp ({\gamma }_{p}^{\top }{z}_{i,p})}}\right)\exp ({\beta }_{p}^{\top }{x}_{i,p})$

To capture spatial overdispersion during clustered convective storms or atmospheric rivers, placing a Gamma prior \$\\lambda\_{i,p} \\mid \\nu\_i \\sim \\text{Gamma}(r\_p, r\_p / \\mu\_{i,p})\$ yields the Zero-Inflated Negative Binomial (ZINB) active-state variance \$\\text{Var}(N\_{i,p} \\mid \\text{active}) \= \\mu\_{i,p} \+ \\frac{\\mu\_{i,p}^2}{r\_p}\$ while preserving $E[{N}_{i,p}]$.

2\. Severity (\$\\mathbb{E}\[S\_{i,p} \\mid N\_{i,p} \> 0\]\$): USACE Depth-Damage Curves Spliced with GPD Tail

Conditional loss severity ${S}_{i,p}\in (0,1]$ is modeled as a spliced distribution combining an empirical USACE / FEMA Depth-Damage Beta Regression in the body ($s\leq {u}_{p}$) with a Truncated Generalized Pareto Distribution (GPD) in the extreme tail (${u}_{p}<s\leq 1$).

For flood ($p=FL$), let ${d}_{i}(T)=\left({{w}_{i}(T)-BF{E}_{i}}\right)-\Delta {h}_{i}$ be effective water depth (in feet) relative to FFE. Following the USACE (2000) Generic Depth-Damage Curve for a One-Story Structure Without Basement—where sub-floor damage initiates at \-2.0 ft (0%), reaches \~13.4% at 0 ft, \~49.0% at \+4.0 ft, and asymptotes above \+12.0 ft—body vulnerability attenuated by flood-hardening vector ${m}_{i,FL}$ is:

\$\$\\mu\_{\\text{DDF}}(d\_i, \\mathbf{m}\_{i,\\text{FL}}) \= \\begin{cases} 0, & \\text{if } d\_i \\le \-2.0 \\\\ \\exp(-\\boldsymbol{\\psi}\_{\\text{FL}}^\\top \\mathbf{m}\_{i,\\text{FL}}) \\cdot \\left\[ \\frac{L\_{\\max}}{1 \+ \\exp\\left(-k\_{\\text{DDF}} (d\_i \- d\_0)\\right)} \- c\_0 \\right\], & \\text{if } d\_i \> \-2.0 \\end{cases}\$\$

with ${L}_{\max\limits_{}}=0.88$, ${k}_{DDF}=0.36$, ${d}_{0}=2.85$, and continuity constant ${c}_{0}$ enforcing ${\mu }_{DDF}(-2.0)=0$.

Above the catastrophic threshold ${u}_{p}=0.50$, excess severity \$Y \= S\_{i,p} \- u\_p \\mid S\_{i,p} \> u\_p\$ follows a GPD truncated on $[0,1-{u}_{p}]$ with shape ${\xi }_{p}$ and mitigation-attenuated scale ${\sigma }_{i,p}({m}_{i,p})={\sigma }_{0,p}\exp (-{\theta }_{p}^{\top }{m}_{i,p})$:

${G}_{{\xi }_{p},{\sigma }_{i,p}}(y)=1-{\left({1+\frac{{\xi }_{p}y}{{\sigma }_{i,p}({m}_{i,p})}}\right)}^{-1/{\xi }_{p}},y\in [0,1-{u}_{p}]$

With tail exceedance probability ${p}_{tail,i,p}=\Phi \left({{\alpha }_{0,p}-{\alpha }_{p}^{\top }{m}_{i,p}-{\alpha }_{\Delta h}\Delta {h}_{i}}\right)$, total expected conditional severity is:

\$\$\\mathbb{E}\[S\_{i,p} \\mid N\_{i,p} \> 0\] \= (1 \- p\_{\\text{tail},i,p}) \\cdot \\mu\_{\\text{body},i,p}(\\Delta h\_i, \\mathbf{m}\_{i,p}) \+ p\_{\\text{tail},i,p} \\cdot \\left\[ u\_p \+ \\mathbb{E}\_{\\text{TGPD}}\\left\[Y \\mid 0 \\le Y \\le 1 \- u\_p; \\xi\_p, \\sigma\_{i,p}(\\mathbf{m}\_{i,p})\\right\] \\right\]\$\$

3.2 Bayesian Hierarchical Credibility Updating (Bühlmann-Straub)

To balance parcel-level verification against census-tract hazard priors, SaveMyHome embeds the compound loss estimate into a hierarchical Bühlmann-Straub Empirical Bayes Credibility Model.

1\. Macro Census-Tract Prior: Latent tract risk ${\Theta }_{j}$ for tract $j$ follows a conjugate Gamma prior calibrated on OpenFEMA historical paid loss ratios, NOAA Atlas 15 posteriors, and regional burn probabilities:

${\Theta }_{j}\sim Gamma({\alpha }_{j},{\beta }_{j}),{\mu }_{0,j}=E[{\Theta }_{j}]=\frac{{\alpha }_{j}}{{\beta }_{j}},{\tau }_{j}^{2}=Var({\Theta }_{j})=\frac{{\alpha }_{j}}{{\beta }_{j}^{2}}$

1\. Parcel Likelihood & Verification Precision Weight: Parcel Loss Cost Ratio ${X}_{ij}=\frac{AA{L}_{ij}}{RC{V}_{ij}}$ is observed across ${M}_{ij}$ verification channels (1m LiDAR, Aerial CV, NFIP Elevation Certificates, IBHS/IoT telemetry), each carrying inverse-variance precision weight ${w}_{ij,m}>0$:

\$\$w\_{ij} \= \\sum\_{m=1}^{M\_{ij}} w\_{ij,m}, \\quad \\mathbb{E}\[X\_{ij} \\mid \\Theta\_{ij}\] \= \\mu(\\Theta\_{ij}), \\quad \\text{Var}(X\_{ij} \\mid \\Theta\_{ij}) \= \\frac{\\sigma^2}{w\_{ij}}\$\$

1\. Posterior Credibility Estimator: Letting \$\\sigma^2 \= \\mathbb{E}\\left\[w\_{ij} \\text{Var}(X\_{ij} \\mid \\Theta\_{ij})\\right\]\$ denote Expected Value of Process Variance (EVPV, within-parcel epistemic/sensor noise) and \$\\tau^2 \= \\text{Var}\\left(\\mathbb{E}\[X\_{ij} \\mid \\Theta\_{ij}\]\\right)\$ denote Variance of Hypothetical Means (VHM, between-parcel structural heterogeneity), the linear Bayes estimator is:

${\widehat{LCR}}_{ij}^{post}={Z}_{ij}\cdot {X}_{ij}^{parcel}+(1-{Z}_{ij})\cdot {\mu }_{0,j}^{tract},where{Z}_{ij}=\frac{{w}_{ij}}{{w}_{ij}+k}=\frac{{w}_{ij}}{{w}_{ij}+\frac{{\sigma }^{2}}{{\tau }^{2}}}$

⚬ Low-Verification / Occluded Regime (${Z}_{ij}\in [0.15,0.25]$): When cloud cover or missing certificates keep ${w}_{ij}$ low relative to $k={\sigma }^{2}/{\tau }^{2}$, ${\widehat{LCR}}_{ij}^{post}$ defaults conservatively toward the census-tract prior ${\mu }_{0,j}^{tract}$.

⚬ High-Verification Hardened Regime (${Z}_{ij}\in [0.92,0.98]$): When 1m LiDAR, Nearmap CV (confidence \> 0.95), an Elevation Certificate, and an IBHS certificate are verified in high-heterogeneity WUI/coastal tracts (large ${\tau }^{2}$, small $k$), ${Z}_{ij}\rightarrow 1$, mathematically decoupling the hardened structure from its toxic ZIP-code prior.

3.3 FICO-Style Normalization (300–850 Scale)

Posterior Loss Cost Ratio ${\widehat{LCR}}_{i}={\widehat{LCR}}_{ij}^{post}$ maps onto $[300,850]$ via a continuous log-logistic sigmoidal transformation anchored at midpoint $LC{R}_{0}=0.0085$ (85 bps of RCV, or \$4,250 pure cat loss on \$500k RCV $\rightarrow SaveMyHome=575$) and slope $\kappa =1.15$:

$ResiliScor{e}_{i}=300+round\left({\frac{550}{1+\exp \left({\kappa \cdot \left[{\ln \left({{\widehat{LCR}}_{i}}\right)-\ln \left({LC{R}_{0}}\right)}\right]}\right)}}\right)=300+round\left({\frac{550}{1+{\left({\frac{{\widehat{LCR}}_{i}}{LC{R}_{0}}}\right)}^{\kappa }}}\right)$

| Underwriting Tier | SaveMyHome Range | Implied Posterior LCR (AAL / RCV) | Annual Pure Cat Loss Cost (per \$500k RCV) | Automated Underwriting Copilot Action & Binding Protocol |
| ----- | ----- | ----- | ----- | ----- |
| Tier 1: Preferred Resilient | 720 – 850 | \<= 0.0032 (\<= 32 bps) | \<= \$1,600 / yr | Instant Auto-Bind Eligibility: Zero human touch; automated API quote issuance with statutory mitigation credits applied (21%–30% wildfire or 20%–55% wind discount). |
| Tier 2: Conditional Mitigable | 580 – 719 | 0.0033 to 0.0082 (33 to 82 bps) | \$1,650 to \$4,100 / yr | Conditional Bind with Remediation: Automated policy issuance contingent on completing a 60-day Prescriptive Mitigation Action Plan verified via mobile photo/CV upload. |
| Tier 3: High Vulnerability | 300 – 579 | \> 0.0082 (\> 82 bps) | \> \$4,100 / yr | Decline / Senior Underwriter Escalation: Blocks straight-through admitted binding; routes to senior underwriter workbench or Surplus Lines (E\&S) / DIC facility quote. |

3.4 Regulatory Compliance and Explainability

1\. Proof of Strict Mathematical Monotonicity

Because all physical mitigation parameters (${\gamma }_{k},{\beta }_{k},{\psi }_{k},{\theta }_{k},{\alpha }_{k}>0$) strictly attenuate frequency and severity while the outer sigmoidal derivative is strictly negative:

$\frac{\partial ResiliScor{e}_{i}}{\partial {\widehat{LCR}}_{i}}=-\frac{550\cdot \kappa }{{\widehat{LCR}}_{i}}\cdot \frac{{\left({{\widehat{LCR}}_{i}/LC{R}_{0}}\right)}^{\kappa }}{{\left[{1+{\left({{\widehat{LCR}}_{i}/LC{R}_{0}}\right)}^{\kappa }}\right]}^{2}}<0$

application of the chain rule guarantees that any physical mitigation ${m}_{i,k}$ strictly improves the score and reduces pure premium:

\$\$\\frac{\\partial \\text{SaveMyHome}\_i}{\\partial m\_{i,k}} \= \\underbrace{\\frac{\\partial \\text{SaveMyHome}\_i}{\\partial \\widehat{\\text{LCR}}\_i}}\_{\< 0} \\cdot \\underbrace{Z\_{ij}}\_{\> 0} \\cdot \\left( \\sum\_{p \\in \\mathcal{P}} \\left\[ \\underbrace{\\frac{\\partial \\mathbb{E}\[N\_{i,p}\]}{\\partial m\_{i,k}}}\_{\\le 0} \\mathbb{E}\[S\_{i,p}\] \+ \\mathbb{E}\[N\_{i,p}\] \\underbrace{\\frac{\\partial \\mathbb{E}\[S\_{i,p}\]}{\\partial m\_{i,k}}}\_{\\le 0} \\right\] \\right) \> 0\$\$

2\. Multi-State Regulatory Filing Matrix

| Regulatory Jurisdiction & Mandate | Core Statutory & Supervisory Requirements | SaveMyHome Architectural & Actuarial Compliance Implementation |
| ----- | ----- | ----- |
| New York DFS Insurance Circular Letter No. 7 (July 11, 2024\) | Enforces NY Ins. Law §§ 2303, 2606, 4224 & 11 NYCRR § 90.2; mandates two-step proxy discrimination testing (Step 1 BISG Adverse Impact Ratio & Step 2 Business Necessity), board governance, third-party vendor auditability, and Article 24 disclosures. | Excludes all socio-economic/behavioral ECDIS (credit, occupation, shopping data); provides contractual audit rights, full GLM/GPD parameter tables, pre-deployment BISG disparate-impact audits, and exact log-odds feature attributions with dataset vintages (protected under NY Public Officers Law § 87(2)(d)). |
| California Proposition 103 & 10 CCR § 2644.9 (CDI Bulletin 2023-2) | Mandates rate relief for 12 wildfire mitigations across Cat A (Fire Risk Reduction Community, Firewise USA, Shelter-in-Place), Cat B1 (under-deck clearing, 0–5ft Zone 0 clearing, 0–5ft noncombustible materials, no sheds within 30ft, PRC § 4291 compliance), and Cat B2 (Class A roof, enclosed eaves, ember vents, multi-pane windows, 6-in vertical siding clearance). | Maps CV and registry indicators 1-to-1 to all 12 mandatory factors plus optional fuel/slope modifiers; provides empirical loss-cost relativities via the Consortium Flywheel to prevent rate erosion; generates mandatory policyholder score appeal and disclosure notices. |
| Florida OIR & FCHLPM (Fla. Stat. § 627.0628) | Requires biennial hurricane and quadrennial flood model certification; enforces Standard G-4 component independence (meteorology, vulnerability, actuarial); mandates automated Meteorological Form M-1, Statistical Forms S-1, S-2, S-6, and Actuarial Forms A-1, A-2. | Decouples NOAA Atlas 15 / USGS hazard rasters from USACE / IBHS vulnerability curves and Bühlmann-Straub credibility pricing; automates FCHLPM audit form generation; protects proprietary code under Fla. Stat. § 627.0628(3)(g) trade secret exemption. |

Section 4: The Redesigned PMAI Workflow

4.1 Legacy vs. SaveMyHome Workflow Comparison

| Workflow Stage | Legacy Carrier Workflow | SaveMyHome AI-Native Copilot Workflow | Quantified Operational Impact |
| ----- | ----- | ----- | ----- |
| 1\. Submission Intake | Applicant/broker fills out a 45-question ACORD PDF manually estimating roof age, brush distance, and flood zone; high error rate. | Zero-Input Address/APN Autocomplete: Street address resolves APN, building footprint polygon, and pre-populates 35+ verified structural and topographic attributes via API. | Intake time cut from 25 minutes to 4 seconds; eliminates applicant misrepresentation. |
| 2\. Hazard Screen | Underwriter checks census tract or 5-digit ZIP against static FEMA FIRMs and macro wildfire tables; applies binary ZIP moratoriums. | Continuous Parcel Micro-Hazard Screen: Queries USGS 3DEP 1m LiDAR freeboard, USGS HAND, NOAA Atlas 15 non-stationary grids, and LANDFIRE FBFM40 fuels. | Unlocks 30%–45% of profitable hardened risks blocked by binary territory freezes. |
| 3\. Physical Inspection | Orders third-party physical field survey ($250–$450 cost, 14–21 days turnaround) to photograph roof, eaves, and yard clearance. | Automated CV & Registry Verification: ViT segments 7.5cm Nearmap/Pléiades Neo imagery for Class A roof, canopy overhang, and Zone 0/1/2 clearance; cross-checks IBHS & permit APIs. | Inspection cost cut by 99.5% ($450to<$2.00); cycle time cut from 14 days to 3.8 seconds. |
| 4\. Pricing & Binding | Applies coarse territorial base rates; underwriter manually reviews inspection PDFs; unverified discounts erode rate adequacy. | Bühlmann-Straub Credibility & Tiered Routing: Computes posterior LCR and SaveMyHome (300–850); Tier 1 (720–850) auto-binds; Tier 2 (580–719) triggers conditional bind. | Straight-through processing (STP) rises from 18% to 74%; 100% compliant with 10 CCR § 2644.9 and NY DFS CL No. 7\. |
| 5\. Mitigation Guidance | Generic adverse action notice ("Declined due to wildfire/flood hazard") with zero remediation path. | Prescriptive Mitigation Action Plan: Counterfactual engine computes exact SaveMyHome boost, annual premium savings, and grant offsets per retrofit. | Converts 35%+ of conditional declines into bound policies; fulfills CA disclosure laws. |
| 6\. Claims Adjudication | Post-cat adjusters measure water lines and roof damage manually from scratch; slow FNOL triage. | Pre-Loss Digital Twin & Closed-Loop FNOL: Pre-loss LiDAR FFE and baseline CV roof masks feed Guidewire ClaimCenter; post-event aerial/IoT data automates triage. | Accelerates post-cat claim triage by 60%; streams closed loss runs back into Bayesian likelihood. |

4.2 The Human-in-the-Loop (HITL) Protocol

⚬ Autonomous AI Execution (\< 5 Seconds): (1) Resolves APN polygon, extracts 1m LiDAR freeboard ($\Delta h$), evaluates USGS HAND, and pulls NOAA Atlas 14/15 grids; (2) Segments Zone 0/1/2 buffers and roof condition via CV while querying IBHS and IoT shutoff APIs; (3) Computes ZIP/GPD $AA{L}_{i}$, Bühlmann-Straub ${Z}_{ij}$, and SaveMyHome $[300,850]$, executing straight-through binding in Guidewire PolicyCenter for Tier 1 parcels.

⚬ Deterministic Escalation to Human Underwriter (Guidewire UnderwritingCenter):

| HITL Trigger ID & Category | Deterministic Mathematical / Sensor Condition | Escalated Underwriter Action & Resolution Protocol |
| ----- | ----- | ----- |
| Trigger 1: Cross-Sensor Epistemic Divergence | Discrepancy between USGS 3DEP 1m LiDAR FFE and municipal permit / NFIP Elevation Certificate exceeds 1.5 ft, OR tree/cloud occlusion drops ViT segmentation confidence below 0.85 in Zone 0 or Zone 1\. | Underwriter inspects oblique imagery and Elevation Certificate PDF in Copilot UI, or dispatches a 60-second cryptographically geofenced smartphone self-inspection link to verify foundation vents and 5-ft perimeter. |
| Trigger 2: Unpermitted Structural Addition | Polygon area of building\_footprint\_geom from current Pléiades Neo / Nearmap orthophotos exceeds tax assessor footprint by \> 150 sq ft, indicating an unpermitted addition, ADU, or enclosed deck. | Senior underwriter reviews permit history, verifies post-2008 Chapter 7A or Florida Building Code compliance of the addition, and adjusts RCV and vulnerability modifiers before quote release. |
| Trigger 3: High-Value Commercial / Habitational TIV | Total Insured Value (TIV) exceeds \$5,000,000 residential or involves high-value commercial habitational schedules (competing with CA FAIR Plan's \$20M/building, \$100M/location commercial limits). | Mandatory senior underwriter sign-off on facultative reinsurance attachment points, aggregation capacity, and fire-suppression engineering reports. |
| Trigger 4: Threshold Boundary & Multi-Peril Conflict | Composite score falls inside the Tier 2/Tier 3 boundary (\[570, 590\]) OR exhibits sharp peril divergence (e.g., Tier 1 Wildfire \> 750 paired with localized pluvial HAND ponding \< 520). | Underwriter structures a customized package—binding primary wind/wildfire coverage while attaching a parametric flood endorsement or graduated water deductible. |

4.3 The Prescriptive Mitigation Action Plan

For Tier 2 (580–719) and Tier 3 (300–579) parcels, the counterfactual optimization engine evaluates every feasible physical retrofit $a\in {A}_{i}$:

$\Delta ResiliScor{e}_{i}(a)=ResiliScor{e}_{i}({m}_{i}+{e}_{a})-ResiliScor{e}_{i}({m}_{i}),Paybac{k}_{i}(a)=\frac{CapEx(a)-GrantSubsidy(a)}{\Delta Premiu{m}_{i}(a)+\Delta ExpectedDeductibleLos{s}_{i}(a)}$

Empirical benchmarks anchor each calculation: IBHS FORTIFIED Roofs cut hurricane claim frequency by 73% (Hurricane Sally) and total hurricane losses by 72%–76%, unlocking 20%–55% statutory wind discounts (\$1,250/yr average savings in Alabama), a 6.8% home resale value bump, 8.1%–72% homeowner ROI, and \$6.00 in disaster recovery savings per \$1.00 spent, backed by \$10,000 grants and $10,000taxcreditsinLouisianaand12.4%($420/yr) Class 4 hail discounts at Mercury Insurance. IBHS Wildfire Prepared Home Plus adds just 3% (\~$15,000,or~$2,000 over CA code) to rebuild costs while cutting premiums by 21% on average—unlocking up to 30% off wildfire peril rates at Mercury, 4%–18% at State Farm, and 16.4% under the CA FAIR Plan's November 2025 discount stack.

| Prescriptive Mitigation Measure | Target Peril & Statutory Authority | Gross CapEx / Grant Offset | Posterior LCR Impact | SaveMyHome Boost | Verified Annual Premium Savings | Net Payback Period & Equity Impact |
| ----- | ----- | ----- | ----- | ----- | ----- | ----- |
| Zone 0 (0–5 ft) Noncombustible Buffer \+ PRC § 4291 Tree Pruning (15 ft clearance) | Wildfire (10 CCR § 2644.9 Cat B1 & IBHS WPH) | \$1,800 Gross / \$0 Grant | \-18 bps (Boosts ember immunity & cuts arrival rate) | \+65 pts | \-\$680 / yr (Up to 16.4% off FAIR Plan / admitted wildfire rate) | 2.6 Years; immediately unlocks conditional bind eligibility. |
| 1/4-Inch Metal Mesh Ember Vents \+ Enclosed Soffit Eaves | Wildfire (10 CCR § 2644.9 Cat B2 & Chapter 7A) | \$3,200 Gross / \$0 Grant | \-15 bps (Blocks attic ember ingress) | \+55 pts | \-\$540 / yr (Mandated B2 hardening credit) | 5.9 Years; prevents catastrophic attic ignition. |
| IBHS Wildfire Prepared Home Plus (Class A Roof, Tempered Glass, Noncombustible Siding) | Wildfire (IBHS WPH Plus & 10 CCR § 2644.9 B1+B2) | \$15,000 Incremental Rebuild Cost (3% of RCV) | \-42 bps (Shrinks both frequency and GPD tail scale) | \+150 pts | \-\$1,450 / yr (21% avg total savings; up to 30% wildfire peril cut) | 10.3 Years (or 1.4 Years vs. \$2,000 code delta during rebuild). |
| IBHS FORTIFIED Roof \+ UL 2218 Class 4 Impact Shingles | Wind & Hail (FL/AL/LA/OK Statutory Discounts) | $12,500Gross/-$10,000 State Grant (LA/AL) | \-35 bps (73% fewer claims; 72%–76% loss reduction) | \+115 pts | \-\$1,250 / yr (20%–55% wind discount; $420–$1,250 avg savings) | 2.0 Years Net of Grant; adds \+6.8% to home resale value. |
| Smart Water Auto-Shutoff Valve (Flo/Phyn) \+ Backflow Preventer \+ Elevated HVAC | Flood & Non-Weather Water (USACE Sub-Floor DDF) | $1,650Gross/CarrierRebate-$250 | \-11 bps (Truncates \[-2, 0\] ft sub-floor loss) | \+45 pts | \-\$380 / yr (Protective device & flood mitigation credit) | 3.7 Years; continuous IoT telemetry boosts credibility Z\_ij. |

Section 5: Enterprise B2B Go-To-Market and Moat Strategy

5.1 Core System Integration and Dual-Engine GTM

SaveMyHome integrates natively into Guidewire Cloud Platform (InsuranceSuite), Duck Creek OnDemand, and Applied Epic without intrusive core code customization:

⚬ Ingestion & Storage (PolicyCenter & IDM): An App Event (`PolicyPeriodCreated` or `SubmissionQuoted`) triggers an outbound REST API Client call via the Guidewire Integration Gateway (Apache Camel middleware) to `POST /v1/parcel/score`. In \< 3.8 seconds, top-level scores populate upgrade-safe Data Model Extensions (`ResiliScore_Ext`) and Typelists on underwriter Page Configuration Files (PCFs), while full CV/regulatory audit JSONs are stored in Guidewire's Integration Data Manager (IDM).

⚬ Rating & Binding (PricingCenter & Rules Service): Plugs into Guidewire PricingCenter's "Bring Your Own Model" (BYOM) and pre-packaged Gosu rules to apply 10 CCR § 2644.9 or FORTIFIED credits during `POST /submissions/{submissionId}/quote` and auto-bind Tier 1 risks via `POST /submissions/{submissionId}/issue`.

⚬ Agentic Copilot & Claims (UnderwritingCenter & ClaimCenter): Exposes a Model Context Protocol (MCP) Server (`get_parcel_resiliscore`, `verify_zone0_clearance`, `query_usgs_freeboard`, `simulate_mitigation_roi`) for Guidewire's Agentic Framework, Underwriting Assistant, and ProNavigator, while feeding pre-loss digital twins into ClaimCenter (`POST /fnol`, `GET /claims/{claimId}/exposures`).

To bypass 9-to-18-month carrier procurement cycles while building enterprise scale, SaveMyHome executes a Dual-Engine Go-To-Market:

| Strategic Dimension | Phase 1: Catastrophe-Resilient MGA & Take-Out Facility (Months 1–18) | Phase 2: Direct Carrier Enterprise B2B SaaS & API Platform (Months 6–36+) |
| ----- | ----- | ----- |
| Target Customer / Channel | Independent retail brokers, E\&S wholesalers, and state depopulation clearinghouses (FL Citizens, CA FAIR Plan, LA Citizens). | Tier-1 and Tier-2 admitted P\&C carriers (State Farm, Mercury, CSAA, Allstate, mutuals) and global reinsurers / ILS cat bond funds. |
| Commercial Mechanism | Tech-enabled MGA backed by A-rated fronting paper and collateralized reinsurance / Lloyd's syndicates; scans all 573,739+ CA FAIR Plan and FL Citizens parcels overnight to cherry-pick Tier 1 (\>= 720\) hardened homes. | Annual Enterprise SaaS license \+ usage-based API tiers ($1.50–$3.50 per quote screen; \$0.45 per renewal monitor) embedded in Guidewire/Duck Creek. |
| Unit Economics & Take Rate | 18%–22% MGA Gross Written Premium (GWP) commission \+ 25% sliding-scale profit commission on sub-55% loss ratio alpha. | 85%+ Gross Margin SaaS with 140%+ Net Dollar Retention (NDR) across nationwide book rolls. |
| Strategic Purpose | Proves live actuarial loss-ratio alpha within 6 months; monetizes mispriced Tier 1 FAIR Plan / Citizens policies directly. | Scales to 85M+ U.S. residential parcels without balance-sheet constraints; cements SaveMyHome as the industry standard. |

5.2 The "Give-to-Get" Consortium Data Flywheel

Carriers lack parcel-level empirical loss data to calibrate multi-mitigation discount relativities accurately. SaveMyHome solves this via a contractual "Give-to-Get" Consortium Flywheel:

⚬ Standalone API Tier (\$3.50/call): Uses baseline public OpenFEMA and USACE/IBHS priors.

⚬ Consortium Flywheel Tier (\$1.75/call — 50% SaaS Discount): Requires enabling an automated, read-only Guidewire Cloud Data Access (CDA) connector that streams anonymized closed claim records (`apn_hash`, `event_id`, `incurred_building_loss`, `water_line_depth_ft`, `ember_ignition_vector`, `pre_loss_mitigation_vector`) into SaveMyHome's federated enclave. Post-catastrophe loss runs continuously update log-likelihood parameters $(\gamma ,\beta ,\psi ,\theta )$ and shrink within-group process variance ${\sigma }^{2}$ in ${Z}_{ij}=\frac{{w}_{ij}}{{w}_{ij}+{\sigma }^{2}/{\tau }^{2}}$, creating a compounding actuarial moat against non-participating carriers.

5.3 Consumer, Real Estate, and Mortgage Capital Markets Distribution

⚬ Real Estate Portal Syndication (Zillow / Redfin): Static macro scores (e.g., First Street 1–10) stigmatize listings without rewarding retrofits. SaveMyHome syndicates a dynamic "Verified SaveMyHome (300–850)" widget; when a seller completes the Prescriptive Mitigation Action Plan or links an IBHS certificate (via the GAF-IBHS contractor pipeline), the listing updates instantly from `540 (Tier 3)` to `745 (Tier 1 Auto-Bind Eligible — Est. Savings: $1,850/yr)`, unlocking the documented \+6.8% property resale value premium.

⚬ Mortgage & RMBS Transaction Gate: Moody's Analytics and GARP research confirms that insurance burden predicts mortgage delinquency independently of LTV, DTI, and FICO. By licensing SaveMyHome to mortgage originators, GSEs (Fannie Mae/Freddie Mac), and RMBS rating desks to price FAIR Plan/Citizens concentration risk, lenders mandate a minimum Tier 2 SaveMyHome ($\geq 580$) (or an escrow holdback for the Mitigation Action Plan) prior to loan closing.

Section 6: Hackathon Winning Artifacts (PMAI NYC 2026\)

6.1 Three-Minute Live Pitch Script

\> \[0:00 – 0:30 | THE HOOK & THE \$645 BILLION PARADOX\]  
"Right now, a homeowner in Pacific Palisades or Miami-Dade can spend twenty-five thousand dollars installing a Class A fire-rated FORTIFIED roof, clearing five feet of noncombustible Zone 0 defensible space, and elevating mechanical utilities four feet above Base Flood Elevation—and still get non-renewed by an insurance carrier in thirty milliseconds. Why? Because legacy catastrophe models score the *neighborhood*, not the *structure*. That single architectural blind spot drove eleven carrier insolvencies in Louisiana after Hurricane Ida, pushed Florida Citizens to 1.42 million policies, and ballooned the California FAIR Plan to \$645 billion in exposure before the January 2025 Los Angeles wildfires triggered a \$4.8 billion FAIR Plan claim shock and its first bailout assessment in thirty-one years. Meet SaveMyHome: the AI-native 300-to-850 Property Catastrophe Resilience Score and Underwriting Copilot that replaces binary ZIP-code freezes with parcel-level physical verification in under four seconds."

\> \[0:30 – 1:15 | THE LEGACY WORKFLOW BREAKDOWN\]  
"Today, when a property submission hits an underwriter's desk at a carrier running Guidewire or Duck Creek, the workflow is completely broken. Macro vendors like First Street, CoreLogic, and Moody's RMS flag an entire census tract as high hazard. To check if the actual house is hardened, the carrier has to order a manual physical inspection—costing \$450 and taking fourteen days—or guess at discounts and watch rate adequacy bleed for two years. Yet the empirical science is crystal clear: in the 2025 Palisades Fire, 95% of damaged homes predated California's 2008 Chapter 7A building code. In Hurricane Ian, zero structures built to the modern Florida Building Code suffered structural wind damage. And IBHS FORTIFIED roofs cut hurricane claims by 73%. The resilience signal exists on the parcel—carriers simply lack the pipeline to ingest and price it at the point of quote."

\> \[1:15 – 2:00 | LIVE PRODUCT & WORKFLOW TRANSFORMATION\]  
"SaveMyHome automates that entire fourteen-day workflow in 3.8 seconds for under two dollars. When an address enters the SaveMyHome Copilot, the spatial harmonization engine resolves the national parcel polygon and queries five federal foundation layers in parallel: 2.5 million FEMA NFIP claims, USGS 1-meter 3DEP LiDAR to measure exact First Floor Elevation freeboard against Base Flood Elevation, USGS Height Above Nearest Drainage, LANDFIRE 40 surface fuel models, and NOAA's new non-stationary Atlas 15 precipitation grids. Next, the Vision Transformer segments high-resolution aerial imagery across the exact statutory rings mandated by California Regulation 2644.9 and IBHS: Zone 0 at five feet, Zone 1 at thirty feet, and Zone 2 at one hundred feet, grading roof class and tree canopy overhang while pulling real-time smart water valve telemetry. When the parcel scores above 720—Tier 1—Guidewire PolicyCenter auto-binds it instantly. When it scores between 580 and 719—Tier 2—the Copilot generates a Prescriptive Mitigation Action Plan showing the exact point boost, premium savings, and state grant ROI required to unlock coverage."

\> \[2:00 – 2:35 | ACTUARIAL & REGULATORY DEFENSIBILITY\]  
"Unlike black-box wrappers, SaveMyHome is engineered from the ground up for state rate filings. The actuarial core pairs a Zero-Inflated Poisson frequency GLM and a USACE Depth-Damage plus Generalized Pareto tail severity model inside a Bühlmann-Straub Bayesian credibility framework. When parcel verification confidence is high, the credibility factor $Z$ approaches one, mathematically decoupling a hardened home from a toxic census-tract prior. Every partial derivative is strictly monotonic, all socio-economic proxies are excluded to satisfy New York DFS Circular Letter No. 7, and every California Regulation 2644.9 and Florida FCHLPM standard is mapped out of the box."

\> \[2:35 – 3:00 | ENTERPRISE MOAT & MARKET CLOSE\]  
"SaveMyHome launches via a dual engine: capturing immediate underwriting margin by cherry-picking Tier 1 hardened policies out of the \$645 billion California FAIR Plan and Florida Citizens depopulation clearinghouses, while licensing an MCP-ready API directly into Guidewire PolicyCenter under a 'Give-to-Get' closed-loss-run flywheel. With an \$8 billion to \$10 billion annual premium gap in California alone and mortgage investors demanding loan-level resilience scoring across 85 million U.S. homes, SaveMyHome establishes the FICO score for physical climate resilience."

6.2 Interactive Demo Walkthrough Guide

⚬ Scenario 1: Coastal Flood with High Freeboard (412 Bayou Rd, Jefferson Parish, LA): Located in FEMA Zone AE (`baseFloodElevation = 9.0 ft NAVD88`) where 11 insurers failed post-Ida. Macro census-tract prior LCR is 1.85% (185 bps) $\rightarrow$ Baseline Score: 430 (Tier 3 Decline). Clicking `Run SaveMyHome Spatial & LiDAR Verification` executes in 3.1s: `USGS_3DEP_EPQS` extracts LAG of 7.2 ft and 1m LiDAR elevated FFE of 13.2 ft; `OpenFEMA_NFIP_v2` confirms `elevatedBuildingIndicator = true`, `elevationCertificateIndicator = true`, and positive freeboard $\Delta h=+4.2ft$ above BFE; `NOAA_Atlas15_PFDS` and `USGS_HAND` confirm \+6.4 ft drainage clearance under a 14.8-in 24h storm; `Nearmap_CV_v4` verifies an IBHS FORTIFIED Roof funded by Louisiana's \$10,000 Fortify Homes grant. Credibility jumps to ${Z}_{ij}=0.94$, shifting the USACE curve right by \+4.2 ft and cutting posterior LCR from 185 bps to 24 bps (\$1,080 AAL on \$450k RCV). Score leaps from 430 to 765 (Tier 1 Auto-Bind) via Guidewire `/submissions/quote` with a 38% wind and freeboard credit.

⚬ Scenario 2: Wildfire WUI with Zero Brush Clearance (1840 Canyon Crest Dr, Altadena Foothills, CA): Pre-2008 Chapter 7A foothill parcel overlaid with Zone 0 (0–5 ft), Zone 1 (5–30 ft), and Zone 2 (30–100 ft) rings. Clicking `Execute Multi-Spectral CV & LANDFIRE Scan` flags `LANDFIRE_FBFM40` heavy chaparral (`SH7`) on a 28-degree slope while ViT highlights an unrated wood-shake roof, 16.5 ft of eucalyptus canopy overhanging Zone 0, and a wooden shed at 18 ft in Zone 1 $\rightarrow$ Posterior LCR \= 245 bps, SaveMyHome \= 385 (Tier 3 Decline). Clicking `Generate 10 CCR § 2644.9 Prescriptive Mitigation Action Plan` toggles three retrofits: clearing Zone 0 overhang \+ moving Zone 1 shed (\$1,800 $\rightarrow$ \+65 pts), 1/4-in ember vents \+ enclosed eaves (\$3,200 $\rightarrow$ \+55 pts), and IBHS Wildfire Prepared Home Class A roof upgrade (\$14,500 $\rightarrow$ \+125 pts). Score updates live from 385 to 630 (Tier 2 Conditional Bind), cutting annual premium by \-\$2,140/yr and issuing a 60-day FAIR Plan take-out endorsement.

⚬ Scenario 3: Suburban Full Mitigation & HITL Guardrail (Dixon Trail Subdivision, Escondido, CA): Modeled on the first IBHS Wildfire Prepared Neighborhood. Webhooks verify `ibhs_wph_tier = PLUS`, `cv_roof_class = CLASS_A_IMPACT_4`, `cv_zone0_clear = true`, and active Flo by Moen shutoff telemetry (`iot_shutoff_active = true`), driving ${Z}_{ij}=0.97$, posterior LCR \= 18 bps, and SaveMyHome \= 815 (Tier 1 Auto-Bind) with a 30% wildfire discount and 12.4% (\$420) Class 4 hail credit. Clicking `Simulate HITL Edge-Case Trigger: Unpermitted Footprint Delta` injects a satellite alert showing an unrecorded 240 sq ft structure in Zone 1; the Copilot immediately halts auto-binding, flags `HITL_TRIGGER_02`, and routes the dossier to `Guidewire UnderwritingCenter`.

| Demo Scenario & Location | Macro Census-Tract Prior | Live Sensor & Registry Signals Ingested | Credibility Z\_ij & Posterior LCR | Final SaveMyHome & Copilot Execution |
| ----- | ----- | ----- | ----- | ----- |
| Scenario 1: Coastal Flood with High Freeboard (Jefferson Parish, LA) | 430 (Tier 3 Decline); FEMA Zone AE (BFE \= 9.0 ft); Tract LCR \= 185 bps. | USGS 3DEP 1m LiDAR (FFE \= 13.2 ft, delta\_h \= \+4.2 ft above BFE); OpenFEMA Elevation Cert; USGS HAND (+6.4 ft); IBHS FORTIFIED Roof. | Z\_ij \= 0.94; Posterior LCR \= 24 bps (AAL \= \$1,080) | 765 (Tier 1 Auto-Bind); Guidewire /submissions/quote binds with 38% wind & freeboard credit. |
| Scenario 2: WUI Wildfire Unmitigated to Remediated (Altadena Foothills, CA) | 385 (Tier 3 Decline); Pre-2008 Chapter 7A home; LANDFIRE SH7 fuel on 28-deg slope. | ViT/Mask R-CNN detects wood shake roof, 16.5 ft Zone 0 overhang, and Zone 1 shed (18 ft); user toggles 3-step 10 CCR § 2644.9 remediation plan. | Z\_ij \= 0.91; Posterior LCR: 245 bps to 58 bps | 385 to 630 (Tier 2 Conditional Bind); \+245 pts boost, \-\$2,140/yr savings, 60-day FAIR Plan take-out bind. |
| Scenario 3: Suburban Full Mitigation \+ HITL Check (Escondido, CA) | 595 (Tier 2 Baseline); Southern California WUI & convective hail corridor. | IBHS Wildfire Prepared Home Plus cert; UL 2218 Class 4 roof; Zone 0 clear; Flo smart shutoff active; simulated \+240 sq ft unpermitted Zone 1 structure. | Z\_ij \= 0.97; Posterior LCR \= 18 bps | 815 (Tier 1 Preferred) with 30% wildfire & 12.4% hail discounts; pauses on HITL\_TRIGGER\_02 for human review. |

6.3 Judge Defense FAQ

1\. "Why can't carriers just use First Street Foundation / Risk Factor, CoreLogic, or Moody's RMS?"  
First Street scores *environmental hazard* (1–10) at a 3m–30m grid resolution but is structurally blind to *parcel-level mitigation*: if a homeowner spends \$15,000 on an IBHS Wildfire Prepared Home Plus retrofit or \$12,500 on an IBHS FORTIFIED Roof (cutting hurricane claims by 73%), their First Street score does not change by a single point, making it unusable for statutory mitigation compliance under California 10 CCR § 2644.9. Meanwhile, Moody's RMS and Verisk include secondary structural modifiers in their stochastic models, but primary carriers have no automated pipeline to populate those inputs at point-of-quote without a \$450, 14-day physical inspection—defaulting back to coarse census-tract averages. SaveMyHome populates and prices those exact parcel features in 3.8 seconds via 1m LiDAR, 7.5cm CV, and Bühlmann-Straub credibility updating.

2\. "Why will state regulators (CDI, NY DFS, FL OIR) approve a Bayesian AI model over traditional catastrophe models?"  
Regulators reject black-box deep-learning *pricing* models because neural networks violate monotonicity and lack physical causality. SaveMyHome restricts neural networks (ViT / Mask R-CNN) strictly to *visual feature extraction* (replacing a human inspector's roof and Zone 0/1/2 measurements with an auditable image mask). The *pricing engine* is a closed-form Zero-Inflated Poisson and Generalized Pareto compound model updated via Bühlmann-Straub Empirical Bayes credibility—the gold standard under ASOP No. 25 for over 50 years. It satisfies CA 10 CCR § 2644.9 (12 mandatory mitigation factors), NY DFS Circular Letter No. 7 (zero socio-economic ECDIS, strict monotonicity $\partial SaveMyHome/\partial Mitigation>0$, and pre-computed BISG disparate impact audits), and Florida FCHLPM Standard G-4 (strict independence of meteorology, vulnerability, and actuarial components under Fla. Stat. § 627.0628).

3\. "How do you verify homeowner mitigations without sending an inspector?"  
SaveMyHome uses a Four-Tiered Multi-Modal Verification Protocol where each channel adds precision weight ${w}_{ij,m}$ to total parcel credibility ${Z}_{ij}=\frac{{w}_{ij}}{{w}_{ij}+k}$:

	⚬ *Tier 1 (Federal & Cryptographic Registries):* Intersects 1m USGS 3DEP LiDAR DEM/DSM with OpenFEMA NFIP `elevationCertificateIndicator` records ($\pm 0.3ft$ vertical precision) and queries IBHS FORTIFIED / Wildfire Prepared registries and municipal permit APIs (e.g., Louisiana 2025 Acts 144/239/422 roofing permits and CA Chapter 7A certificates).

	⚬ *Tier 2 (Sub-Decimeter Aerial & Satellite CV):* Segments 7.5cm Nearmap nadir/oblique orthophotos and 30cm Pléiades Neo imagery to verify roof class, Zone 1 detached structures (5–30 ft), and Zone 0 canopy overhang (0–5 ft).

	⚬ *Tier 3 (Continuous IoT Telemetry):* Ingests OAuth2 webhooks from Flo by Moen and Phyn smart shutoff valves and monitored fire alarms.

	⚬ *Tier 4 (Cryptographically Attested Smartphone Vision):* When nadir views are occluded (e.g., under-eave 1/4-in ember vents or shaded Zone 0 mulch), dispatches a 60-second browser capture flow enforcing GPS/RTK footprint geofencing, LiDAR depth-map anti-spoofing, and real-time on-device CV validation at zero field-surveyor cost.

Thoughts

