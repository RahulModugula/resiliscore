"use client";

import { Component, useEffect, useMemo, useRef, useState, type ReactNode, type RefObject } from "react";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { CameraControls } from "@react-three/drei";
import { DoubleSide, EdgesGeometry, Vector3 } from "three";
import { buildingGeometry, cameraFrame, terrainGeometry, worldPoint } from "@/lib/manhattan/sceneGeometry";
import { buildingGroundRange, sampleBuildingPerimeter, terrainRange } from "@/lib/manhattan/blockElevation";
import { colorTerrain, streetGeometry, streetLabelPosition } from "@/lib/manhattan/blockGeometry";
import type { BlockContext } from "@/lib/manhattan/blockContext";
import type { Neighborhood } from "@/lib/manhattan/types";
import styles from "./BlockContextView.module.css";

class SceneBoundary extends Component<{children:ReactNode},{failed:boolean}> {
  state={failed:false};
  static getDerivedStateFromError(){return {failed:true};}
  render(){return this.state.failed ? <p className={styles.fallback} role="status">3D rendering is unavailable. The block addresses, streets and measured elevations remain listed below.</p> : this.props.children;}
}
function Camera({context,reset}:{context:BlockContext;reset:number}) {
  const controls=useRef<CameraControls>(null);
  const size=useThree(s=>s.size);
  const invalidate=useThree(s=>s.invalidate);
  const latest=useRef(context);
  useEffect(()=>{ latest.current=context; },[context]);
  useEffect(()=>{
    const current=latest.current;
    const maxRoof=Math.max(...current.buildings.map(b=>(buildingGroundRange(b,current.terrain).minM??b.groundElevationM??0)+(b.heightM??0)));
    const frame=cameraFrame(current.bounds,size.width/Math.max(1,size.height),maxRoof);
    void controls.current?.setLookAt(...frame.position,...frame.target,false);
    invalidate();
  },[context.selected.id,size.width,size.height,reset,invalidate]);
  return <CameraControls ref={controls} makeDefault dollySpeed={2} minDistance={25} maxDistance={6000} minPolarAngle={.05} maxPolarAngle={Math.PI/2.08}/>;
}
function Block({context}:{context:BlockContext}) {
  const geometries=useMemo(()=>{
    const [w,s,e,n]=context.terrain.bounds;
    const rectangle:Neighborhood={id:"context",name:"Block",type:"0",center:[(w+e)/2,(s+n)/2],bounds:[w,s,e,n],geometry:{type:"Polygon",coordinates:[[[w,s],[e,s],[e,n],[w,n],[w,s]]]}};
    const {minM,maxM}=terrainRange(context.terrain);
    const land=colorTerrain(terrainGeometry(context.terrain,[rectangle]),minM??0,maxM??0);
    const options={terrain:context.terrain,verticalScale:1,groundAt:(b:BlockContext["selected"])=>buildingGroundRange(b,context.terrain).minM??b.groundElevationM};
    const prepared=context.buildings.map(building=>sampleBuildingPerimeter(building,context.terrain.raster?.nominalSpacingM??2));
    const buildings=buildingGeometry(prepared.filter(b=>b.id!==context.selected.id),options).geometry;
    const selected=buildingGeometry(prepared.filter(b=>b.id===context.selected.id),options).geometry;
    return {land,buildings,selected,selectedEdges:new EdgesGeometry(selected),streets:streetGeometry(context.streets,context.terrain,context.bounds)};
  },[context]);
  useEffect(()=>()=>{Object.values(geometries).forEach(g=>g.dispose());},[geometries]);
  return <group>
    <mesh geometry={geometries.land}><meshStandardMaterial vertexColors side={DoubleSide} roughness={1}/></mesh>
    <mesh geometry={geometries.streets}><meshStandardMaterial color="#34474e" roughness={1} side={DoubleSide}/></mesh>
    <mesh geometry={geometries.buildings}><meshStandardMaterial vertexColors roughness={1} side={DoubleSide}/></mesh>
    <mesh geometry={geometries.selected}><meshStandardMaterial color="#57d3df" roughness={.8} side={DoubleSide}/></mesh>
    <lineSegments geometry={geometries.selectedEdges} renderOrder={5} raycast={()=>null}><lineBasicMaterial color="#57d3df" depthTest={false}/></lineSegments>


  </group>;
}
function contextStreetLabels(context:BlockContext) {
    const names=new Set<string>();
    return context.streets.flatMap(street=>{
      if(names.has(street.name)) return [];
      const position=streetLabelPosition(street,context.terrain,context.bounds);
      if(!position) return [];
      names.add(street.name);
      return [{id:street.id,name:street.name,...position}];
    }).sort((a,b)=>Math.hypot(...worldPoint(a.point).map((v,i)=>v-worldPoint(context.selected.center)[i]))-Math.hypot(...worldPoint(b.point).map((v,i)=>v-worldPoint(context.selected.center)[i]))).filter((label,index,labels)=>labels.slice(0,index).every(other=>Math.hypot(...worldPoint(label.point).map((v,i)=>v-worldPoint(other.point)[i]))>95)).slice(0,3);
}

