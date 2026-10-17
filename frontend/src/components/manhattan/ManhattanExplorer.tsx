"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowLeft, ArrowRight, Building2, ChevronRight, CircleHelp, Layers3, LoaderCircle, MapPin, RotateCcw, Search, ShieldCheck, X } from "lucide-react";
import { assessManhattanProperty, propertyLabel, saveManhattanAssessment } from "@/lib/manhattan/assessment";
import { loadManhattan, loadNeighborhood } from "@/lib/manhattan/data";
import type { Building, NeighborhoodDetail } from "@/lib/manhattan/types";
import styles from "./ManhattanExplorer.module.css";

const Scene = dynamic(() => import("./ManhattanScene"), { ssr: false, loading: () => <div className={styles.mapLoading}><LoaderCircle size={20} className={styles.spinner} /><span>Preparing the 3D map…</span></div> });
type MapData = Awaited<ReturnType<typeof loadManhattan>>;

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
  const [sceneError, setSceneError] = useState("");
  const [sceneReady, setSceneReady] = useState(false);
  const [pending, setPending] = useState<Building | null>(null);
  const [assessmentError, setAssessmentError] = useState("");
  const assessmentController = useRef<AbortController | null>(null);
  const neighborhood = data?.neighborhoods.find(item => item.id === neighborhoodId) ?? null;
  const activeDetail = detail?.neighborhoodId === neighborhoodId ? detail : null;
  const detailPending = !!neighborhoodId && !activeDetail && !detailError;
  const ready = useCallback(() => { setSceneReady(true); setSceneError(""); }, []);
  const failScene = useCallback((message: string) => setSceneError(message), []);

  useEffect(() => {
    const controller = new AbortController();
    setLoadError("");
    void loadManhattan(controller.signal).then(result => {
      setData(result);
      const requested = new URLSearchParams(window.location.search).get("neighborhood");
      if (result.neighborhoods.some(item => item.id === requested)) setNeighborhoodId(requested);
    }).catch(error => { if (!controller.signal.aborted) setLoadError(error instanceof Error ? error.message : "Map data could not be loaded"); });
    return () => controller.abort();
  }, [retry]);

  useEffect(() => {
    if (!data || !neighborhoodId) return;
    const controller = new AbortController();
    setDetailError("");
    void loadNeighborhood(data.manifest, neighborhoodId, controller.signal).then(setDetail)
      .catch(error => { if (!controller.signal.aborted) setDetailError(error instanceof Error ? error.message : "Neighborhood detail could not be loaded"); });
    return () => controller.abort();
  }, [data, neighborhoodId, detailRetry]);
  useEffect(() => () => assessmentController.current?.abort(), []);

  const visibleNeighborhoods = useMemo(() => (data?.neighborhoods ?? []).filter(item => `${item.name} ${item.id}`.toLowerCase().includes(query.toLowerCase())).sort((a, b) => a.name.localeCompare(b.name)), [data, query]);
  const matchingBuildings = useMemo(() => (activeDetail?.buildings ?? []).filter(building => `${propertyLabel(building)} ${building.bbl ?? ""}`.toLowerCase().includes(query.toLowerCase())).sort((a, b) => propertyLabel(a).localeCompare(propertyLabel(b))), [activeDetail, query]);

  function selectNeighborhood(id: string | null) {
    if (id !== null && !data?.neighborhoods.some(item => item.id === id)) return;
    assessmentController.current?.abort();
    setPending(null); setAssessmentError(""); setNeighborhoodId(id); setDetailError(""); setQuery(""); setLimit(60);
    window.history.replaceState(null, "", id ? `/?neighborhood=${encodeURIComponent(id)}` : "/");
  }

  async function selectBuilding(building: Building) {
    assessmentController.current?.abort();
    const controller = new AbortController();
    assessmentController.current = controller;
    setPending(building); setAssessmentError("");
    try {
      const result = await assessManhattanProperty(building, { signal: controller.signal, preferLive: true });
      if (controller.signal.aborted) return;
      if (!saveManhattanAssessment(building.id, result)) throw new Error("Your browser could not save this assessment. Allow session storage, then select the property again.");
      router.push(`/assessment?property=${encodeURIComponent(building.id)}`);
    } catch (error) {
      if (!controller.signal.aborted) { setAssessmentError(error instanceof Error ? error.message : "Assessment could not be opened. Select the property to retry."); setPending(null); }
    }
  }

  const infrastructure = (activeDetail ?? data?.overview)?.infrastructure;
  return <div className={`app-shell ${styles.explorer}`}>
    <a className="skip-link" href="#map-directory">Skip to neighborhood and property list</a>
    <header className={styles.header}>
      <Link href="/" className="brand" aria-label="ResiliScore map home"><span className="brand-mark"><ShieldCheck size={23} /></span>ResiliScore</Link>
      <span className={styles.headerContext}>Manhattan property explorer</span>
      <Link href="/assessment?demo=true" className={styles.demoLink}>Open demo workspace<ArrowRight size={15} /></Link>
    </header>
    <main className={styles.layout}>
      <aside className={styles.directory} id="map-directory" tabIndex={-1} aria-label="Neighborhood and property directory">
        <div className={styles.directoryHeading}>
          {neighborhood && <button className={styles.back} onClick={() => selectNeighborhood(null)}><ArrowLeft size={15} />All Manhattan</button>}
          <h1>{neighborhood ? neighborhood.name : "Manhattan"}</h1>
          <p>{neighborhood ? "Select a building to run its risk assessment." : "Choose a neighborhood, then a property to assess."}</p>
        </div>
        <label className={styles.search}><Search size={17} /><span className={styles.srOnly}>{neighborhood ? "Find a property by name, BIN, or BBL" : "Find a neighborhood"}</span><input type="search" value={query} placeholder={neighborhood ? "Search name, BIN, or BBL" : "Find a neighborhood"} onChange={event => { setQuery(event.target.value); setLimit(60); }} /></label>
        <div className={styles.listHeading}><span>{neighborhood ? "Mapped buildings" : "Neighborhoods & park areas"}</span><span>{neighborhood ? activeDetail ? matchingBuildings.length.toLocaleString() : "…" : visibleNeighborhoods.length || "…"}</span></div>
        <div className={styles.list} aria-busy={!data || detailPending}>
          {loadError ? <div className={styles.listMessage} role="alert"><p>{loadError}</p><button className="secondary-button" onClick={() => setRetry(value => value + 1)}>Reload map data</button></div>
            : !data ? <p className={styles.listMessage} role="status">Loading Manhattan data…</p>
              : detailPending ? <p className={styles.listMessage} role="status">Loading building footprints, parks, and terrain…</p>
                : detailError ? <div className={styles.listMessage} role="alert"><p>{detailError}</p><button className="secondary-button" onClick={() => setDetailRetry(value => value + 1)}>Retry neighborhood</button></div>
                  : neighborhood ? <>
                    {!matchingBuildings.length && <p className={styles.listMessage}>{query ? "No buildings match this search." : "No building footprints are published for this area. Choose another neighborhood."}</p>}
                    <ul aria-label="Properties">{matchingBuildings.slice(0, limit).map(building => <li key={building.id}><button className={styles.listButton} aria-label={`Assess ${propertyLabel(building)}`} aria-pressed={pending?.id === building.id} onClick={() => void selectBuilding(building)}><Building2 size={16} /><span><strong>{propertyLabel(building)}</strong><small>{building.heightM === null ? "Height unknown" : `${Math.round(building.heightM)} m tall`}{building.yearBuilt ? ` · Built ${building.yearBuilt}` : " · Build year unknown"}</small></span><ChevronRight size={15} /></button></li>)}</ul>
                    {matchingBuildings.length > limit && <button className={styles.more} onClick={() => setLimit(value => value + 60)}>Show more properties</button>}
                  </> : <>
                    {!visibleNeighborhoods.length && <p className={styles.listMessage}>No neighborhoods match this search.</p>}
                    <ul aria-label="Neighborhoods">{visibleNeighborhoods.map(item => <li key={item.id}><button className={styles.listButton} onClick={() => selectNeighborhood(item.id)}><span><strong>{item.name}</strong><small>{item.type === "9" ? "Park or special-use area" : "Neighborhood area"}</small></span><ChevronRight size={16} /></button></li>)}</ul>
                  </>}
        </div>
        <div className={styles.directoryFoot}><MapPin size={14} /><span>NYC mapped footprints, not surveyed parcel boundaries</span></div>
      </aside>
      <section className={styles.map} aria-label="Interactive 3D Manhattan map" aria-describedby="map-instructions">
        {data && <Scene neighborhoods={data.neighborhoods} overview={data.overview} detail={activeDetail} selectedNeighborhoodId={neighborhoodId} selectedBuildingId={pending?.id} showUnderground={underground} onNeighborhoodSelect={selectNeighborhood} onBuildingSelect={building => void selectBuilding(building)} onReady={ready} onError={failScene} />}
        {!data && <div className={styles.mapLoading}><Layers3 size={28} /><p>{loadError ? "Map data unavailable" : "Loading the island…"}</p></div>}
        <div className={styles.mapToolbar}><div className={styles.breadcrumb}><span>New York</span><ChevronRight size={13} /><button onClick={() => selectNeighborhood(null)}>Manhattan</button>{neighborhood && <><ChevronRight size={13} /><span>{neighborhood.name}</span></>}</div><button className={styles.reset} aria-label="Return to all Manhattan" onClick={() => selectNeighborhood(null)}><RotateCcw size={16} /><span>Island view</span></button></div>
        <div className={styles.layerControls}>
          <label className={styles.layerToggle}><Layers3 size={17} /><span>Underground drainage</span><input type="checkbox" checked={underground} onChange={event => setUnderground(event.target.checked)} /></label>
          {underground && <div className={styles.undergroundLegend} role="status"><div><i className={styles.drainSwatch} /><span>DEP storm drains · {infrastructure?.stormDrains.length.toLocaleString() ?? 0}</span></div><div><i className={styles.pipeSwatch} /><span>Historic illustrative interceptors</span></div><p>Incomplete, not DEP-verified. Depths unavailable; vertical offset is schematic. No drain-to-pipe connections inferred.</p></div>}
        </div>
        <div className={styles.mapBottom}><p id="map-instructions" className={styles.instructions}>{sceneError || (!sceneReady && data ? "Preparing 3D view. The directory is ready to use." : neighborhood ? "Click a building to assess · Drag to orbit · Scroll to zoom" : "Click a neighborhood to explore · Drag to orbit · Scroll to zoom")}</p><details className={styles.sources}><summary><CircleHelp size={15} />Map sources & accuracy</summary><div className={styles.sourceContent}><h2>About this map</h2><p>Geographic building massing from NYC footprints and roof heights. Ground elevations are interpolated from building-base observations, not a surveyed terrain model. Missing heights use a display height.</p><p>Neighborhoods follow NYC 2020 statistical boundaries. Open Sewer Atlas lines are historical, partial, and illustrative. Drain depths and pipe connections are unknown. This map is not suitable for excavation or engineering design.</p><ul>{data?.manifest.sources.map(source => <li key={source.url}><a href={source.url} target="_blank" rel="noreferrer">{source.name}</a><small>Retrieved {source.retrievedAt.slice(0, 10)}</small></li>)}</ul></div></details></div>
        {(pending || assessmentError) && <div className={styles.assessing} role="status">{pending ? <><LoaderCircle size={20} className={styles.spinner} /><div><strong>Assessing {propertyLabel(pending)}</strong><p>Checking the risk API. Cached model screening is available offline.</p></div><button aria-label="Cancel assessment" onClick={() => { assessmentController.current?.abort(); setPending(null); }}><X size={18} /></button></> : <><p>{assessmentError}</p><button aria-label="Dismiss assessment error" onClick={() => setAssessmentError("")}><X size={18} /></button></>}</div>}
      </section>
    </main>
  </div>;
}
