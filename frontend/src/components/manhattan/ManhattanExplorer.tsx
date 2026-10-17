"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowLeft, ArrowRight, Building2, ChevronRight, CircleHelp, Layers3, LoaderCircle, MapPin, Mountain, RotateCcw, Search, ShieldCheck, X } from "lucide-react";
import { assessManhattanProperty, propertyLabel, saveManhattanAssessment } from "@/lib/manhattan/assessment";
import { loadManhattan, loadNeighborhood } from "@/lib/manhattan/data";
import { loadAddressIndex, resolveBuildingAddress, type AddressIndex } from "@/lib/manhattan/blockContext";
import type { Building, NeighborhoodDetail } from "@/lib/manhattan/types";
import styles from "./ManhattanExplorer.module.css";

const Scene = dynamic(() => import("./ManhattanScene"), { ssr: false, loading: () => <div className={styles.mapLoading}><LoaderCircle size={20} className={styles.spinner} /><span>Preparing the 3D map…</span></div> });
type MapData = Awaited<ReturnType<typeof loadManhattan>>;

function addressBuildings(buildings: Building[], index: AddressIndex) {
  return buildings.map(building => ({ ...building, address: resolveBuildingAddress(building, index) }));
}

function mapUrl(neighborhoodId: string | null, demo: boolean) {
  const params = new URLSearchParams();
  if (neighborhoodId) params.set("neighborhood", neighborhoodId);
  if (demo) params.set("workflow", "demo");
  return params.size ? `/?${params}` : "/";
}

