"use client";

import dynamic from "next/dynamic";
import { useEffect, useMemo, useState } from "react";
import { loadBuildingContext, type BlockContext } from "@/lib/manhattan/blockContext";
import { buildingGroundRange, terrainRange } from "@/lib/manhattan/blockElevation";
import { loadDetailedElevation } from "@/lib/manhattan/detailedElevation";
import styles from "./BlockContextView.module.css";

const Scene=dynamic(()=>import("./BlockContextScene"),{ssr:false,loading:()=> <p className={styles.fallback} role="status">Opening the 3D block view…</p>});
export function BlockContextView({property,onAddressResolved}:{property:{id:string;neighborhoodId:string};onAddressResolved?:(address:string|null)=>void}) {
  const [loaded,setLoaded]=useState<{id:string;context:BlockContext}|null>(null);
  const [error,setError]=useState<string|null>(null);
  const [retry,setRetry]=useState(0);
  const [detailRetry,setDetailRetry]=useState(0);
  const [detailed,setDetailed]=useState<{id:string;terrain:BlockContext["terrain"]|null;status:"loading"|"ready"|"fallback"}|null>(null);
  const id=property.id,neighborhoodId=property.neighborhoodId;
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
    setDetailed({id,terrain:null,status:"loading"});
    void loadDetailedElevation(base.terrain.bounds,controller.signal).then(terrain=>{
      if(!controller.signal.aborted) setDetailed({id,terrain,status:"ready"});
    }).catch(()=>{if(!controller.signal.aborted) setDetailed({id,terrain:null,status:"fallback"});});
    return ()=>controller.abort();
  },[base,id,detailRetry]);
  const context=useMemo(()=>base && detailed?.id===id && detailed.terrain ? {...base,terrain:detailed.terrain} : base,[base,detailed,id]);
  if(error) return <section className={styles.panel} aria-label="Building block context"><div className={styles.status}><h2>Building block context unavailable</h2><p role="status">{error}. Your risk assessment remains available.</p><button className="secondary-button" onClick={()=>setRetry(r=>r+1)}>Retry block context</button></div></section>;
  if(!context) return <section className={styles.panel} aria-label="Building block context"><p className={styles.status} role="status">Loading the selected building, neighboring streets and measured elevation…</p></section>;
  const {minM:min,maxM:max}=terrainRange(context.terrain);
  const ground=buildingGroundRange(context.selected,context.terrain);
  const elevation=ground.minM;
  const fine=detailed?.id===id && detailed.status==="ready";
  const streetNames=[...new Set(context.streets.map(s=>s.name))].sort();
  const groundText=elevation===null ? "Unknown" : `${elevation.toFixed(1)} m NAVD88`;
  return <section className={styles.panel} aria-label="Building block context">
    <div className={styles.heading}><h2>{context.selected.address??"Address unavailable"}</h2><span>{context.taxBlock ? context.wholeBlock ? `Tax block ${Number(context.taxBlock.slice(1))} and adjoining streets` : `Local part of tax block ${Number(context.taxBlock.slice(1))}` : "Approximate one-block vicinity"}</span></div>
    <div className={styles.elevationStatus} role="status" data-testid="block-elevation-status"><span>{fine ? `${context.terrain.raster!.nominalSpacingM.toFixed(1)} m ground grid · USGS 3DEP` : "10 m cached ground grid · USGS 3DEP"}{detailed?.status==="loading" ? " · Loading finer terrain…" : !fine ? " · Finer terrain unavailable; cached elevations retained." : ""}</span>{detailed?.status==="fallback" && <button className="text-button" onClick={()=>setDetailRetry(value=>value+1)}>Retry finer terrain</button>}</div>
    <Scene context={context}/>
    <dl className={styles.measurements}>
      <div><dt>Selected ground elevation</dt><dd>{groundText}</dd></div>
      <div><dt>Building height above ground</dt><dd>{context.selected.heightM===null ? "Unknown" : `${context.selected.heightM.toFixed(1)} m`}</dd></div>
      <div><dt>Block ground elevation</dt><dd>{min!==null && max!==null ? <span className={styles.legend}><span>{min.toFixed(1)} m</span><span className={styles.ramp} aria-hidden="true"/><span>{max.toFixed(1)} m</span></span> : "Unknown"}</dd></div>
    </dl>
    <p className={styles.nearby}>Ground at the building base: {ground.minM===null ? "Unknown" : `${ground.minM.toFixed(1)}–${ground.maxM!.toFixed(1)} m NAVD88 along the sampled footprint`}.{ground.known<ground.total ? " Some perimeter samples are unavailable; this is a partial range." : ""} Building height is retained above the lowest supported ground. First-floor elevation remains unknown.</p>
    <p className={styles.nearby}>Nearby streets: {streetNames.slice(0,4).join(" · ")||"No mapped at-grade streets"}{streetNames.length>4 ? ` · +${streetNames.length-4} in source details` : ""}</p>
    <details className={styles.details}><summary>{context.buildings.length} mapped buildings · {streetNames.length} neighboring streets · Source details</summary>
      <p>The selected building is cyan. Ground and buildings are shown at true scale. Ground elevation is metres relative to NAVD88. The selected ground value is the lowest supported perimeter sample, not the footprint centre or a first-floor measurement. Building heights remain above the lowest supported ground; long walls follow sampled terrain. The DEM represents bare earth and does not measure roof shape or current construction. Missing elevation samples leave gaps. Map elevation is context, not certified freeboard or a risk-model input.</p>
      <p>Streets: {streetNames.join(" · ")||"No street centerlines in this extent"}.</p>
      <ul aria-label="Surrounding building addresses">{context.buildings.map(building=><li key={building.id}>{building.id===context.selected.id ? "Selected: " : ""}{building.address??"Address unavailable"} · {building.bin ? `BIN ${building.bin}` : `Source ID ${building.id}`}</li>)}</ul>
      <p><a href="https://data.cityofnewyork.us/d/64uk-42ks" target="_blank" rel="noreferrer">NYC DCP PLUTO tax-lot addresses</a> join by exact BBL. Buildings on one lot may share its primary address. <a href="https://data.cityofnewyork.us/d/inkn-q76z" target="_blank" rel="noreferrer">NYC OTI street centerlines</a> use source widths when supplied and thin centerlines otherwise; ribbons do not establish curb boundaries. Only constructed at-grade segments are shown; bridges and tunnels are omitted.</p>
      <p>Terrain source: {context.terrain.source}. Native sources and acquisition vintages are recorded in the <a href="/manhattan/dem-provenance.json" target="_blank" rel="noreferrer">USGS source snapshot</a>. Grid spacing is display resolution, not vertical accuracy. Large blocks use a coarser grid to keep the view responsive. Buildings: NYC OTI Building Footprints. {context.taxBlock ? context.wholeBlock ? "Extent includes this tax block and adjoining street frontage." : "This unusually large tax block is shown as a local 180-metre vicinity around the chosen footprint." : "No valid tax block is available; extent is an approximate 180-metre vicinity."}</p>
    </details>
  </section>;
}
