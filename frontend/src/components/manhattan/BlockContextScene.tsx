"use client";

import { Component, useEffect, useMemo, useRef, useState, type ReactNode, type RefObject } from "react";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { CameraControls, Html } from "@react-three/drei";
import { DoubleSide, EdgesGeometry, Vector3 } from "three";
import { buildingGeometry, cameraFrame, terrainElevation, terrainGeometry, worldPoint } from "@/lib/manhattan/sceneGeometry";
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
  useEffect(()=>{
    const maxRoof=Math.max(...context.buildings.map(b=>(terrainElevation(b.center,context.terrain)??b.groundElevationM??0)+(b.heightM??0)));
    const frame=cameraFrame(context.bounds,size.width/Math.max(1,size.height),maxRoof);
    void controls.current?.setLookAt(...frame.position,...frame.target,false);
    invalidate();
  },[context,size.width,size.height,reset,invalidate]);
  return <CameraControls ref={controls} makeDefault minDistance={25} maxDistance={6000} minPolarAngle={.05} maxPolarAngle={Math.PI/2.08}/>;
}
function Block({context}:{context:BlockContext}) {
  const geometries=useMemo(()=>{
    const [w,s,e,n]=context.terrain.bounds;
    const rectangle:Neighborhood={id:"context",name:"Block",type:"0",center:[(w+e)/2,(s+n)/2],bounds:[w,s,e,n],geometry:{type:"Polygon",coordinates:[[[w,s],[e,s],[e,n],[w,n],[w,s]]]}};
    const samples=context.terrain.elevationsM.filter((h):h is number=>h!==null);
    const land=colorTerrain(terrainGeometry(context.terrain,[rectangle]),Math.min(...samples),Math.max(...samples));
    const options={terrain:context.terrain,verticalScale:1};
    const buildings=buildingGeometry(context.buildings.filter(b=>b.id!==context.selected.id),options).geometry;
    const selected=buildingGeometry(context.buildings.filter(b=>b.id===context.selected.id),options).geometry;
    return {land,buildings,selected,selectedEdges:new EdgesGeometry(selected),streets:streetGeometry(context.streets,context.terrain,context.bounds)};
  },[context]);
  useEffect(()=>()=>{Object.values(geometries).forEach(g=>g.dispose());},[geometries]);
  const streetLabels=useMemo(()=>{
    const names=new Set<string>();
    return context.streets.flatMap(street=>{
      if(names.has(street.name)) return [];
      const position=streetLabelPosition(street,context.terrain,context.bounds);
      if(!position) return [];
      names.add(street.name);
      return [{id:street.id,name:street.name,...position}];
    }).sort((a,b)=>Math.hypot(...worldPoint(a.point).map((v,i)=>v-worldPoint(context.selected.center)[i]))-Math.hypot(...worldPoint(b.point).map((v,i)=>v-worldPoint(context.selected.center)[i]))).filter((label,index,labels)=>labels.slice(0,index).every(other=>Math.hypot(...worldPoint(label.point).map((v,i)=>v-worldPoint(other.point)[i]))>95)).slice(0,3);
  },[context]);
  return <group>
    <mesh geometry={geometries.land}><meshStandardMaterial vertexColors side={DoubleSide} roughness={1}/></mesh>
    <mesh geometry={geometries.streets}><meshStandardMaterial color="#34474e" roughness={1} side={DoubleSide}/></mesh>
    <mesh geometry={geometries.buildings}><meshStandardMaterial vertexColors roughness={1} side={DoubleSide}/></mesh>
    <mesh geometry={geometries.selected}><meshStandardMaterial color="#57d3df" roughness={.8} side={DoubleSide}/></mesh>
    <lineSegments geometry={geometries.selectedEdges} renderOrder={5} raycast={()=>null}><lineBasicMaterial color="#57d3df" depthTest={false}/></lineSegments>

    {streetLabels.map(label=><Html key={label.id} position={worldPoint(label.point,label.elevation!+3)} center style={{pointerEvents:"none"}}><span className={styles.streetLabel}>{label.name}</span></Html>)}
  </group>;
}
/** Keep the selected address in React's DOM tree; project its anchor from the real 3D roof position. */
function SelectedAddress({context,marker}:{context:BlockContext;marker:RefObject<HTMLSpanElement|null>}) {
  const point=useMemo(()=>new Vector3(...worldPoint(context.selected.center,(terrainElevation(context.selected.center,context.terrain)??context.selected.groundElevationM??0)+(context.selected.heightM??0)+2)),[context]);
  useFrame(({camera,size})=>{
    const element=marker.current;
    if(!element) return;
    const screen=point.clone().project(camera);
    element.style.left=`${(screen.x+1)*size.width/2}px`;
    element.style.top=`${(1-screen.y)*size.height/2}px`;
    element.style.visibility=screen.z>=-1 && screen.z<=1 ? "visible" : "hidden";
  });
  return null;
}
export default function BlockContextScene({context}:{context:BlockContext}) {
  const [reset,setReset]=useState(0);
  const marker=useRef<HTMLSpanElement>(null);
  return <div className={styles.scene} role="group" aria-label="3D selected property and surrounding block with measured ground elevation">
    <SceneBoundary><Canvas frameloop="demand" dpr={[1,1.5]} camera={{fov:38,near:1,far:30000}} fallback={<p className={styles.fallback}>3D rendering is unavailable. Use the address, street and elevation information below.</p>} gl={{antialias:true}}>
      <color attach="background" args={["#13232b"]}/><ambientLight intensity={1.1}/><directionalLight position={[2000,6000,1500]} intensity={2}/>
      <Block context={context}/><Camera context={context} reset={reset}/><SelectedAddress context={context} marker={marker}/>
    </Canvas></SceneBoundary>
    <span ref={marker} data-testid="selected-building-marker" data-property-id={context.selected.id} className={styles.selectedMarker}>{context.selected.address??"Selected building · Address unavailable"}</span>
    <button type="button" className={styles.reset} onClick={()=>setReset(r=>r+1)}>Reset block view</button>
    <span className={styles.controls}><span className={styles.pointerControls}>Drag to rotate · Right-drag to pan · Scroll to zoom</span><span className={styles.touchControls}>Drag to rotate · Two fingers to pan and zoom</span></span>
  </div>;
}