/** DOM labels share the workspace React root, including when terrain replaces geometry. */
function ProjectedLabels({context,marker,streetMarkers,labels}:{context:BlockContext;marker:RefObject<HTMLSpanElement|null>;streetMarkers:RefObject<Map<string,HTMLSpanElement>>;labels:ReturnType<typeof contextStreetLabels>}) {
  const anchors=useMemo(()=>[
    {id:null,point:new Vector3(...worldPoint(context.selected.center,(buildingGroundRange(context.selected,context.terrain).minM??context.selected.groundElevationM??0)+(context.selected.heightM??0)+2))},
    ...labels.map(label=>({id:label.id,point:new Vector3(...worldPoint(label.point,label.elevation+3))})),
  ],[context,labels]);
  const projected=useRef(new Vector3());
  useFrame(({camera,size})=>{
    for(const anchor of anchors) {
      const element=anchor.id===null ? marker.current : streetMarkers.current.get(anchor.id);
      if(!element) continue;
      const screen=projected.current.copy(anchor.point).project(camera);
      element.style.left=`${(screen.x+1)*size.width/2}px`;
      element.style.top=`${(1-screen.y)*size.height/2}px`;
      element.style.visibility=screen.z>=-1 && screen.z<=1 ? "visible" : "hidden";
    }
  });
  return null;
}
export default function BlockContextScene({context}:{context:BlockContext}) {
  const [reset,setReset]=useState(0);
  const marker=useRef<HTMLSpanElement>(null);
  const streetMarkers=useRef(new Map<string,HTMLSpanElement>());
  const labels=useMemo(()=>contextStreetLabels(context),[context]);
  return <div className={styles.scene} role="group" aria-label="3D selected property and surrounding block with measured ground elevation">
    <SceneBoundary><Canvas frameloop="demand" dpr={[1,1.5]} camera={{fov:38,near:1,far:30000}} fallback={<p className={styles.fallback}>3D rendering is unavailable. Use the address, street and elevation information below.</p>} gl={{antialias:true}}>
      <color attach="background" args={["#13232b"]}/><ambientLight intensity={1.1}/><directionalLight position={[2000,6000,1500]} intensity={2}/>
      <Block context={context}/><Camera context={context} reset={reset}/><ProjectedLabels context={context} marker={marker} labels={labels} streetMarkers={streetMarkers}/>
    </Canvas></SceneBoundary>
    {labels.map(label=><span key={label.id} ref={element=>{if(element) streetMarkers.current.set(label.id,element);else streetMarkers.current.delete(label.id);}} className={`${styles.streetLabel} ${styles.streetMarker}`}>{label.name}</span>)}
    <span ref={marker} data-testid="selected-building-marker" data-property-id={context.selected.id} className={styles.selectedMarker}>{context.selected.address??"Selected building · Address unavailable"}</span>
    <button type="button" className={styles.reset} onClick={()=>setReset(r=>r+1)}>Reset block view</button>
    <span className={styles.controls}><span className={styles.pointerControls}>Drag to rotate · Right-drag to pan · Scroll to zoom</span><span className={styles.touchControls}>Drag to rotate · Two fingers to pan and zoom</span></span>
  </div>;
}