export default function ManhattanExplorer() {
  const router = useRouter();
  const [data, setData] = useState<MapData | null>(null);
  const [loadError, setLoadError] = useState("");
  const [retry, setRetry] = useState(0);
  const [neighborhoodId, setNeighborhoodId] = useState<string | null>(null);
  const [detail, setDetail] = useState<NeighborhoodDetail | null>(null);
  const [detailError, setDetailError] = useState("");
  const [detailRetry, setDetailRetry] = useState(0);
  const [query, setQuery] = useState("");
  const [limit, setLimit] = useState(60);
  const [underground, setUnderground] = useState(false);
  const [terrainMode, setTerrainMode] = useState(false);
  const [reliefScale, setReliefScale] = useState(1);
  const [layersExpanded, setLayersExpanded] = useState(false);
  const [sceneError, setSceneError] = useState("");
  const [sceneReady, setSceneReady] = useState(false);
  const [pending, setPending] = useState<Building | null>(null);
  const [assessmentError, setAssessmentError] = useState("");
  const [buildingDemo, setBuildingDemo] = useState(false);
  const demoHeading = useRef<HTMLHeadingElement | null>(null);
  const assessmentController = useRef<AbortController | null>(null);
  const addressIndex = useRef<AddressIndex>({});
  const [addressError, setAddressError] = useState(false);
  const neighborhood = data?.neighborhoods.find(item => item.id === neighborhoodId) ?? null;
  const activeDetail = detail?.neighborhoodId === neighborhoodId ? detail : null;
  const detailPending = !!neighborhoodId && !activeDetail && !detailError;
  const ready = useCallback(() => { setSceneReady(true); setSceneError(""); }, []);
  const failScene = useCallback((message: string) => setSceneError(message), []);

  useEffect(() => {
    setBuildingDemo(new URLSearchParams(window.location.search).get("workflow") === "demo");
  }, []);
  useEffect(() => {
    if (!buildingDemo) return;
    demoHeading.current?.focus({ preventScroll: true });
    const bounds = demoHeading.current?.getBoundingClientRect();
    if (bounds && (bounds.top < 0 || bounds.bottom > window.innerHeight)) demoHeading.current?.scrollIntoView({ block: "center" });
  }, [buildingDemo]);

  useEffect(() => {
    const controller = new AbortController();
    setLoadError("");
    setAddressError(false);
    const addresses = loadAddressIndex(controller.signal).catch(error => {
      if (controller.signal.aborted) throw error;
      setAddressError(true);
      return {};
    });
    void Promise.all([loadManhattan(controller.signal), addresses]).then(([result, index]) => {
      if (controller.signal.aborted) return;
      addressIndex.current = index;
      setData({ ...result, overview: { ...result.overview, buildings: addressBuildings(result.overview.buildings, index) } });
      const requested = new URLSearchParams(window.location.search).get("neighborhood");
      if (result.neighborhoods.some(item => item.id === requested)) setNeighborhoodId(requested);
    }).catch(error => { if (!controller.signal.aborted) setLoadError(error instanceof Error ? error.message : "Map data could not be loaded"); });
    return () => controller.abort();
  }, [retry]);

  useEffect(() => {
    if (!data || !neighborhoodId) return;
    const controller = new AbortController();
    setDetailError("");
    void loadNeighborhood(data.manifest, neighborhoodId, controller.signal).then(result => { if (!controller.signal.aborted) setDetail({ ...result, buildings: addressBuildings(result.buildings, addressIndex.current) }); })
      .catch(error => { if (!controller.signal.aborted) setDetailError(error instanceof Error ? error.message : "Neighborhood detail could not be loaded"); });
    return () => controller.abort();
  }, [data, neighborhoodId, detailRetry]);
  useEffect(() => () => assessmentController.current?.abort(), []);

  const visibleNeighborhoods = useMemo(() => (data?.neighborhoods ?? []).filter(item => `${item.name} ${item.id}`.toLowerCase().includes(query.toLowerCase())).sort((a, b) => a.name.localeCompare(b.name)), [data, query]);
  const matchingBuildings = useMemo(() => (activeDetail?.buildings ?? []).filter(building => `${propertyLabel(building)} ${building.name ?? ""} ${building.bin ?? ""} ${building.bbl ?? ""}`.toLowerCase().includes(query.toLowerCase())).sort((a, b) => propertyLabel(a).localeCompare(propertyLabel(b))), [activeDetail, query]);

  function selectNeighborhood(id: string | null) {
    if (id !== null && !data?.neighborhoods.some(item => item.id === id)) return;
    if (id === neighborhoodId && detailError) setDetailRetry(value => value + 1);
    assessmentController.current?.abort();
    setPending(null); setAssessmentError(""); setNeighborhoodId(id); setDetailError(""); setQuery(""); setLimit(60);
    window.history.replaceState(null, "", mapUrl(id, buildingDemo));
  }

  function changeBuildingDemo() {
    assessmentController.current?.abort();
    setPending(null); setAssessmentError("");
    setBuildingDemo(value => !value);
    const requestedNeighborhood = neighborhoodId ?? new URLSearchParams(window.location.search).get("neighborhood");
    window.history.replaceState(null, "", mapUrl(requestedNeighborhood, !buildingDemo));
  }

  async function selectBuilding(building: Building) {
    assessmentController.current?.abort();
    const controller = new AbortController();
    assessmentController.current = controller;
    setPending(building); setAssessmentError("");
    try {
      const result = await assessManhattanProperty(building, { signal: controller.signal, preferLive: !buildingDemo });
      if (controller.signal.aborted) return;
      if (!saveManhattanAssessment(building.id, result)) throw new Error("Your browser could not save this assessment. Allow session storage, then select the property again.");
      router.push(`/assessment?property=${encodeURIComponent(building.id)}${buildingDemo ? "&workflow=demo" : ""}`);
    } catch (error) {
      if (!controller.signal.aborted) { setAssessmentError(error instanceof Error ? error.message : "Assessment could not be opened. Select the property to retry."); setPending(null); }
    }
  }

  const infrastructure = (activeDetail ?? data?.overview)?.infrastructure;
  const terrain = (activeDetail ?? data?.overview)?.terrain;
  const elevationRange = useMemo(() => {
    let min = Infinity, max = -Infinity;
    for (const value of terrain?.elevationsM ?? []) if (value !== null) { min = Math.min(min, value); max = Math.max(max, value); }
    return Number.isFinite(min) ? [Math.floor(min), Math.ceil(max)] : null;
  }, [terrain]);
  return <div className={`app-shell ${styles.explorer}`}>
    <a className="skip-link" href="#map-directory">Skip to neighborhood and property list</a>
    <header className={styles.header}>
      <Link href="/" className="brand" aria-label="SaveMyHome map home"><span className="brand-mark"><ShieldCheck size={23} /></span>SaveMyHome</Link>
      <span className={styles.headerContext}>Manhattan property explorer</span>
      <button className={`secondary-button ${styles.demoLink}`} aria-pressed={buildingDemo} onClick={changeBuildingDemo}>{buildingDemo ? "Exit building demo" : "Try building demo"}<ArrowRight size={15} /></button>
    </header>
    <main className={styles.layout}>
      <aside className={styles.directory} id="map-directory" tabIndex={-1} aria-label="Neighborhood and property directory">
        <div className={styles.directoryHeading}>
          {neighborhood && <button className={styles.back} onClick={() => selectNeighborhood(null)}><ArrowLeft size={15} />All Manhattan</button>}
          <h1>{neighborhood ? neighborhood.name : "Manhattan"}</h1>
          <p>{buildingDemo ? "Explore the demo on a real map building." : neighborhood ? "Select a building to run its risk assessment." : "Choose a neighborhood, then a property to assess."}</p>
          {buildingDemo && <section className={styles.demoIntro} aria-labelledby="building-demo-intro"><h2 id="building-demo-intro" ref={demoHeading} tabIndex={-1}>Underwriting demo</h2><p>{neighborhood ? "Choose a building here or on the map to test a roof improvement, simulated verification and a demo binding receipt." : "Choose a neighborhood, then a real building to test improvements and simulated verification/binding."}</p><small>Runs offline with model defaults. No policy issued.</small></section>}
        </div>
        <label className={styles.search}><Search size={17} /><span className={styles.srOnly}>{neighborhood ? "Find a property by address, BIN, or BBL" : "Find a neighborhood"}</span><input type="search" value={query} placeholder={neighborhood ? "Search address, BIN, or BBL" : "Find a neighborhood"} onChange={event => { setQuery(event.target.value); setLimit(60); }} /></label>
        <div className={styles.listHeading}><span>{neighborhood ? "Mapped buildings" : "Neighborhoods & park areas"}</span><span>{neighborhood ? activeDetail ? matchingBuildings.length.toLocaleString() : "…" : visibleNeighborhoods.length || "…"}</span></div>
        {addressError && <div className={styles.addressNotice} role="status"><p>Street addresses could not be loaded. Unresolved addresses remain unknown.</p><button className="text-button" onClick={() => setRetry(value => value + 1)}>Retry addresses</button></div>}
        <div className={styles.list} aria-busy={(!data && !loadError) || detailPending}>
          {loadError ? <div className={styles.listMessage} role="alert"><p>{loadError}</p><button className="secondary-button" onClick={() => setRetry(value => value + 1)}>Reload map data</button></div>
            : !data ? <p className={styles.listMessage} role="status">Loading Manhattan data…</p>
              : detailPending ? <p className={styles.listMessage} role="status">Loading building footprints, parks, and terrain…</p>
                : detailError ? <div className={styles.listMessage} role="alert"><p>{detailError}</p><button className="secondary-button" onClick={() => setDetailRetry(value => value + 1)}>Retry neighborhood</button></div>
                  : neighborhood ? <>
                    {!matchingBuildings.length && <p className={styles.listMessage}>{query ? "No buildings match this search." : "No building footprints are published for this area. Choose another neighborhood."}</p>}
                    <ul aria-label="Properties">{matchingBuildings.slice(0, limit).map(building => <li key={building.id}><button className={styles.listButton} aria-label={`${buildingDemo ? "Demo" : "Assess"} ${propertyLabel(building)}${!building.address ? `, ${building.bin ? `BIN ${building.bin}` : `source ${building.id}`}` : ""}`} aria-pressed={pending?.id === building.id} onClick={() => void selectBuilding(building)}><Building2 size={16} /><span><strong>{propertyLabel(building)}</strong><small>{building.name && building.name.toLowerCase() !== building.address?.toLowerCase() ? `${building.name} · ` : ""}{building.heightM === null ? "Height unknown" : `${Math.round(building.heightM)} m tall`}{building.yearBuilt ? ` · Built ${building.yearBuilt}` : " · Build year unknown"}{!building.address ? ` · ${building.bin ? `BIN ${building.bin}` : `Source ${building.id}`}` : ""}</small></span><ChevronRight size={15} /></button></li>)}</ul>
                    {matchingBuildings.length > limit && <button className={styles.more} onClick={() => setLimit(value => value + 60)}>Show more properties</button>}
                  </> : <>
                    {!visibleNeighborhoods.length && <p className={styles.listMessage}>No neighborhoods match this search.</p>}
                    <ul aria-label="Neighborhoods">{visibleNeighborhoods.map(item => <li key={item.id}><button className={styles.listButton} onClick={() => selectNeighborhood(item.id)}><span><strong>{item.name}</strong><small>{item.type === "9" ? "Park or special-use area" : "Neighborhood area"}</small></span><ChevronRight size={16} /></button></li>)}</ul>
                  </>}
        </div>
        <div className={styles.directoryFoot}><div><MapPin size={14} /><span>NYC mapped footprints, not surveyed parcel boundaries</span></div><Link href="/assessment?demo=true">Sample scenarios<ArrowRight size={12} /></Link></div>
      </aside>
      <section className={styles.map} aria-label="Interactive 3D Manhattan map" aria-describedby="map-instructions">
        {data && <Scene neighborhoods={data.neighborhoods} overview={data.overview} detail={activeDetail} selectedNeighborhoodId={neighborhoodId} selectedBuildingId={pending?.id} showUnderground={underground} showTerrain={terrainMode} verticalScale={terrainMode ? reliefScale : 1} onNeighborhoodSelect={selectNeighborhood} onBuildingSelect={building => void selectBuilding(building)} onReady={ready} onError={failScene} />}
        {!data && <div className={styles.mapLoading}><Layers3 size={28} /><p>{loadError ? "Map data unavailable" : "Loading the island…"}</p></div>}
        <div className={styles.mapToolbar}><div className={styles.breadcrumb}><span>New York</span><ChevronRight size={13} /><button onClick={() => selectNeighborhood(null)}>Manhattan</button>{neighborhood && <><ChevronRight size={13} /><span>{neighborhood.name}</span></>}</div><button className={styles.reset} aria-label="Return to all Manhattan" onClick={() => selectNeighborhood(null)}><RotateCcw size={16} /><span>Island view</span></button></div>
        <div className={styles.layerControls}>
          <button className={styles.mobileLayers} aria-expanded={layersExpanded} aria-controls="map-layer-settings" onClick={() => setLayersExpanded(value => !value)}>
            <span><Layers3 size={17} />{layersExpanded ? "Close map layers" : "Map layers"}</span>
            {(terrainMode || underground) && <small>{[terrainMode ? `Terrain ${reliefScale}×` : null, underground ? "Drainage" : null].filter(Boolean).join(" · ")}</small>}
          </button>
          <div id="map-layer-settings" className={`${styles.layerSettings} ${layersExpanded ? styles.layersExpanded : ""}`}>
          <label className={styles.layerToggle}><Mountain size={17} /><span>Terrain relief</span><input type="checkbox" checked={terrainMode} onChange={event => setTerrainMode(event.target.checked)} /></label>
          {terrainMode && <div className={styles.terrainLegend}>
            <p>USGS ground elevation · metres</p>
            <div className={styles.elevationRamp} aria-hidden="true" />
            <div className={styles.elevationLabels}><span>0 m NAVD88</span><span>100 m</span></div>
            {elevationRange && <p className={styles.groundRange}>Ground in view {elevationRange[0]}–{elevationRange[1]} m</p>}
            <fieldset className={styles.reliefScale}><legend>Ground height scale</legend>{[1, 3].map(scale => <label key={scale}><input type="radio" name="relief-scale" value={scale} checked={reliefScale === scale} onChange={() => setReliefScale(scale)} /><span>{scale === 1 ? "1× actual" : "3× relief"}</span></label>)}</fieldset>
            <p className={styles.reliefNote} role="status">{reliefScale === 1 ? "Actual ground heights. Buildings fade to reveal slopes." : "Ground heights exaggerated 3× for viewing. Assessment inputs stay unchanged."}</p>
          </div>}
          <label className={styles.layerToggle}><Layers3 size={17} /><span>Underground drainage</span><input type="checkbox" checked={underground} onChange={event => setUnderground(event.target.checked)} /></label>
          {underground && <div className={styles.undergroundLegend} role="status"><div><i className={styles.drainSwatch} /><span>DEP storm drains · {infrastructure?.stormDrains.length.toLocaleString() ?? 0}</span></div><div><i className={styles.pipeSwatch} /><span>Historic illustrative interceptors</span></div><p>Incomplete, not DEP-verified. Depths unavailable; vertical offset is schematic. No drain-to-pipe connections inferred.</p></div>}
          </div>
        </div>
        <div className={styles.mapBottom}><p id="map-instructions" className={styles.instructions}>{sceneError || (!sceneReady && data ? "Preparing 3D view. The directory is ready to use." : neighborhood ? `Click a building to ${buildingDemo ? "try the demo" : "assess"} · Drag to orbit · Scroll to zoom` : "Click a neighborhood to explore · Drag to orbit · Scroll to zoom")}</p><details className={styles.sources}><summary><CircleHelp size={15} />Map sources & accuracy</summary><div className={styles.sourceContent}><h2>About this map</h2><p>Geographic building massing from NYC footprints and roof heights, placed on sampled USGS 3DEP bare-earth terrain. Missing heights remain flat footprints. Terrain relief can exaggerate ground heights 3× for inspection; the default 1× scale uses actual elevations. Visual scale does not change risk inputs.</p><p>Neighborhoods follow NYC 2020 statistical boundaries. Open Sewer Atlas lines are historical, partial, and illustrative. Drain depths and pipe connections are unknown. This map is not suitable for excavation or engineering design.</p><ul>{data?.manifest.sources.map(source => <li key={source.url}><a href={source.url} target="_blank" rel="noreferrer">{source.name}</a><small>Retrieved {source.retrievedAt.slice(0, 10)}</small></li>)}</ul></div></details></div>
        {(pending || assessmentError) && <div className={styles.assessing} role="status">{pending ? <><LoaderCircle size={20} className={styles.spinner} /><div><strong>{buildingDemo ? "Opening demo for" : "Assessing"} {propertyLabel(pending)}</strong><p>{buildingDemo ? "Preparing offline model scenarios for this building." : "Checking the risk API. Cached model screening is available offline."}</p></div><button aria-label="Cancel assessment" onClick={() => { assessmentController.current?.abort(); setPending(null); }}><X size={18} /></button></> : <><p>{assessmentError}</p><button aria-label="Dismiss assessment error" onClick={() => setAssessmentError("")}><X size={18} /></button></>}</div>}
      </section>
    </main>
  </div>;
}
