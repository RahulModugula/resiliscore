"use client";

import dynamic from "next/dynamic";
import { useEffect, useMemo, useState } from "react";
import { loadBuildingContext, type BlockContext } from "@/lib/manhattan/blockContext";
import { blockBuildingPlacement, terrainRange } from "@/lib/manhattan/blockElevation";
import { loadDetailedElevation } from "@/lib/manhattan/detailedElevation";
import { hasPrototypeTerrain, loadPrototypeElevation } from "@/lib/manhattan/prototypeElevation";
import styles from "./BlockContextView.module.css";

const Scene=dynamic(()=>import("./BlockContextScene"),{ssr:false,loading:()=> <p className={styles.fallback} role="status">Opening the 3D block view…</p>});
export function BlockContextView({property,onAddressResolved,prototypeTerrain=false,onPrototypeTerrainChange}:{property:{id:string;neighborhoodId:string};onAddressResolved?:(address:string|null)=>void;prototypeTerrain?:boolean;onPrototypeTerrainChange?:(value:boolean)=>void}) {
  const [loaded,setLoaded]=useState<{id:string;context:BlockContext}|null>(null);
  const [error,setError]=useState<string|null>(null);
  const [retry,setRetry]=useState(0);
  const [detailRetry,setDetailRetry]=useState(0);
  const [detailed,setDetailed]=useState<{id:string;terrain:BlockContext["terrain"]|null;status:"loading"|"ready"|"fallback"}|null>(null);
  const id=property.id,neighborhoodId=property.neighborhoodId;
  const prototype=hasPrototypeTerrain(id) && prototypeTerrain;
  const detailKey=`${id}:${prototype ? "2021" : "usgs"}`;
  useEffect(()=>{
    const controller=new AbortController();
    setError(null);
    void loadBuildingContext({id,neighborhoodId},controller.signal).then(context=>{
      if(controller.signal.aborted) return;
      setLoaded({id,context});onAddressResolved?.(context.selected.address);
    }).catch(error=>{if(!controller.signal.aborted) setError(error instanceof Error ? error.message : "Block context could not be loaded");});
    return ()=>controller.abort();
  },[id,neighborhoodId,retry,onAddressResolved]);
  const base=loaded?.id===id ? loaded.context : null;
  useEffect(()=>{
    if(!base) return;
    const controller=new AbortController();
    setDetailed({id:detailKey,terrain:null,status:"loading"});
    const load=prototype ? loadPrototypeElevation : loadDetailedElevation;
    void load(base.terrain.bounds,controller.signal).then(terrain=>{
      if(!controller.signal.aborted) setDetailed({id:detailKey,terrain,status:"ready"});
    }).catch(()=>{if(!controller.signal.aborted) setDetailed({id:detailKey,terrain:null,status:"fallback"});});
    return ()=>controller.abort();
  },[base,detailKey,detailRetry,prototype]);
  const context=useMemo(()=>base && detailed?.id===detailKey && detailed.terrain ? {...base,terrain:detailed.terrain} : base,[base,detailed,detailKey]);
  if(error) return <section className={styles.panel} aria-label="Building block context"><div className={styles.status}><h2>Building block context unavailable</h2><p role="status">{error}. Your risk assessment remains available.</p><button className="secondary-button" onClick={()=>setRetry(r=>r+1)}>Retry block context</button></div></section>;
  if(!context) return <section className={styles.panel} aria-label="Building block context"><p className={styles.status} role="status">Loading the selected building, neighboring streets and measured elevation…</p></section>;
  const {minM:min,maxM:max}=terrainRange(context.terrain);
  const placement=blockBuildingPlacement(context.selected,context.terrain);
  const ground=placement.range;
  const elevation=ground.minM;
  const detailStatus=detailed?.id===detailKey ? detailed.status : "loading";
  const fine=detailStatus==="ready";
  const streetNames=[...new Set(context.streets.map(s=>s.name))].sort();
  const groundText=elevation===null ? "Unknown" : `${elevation.toFixed(1)} m NAVD88`;
  return <section className={styles.panel} aria-label="Building block context">
    <div className={styles.heading}><h2>{context.selected.address??"Address unavailable"}</h2><span>{context.taxBlock ? context.wholeBlock ? `Tax block ${Number(context.taxBlock.slice(1))} and adjoining streets` : `Local part of tax block ${Number(context.taxBlock.slice(1))}` : "Approximate one-block vicinity"}</span></div>
    <div className={styles.elevationStatus} role="status" data-testid="block-elevation-status"><span>{fine ? prototype ? `${context.terrain.raster!.nominalSpacingM.toFixed(1)} m derived ground grid · NYC 2021 prototype` : `${context.terrain.raster!.nominalSpacingM.toFixed(1)} m ground grid · USGS 3DEP` : "10 m cached ground grid · USGS 3DEP"}{detailStatus==="loading" ? prototype ? " · Loading 2021 terrain…" : " · Loading finer terrain…" : !fine ? prototype ? " · 2021 terrain unavailable; cached elevations retained." : " · Finer terrain unavailable; cached elevations retained." : ""}</span>{detailStatus==="fallback" && <button className="text-button" onClick={()=>setDetailRetry(value=>value+1)}>{prototype ? "Retry 2021 terrain" : "Retry finer terrain"}</button>}{hasPrototypeTerrain(id) && onPrototypeTerrainChange && <button className="text-button" onClick={()=>{const next=!prototype;onPrototypeTerrainChange(next);const url=new URL(window.location.href);if(next) url.searchParams.set("terrain","nyc2021");else url.searchParams.delete("terrain");window.history.replaceState(null,"",`${url.pathname}${url.search}`);}}>{prototype ? "Use USGS terrain" : "Try 2021 terrain"}</button>}</div>
    <p className={styles.qualityNote}>{prototype ? "Experimental terrain from May 2021 classified ground points. Only nearby ground is interpolated; larger gaps remain unknown. Historical terrain is not a current survey. Grid spacing is not vertical accuracy." : "Historical terrain can retain pits, spikes and construction changes. Grid spacing is not vertical accuracy."}</p>
    {placement.conflict && <p className={styles.qualityNote} role="status">Ground samples exceed this building’s recorded height. Its footprint is shown; the 3D height needs review.</p>}
    <Scene context={context}/>
    <dl className={styles.measurements}>
      <div><dt>Selected ground elevation</dt><dd>{groundText}</dd></div>
      <div><dt>Building height above ground</dt><dd>{context.selected.heightM===null ? "Unknown" : `${context.selected.heightM.toFixed(1)} m`}</dd></div>
      <div><dt>Block ground elevation</dt><dd>{min!==null && max!==null ? <span className={styles.legend}><span>{min.toFixed(1)} m</span><span className={styles.ramp} aria-hidden="true"/><span>{max.toFixed(1)} m</span></span> : "Unknown"}</dd></div>
    </dl>
    <p className={styles.nearby}>Ground at the building base: {ground.minM===null ? "Unknown" : `${ground.minM.toFixed(1)}–${ground.maxM!.toFixed(1)} m NAVD88 along the sampled footprint`}.{ground.known<ground.total ? ` ${ground.known} of ${ground.total} perimeter samples are supported; this is a partial range.` : ""} {placement.conflict ? "The supplied height is retained in the assessment; conflicting terrain prevents a 3D extrusion." : "Building height is retained above the lowest supported ground."} First-floor elevation remains unknown.</p>
    <p className={styles.nearby}>Nearby streets: {streetNames.slice(0,4).join(" · ")||"No mapped at-grade streets"}{streetNames.length>4 ? ` · +${streetNames.length-4} in source details` : ""}</p>
    <details className={styles.details}><summary>{context.buildings.length} mapped buildings · {streetNames.length} neighboring streets · Source details</summary>
      <p>The selected building is cyan. Ground and buildings are shown at true scale. Ground elevation is metres relative to NAVD88. The selected ground value is the lowest supported perimeter sample, not the footprint centre or a first-floor measurement. Building heights remain above the lowest supported ground; long walls follow sampled terrain. Buildings with conflicting ground and height observations are shown as footprints. The DEM represents bare earth and does not measure roof shape or current construction. Missing elevation samples leave gaps. Map elevation is context, not certified freeboard or a risk-model input.</p>
      <p>Streets: {streetNames.join(" · ")||"No street centerlines in this extent"}.</p>
      <ul aria-label="Surrounding building addresses">{context.buildings.map(building=><li key={building.id}>{building.id===context.selected.id ? "Selected: " : ""}{building.address??"Address unavailable"} · {building.bin ? `BIN ${building.bin}` : `Source ID ${building.id}`}</li>)}</ul>
      <p><a href="https://data.cityofnewyork.us/d/64uk-42ks" target="_blank" rel="noreferrer">NYC DCP PLUTO tax-lot addresses</a> join by exact BBL. Buildings on one lot may share its primary address. <a href="https://data.cityofnewyork.us/d/inkn-q76z" target="_blank" rel="noreferrer">NYC OTI street centerlines</a> use source widths when supplied and thin centerlines otherwise; ribbons do not establish curb boundaries. Only constructed at-grade segments are shown; bridges and tunnels are omitted.</p>
      <p>Terrain source: {context.terrain.source}. {fine && prototype ? <>Ground classes 2 and 8, excluding withheld points, are interpolated with a linear TIN limited to a 10 m triangle edge, 5 m circumradius and 3 m nearest ground point. Buildings without supported perimeter ground retain their existing source-ground estimate, which is not a 2021 measurement. This prototype covers this building context only. Units, support limits and provenance are recorded in the <a href="/manhattan/prototypes/nyc2021-murray-hill.json" target="_blank" rel="noreferrer">2021 prototype manifest</a>.</> : <>Native sources and acquisition vintages are recorded in the <a href="/manhattan/dem-provenance.json" target="_blank" rel="noreferrer">USGS source snapshot</a>. Large blocks use a coarser grid to keep the view responsive.</>} Grid spacing is display resolution, not vertical accuracy. Buildings: NYC OTI Building Footprints. {context.taxBlock ? context.wholeBlock ? "Extent includes this tax block and adjoining street frontage." : "This unusually large tax block is shown as a local 180-metre vicinity around the chosen footprint." : "No valid tax block is available; extent is an approximate 180-metre vicinity."}</p>
    </details>
  </section>;
}
