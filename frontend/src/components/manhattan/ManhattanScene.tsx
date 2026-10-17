"use client";

import { Component, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Canvas, useThree, type ThreeEvent } from "@react-three/fiber";
import { Bvh, CameraControls, Html } from "@react-three/drei";
import { DoubleSide } from "three";
import { buildingAtFace, buildingGeometry, cameraFrame, combineBounds, outlineGeometry, parkGeometry, polygonGeometry, terrainElevation, terrainGeometry, worldPoint } from "@/lib/manhattan/sceneGeometry";
import type { Bounds, Building, ManhattanOverview, Neighborhood, NeighborhoodDetail, TerrainGrid } from "@/lib/manhattan/types";

export interface ManhattanSceneProps {
  neighborhoods: Neighborhood[];
  overview: ManhattanOverview | null;
  detail: NeighborhoodDetail | null;
  selectedNeighborhoodId: string | null;
  selectedBuildingId?: string | null;
  onNeighborhoodSelect: (id: string) => void;
  onBuildingSelect: (building: Building) => void;
  onReady?: () => void;
  onError?: (message: string) => void;
}

const WEBGL_MESSAGE = "The 3D map is unavailable. Choose a neighborhood and property from the list to continue.";

class SceneBoundary extends Component<{ children: ReactNode; onError?: (message: string) => void }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch() { this.props.onError?.(WEBGL_MESSAGE); }
  render() { return this.state.failed ? <MapFallback /> : this.props.children; }
}

function MapFallback({ onError }: { onError?: (message: string) => void }) {
  useEffect(() => { onError?.(WEBGL_MESSAGE); }, [onError]);
  return <div role="status" style={{ padding: 24, color: "#eaf1f3", background: "#0b1519", height: "100%" }}>{WEBGL_MESSAGE}</div>;
}

function useReducedMotion() {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReduced(query.matches);
    update();
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);
  return reduced;
}

function CameraRig({ bounds, reducedMotion }: { bounds: Bounds; reducedMotion: boolean }) {
  const controls = useRef<CameraControls>(null);
  const size = useThree((state) => state.size);
  const invalidate = useThree((state) => state.invalidate);
  const [w, s, e, n] = bounds;
  useEffect(() => {
    const frame = cameraFrame([w, s, e, n], size.width / Math.max(size.height, 1));
    const control = controls.current;
    if (!control) return;
    control.minDistance = 90;
    control.maxDistance = 100_000;
    control.smoothTime = reducedMotion ? 0 : 0.45;
    void control.setLookAt(...frame.position, ...frame.target, !reducedMotion);
    invalidate();
  }, [w, s, e, n, size.width, size.height, reducedMotion, invalidate]);
  return <CameraControls ref={controls} makeDefault minPolarAngle={0.12} maxPolarAngle={Math.PI / 2.15} dollySpeed={0.8} draggingSmoothTime={0.08} />;
}

function NeighborhoodMesh({ neighborhood, terrain, selected, muted, onSelect, onHover }: {
  neighborhood: Neighborhood; terrain?: TerrainGrid; selected: boolean; muted: boolean;
  onSelect: (id: string) => void; onHover: (id: string | null) => void;
}) {
  const fill = useMemo(() => polygonGeometry(neighborhood.geometry, () => -1), [neighborhood.geometry]);
  const border = useMemo(() => outlineGeometry(neighborhood.geometry, terrain, selected ? 7 : 4), [neighborhood.geometry, terrain, selected]);
  useEffect(() => () => { fill.dispose(); border.dispose(); }, [fill, border]);
  return <group>
    <mesh geometry={fill} onClick={(event) => { event.stopPropagation(); if (event.delta <= 6) onSelect(neighborhood.id); }} onPointerOver={(event) => { event.stopPropagation(); onHover(neighborhood.id); }} onPointerOut={() => onHover(null)}>
      <meshStandardMaterial color={selected ? "#74978c" : "#76867a"} roughness={1} side={DoubleSide} />
    </mesh>
    <lineSegments geometry={border} renderOrder={3} raycast={() => null}>
      <lineBasicMaterial color={selected ? "#7ff4e5" : muted ? "#667b7a" : "#a7bdb0"} transparent opacity={selected ? 1 : 0.75} depthTest={false} />
    </lineSegments>
  </group>;
}

function BuildingMesh({ buildings, interactive, onSelect, onNeighborhoodSelect, selectedBuildingId, onHover }: {
  buildings: Building[]; interactive: boolean; selectedBuildingId?: string | null;
  onSelect: (building: Building) => void; onNeighborhoodSelect: (id: string) => void; onHover: (building: Building | null) => void;
}) {
  const merged = useMemo(() => buildingGeometry(buildings), [buildings]);
  const [hoverId, setHoverId] = useState<string | null>(null);
  const selected = buildings.find((building) => building.id === (hoverId ?? selectedBuildingId));
  const highlight = useMemo(() => selected ? buildingGeometry([selected]).geometry : null, [selected]);
  useEffect(() => () => merged.geometry.dispose(), [merged]);
  useEffect(() => () => highlight?.dispose(), [highlight]);
  function pick(event: ThreeEvent<PointerEvent | MouseEvent>) {
    if (event.faceIndex == null) return null;
    return buildings[buildingAtFace(event.faceIndex, merged.triangleEnds)] ?? null;
  }
  return <Bvh key={`${buildings.length}-${buildings[0]?.id}`} firstHitOnly indirect>
    <mesh geometry={merged.geometry} onClick={(event) => {
      event.stopPropagation();
      if (event.delta > 6) return;
      const building = pick(event);
      if (!building) return;
      if (interactive) onSelect(building);
      else onNeighborhoodSelect(building.neighborhoodId);
    }} onPointerMove={(event) => {
      event.stopPropagation();
      const building = pick(event);
      setHoverId(building?.id ?? null);
      onHover(building);
    }} onPointerOut={() => { setHoverId(null); onHover(null); }}>
      <meshStandardMaterial vertexColors roughness={0.92} side={DoubleSide} />
    </mesh>
    {highlight && <mesh geometry={highlight} renderOrder={2} raycast={() => null}>
      <meshStandardMaterial color="#57d3bf" roughness={0.8} side={DoubleSide} polygonOffset polygonOffsetFactor={-2} polygonOffsetUnits={-2} />
    </mesh>}
  </Bvh>;
}

function Landscape({ neighborhoods, overview, detail }: Pick<ManhattanSceneProps, "neighborhoods" | "overview" | "detail">) {
  const data = detail ?? overview;
  const parks = useMemo(() => parkGeometry(data?.parks ?? [], data?.terrain), [data]);
  const land = useMemo(() => data?.terrain ? terrainGeometry(data.terrain, neighborhoods) : null, [data, neighborhoods]);
  useEffect(() => () => { parks.dispose(); land?.dispose(); }, [parks, land]);
  return <group>
    {land && <mesh geometry={land} raycast={() => null}><meshStandardMaterial color="#829181" roughness={1} side={DoubleSide} /></mesh>}
    <mesh geometry={parks} raycast={() => null}><meshStandardMaterial color="#4d8066" side={DoubleSide} roughness={1} polygonOffset polygonOffsetFactor={-1} /></mesh>
  </group>;
}

function WebGLStatus({ onReady, onError }: Pick<ManhattanSceneProps, "onReady" | "onError">) {
  const gl = useThree((state) => state.gl);
  const invalidate = useThree((state) => state.invalidate);
  useEffect(() => {
    const canvas = gl.domElement;
    const lost = (event: Event) => { event.preventDefault(); onError?.(WEBGL_MESSAGE); };
    const restored = () => { onReady?.(); invalidate(); };
    canvas.addEventListener("webglcontextlost", lost);
    canvas.addEventListener("webglcontextrestored", restored);
    // This effect runs only once the Canvas renderer and scene have mounted.
    onReady?.();
    return () => { canvas.removeEventListener("webglcontextlost", lost); canvas.removeEventListener("webglcontextrestored", restored); };
  }, [gl, onReady, onError, invalidate]);
  return null;
}

function City(props: ManhattanSceneProps) {
  const { neighborhoods, overview, detail, selectedNeighborhoodId, selectedBuildingId, onNeighborhoodSelect, onBuildingSelect } = props;
  const [hoverNeighborhoodId, setHoverNeighborhoodId] = useState<string | null>(null);
  const [hoverBuilding, setHoverBuilding] = useState<Building | null>(null);
  const reducedMotion = useReducedMotion();
  const selected = neighborhoods.find((neighborhood) => neighborhood.id === selectedNeighborhoodId);
  const bounds = selected?.bounds ?? combineBounds(neighborhoods);
  const activeDetail = detail?.neighborhoodId === selectedNeighborhoodId ? detail : null;
  const terrain = (activeDetail ?? overview)?.terrain;
  const hovered = neighborhoods.find((neighborhood) => neighborhood.id === (hoverBuilding?.neighborhoodId ?? hoverNeighborhoodId));
  const label = hoverBuilding && activeDetail ? hoverBuilding.address ?? hoverBuilding.name ?? `Building ${hoverBuilding.bin ?? hoverBuilding.id}` : hovered?.name;
  const labelPoint = hoverBuilding && activeDetail ? worldPoint(hoverBuilding.center, (hoverBuilding.groundElevationM ?? 0) + (hoverBuilding.heightM ?? 0) + 20) : hovered ? worldPoint(hovered.center, (terrainElevation(hovered.center, terrain) ?? 0) + 20) : null;
  return <>
    <color attach="background" args={["#0b1b23"]} />
    <ambientLight intensity={1.15} />
    <directionalLight position={[-6000, 10000, 4000]} intensity={2.3} color="#fff4d9" />
    <hemisphereLight args={["#d4e4ed", "#47584b", 1.2]} />
    <CameraRig bounds={bounds} reducedMotion={reducedMotion} />
    <Landscape neighborhoods={neighborhoods} overview={overview} detail={activeDetail} />
    {neighborhoods.map((neighborhood) => <NeighborhoodMesh key={neighborhood.id} neighborhood={neighborhood} terrain={terrain} selected={neighborhood.id === selectedNeighborhoodId || neighborhood.id === hovered?.id} muted={!!selectedNeighborhoodId} onSelect={onNeighborhoodSelect} onHover={setHoverNeighborhoodId} />)}
    <BuildingMesh buildings={activeDetail?.buildings ?? overview?.buildings ?? []} interactive={!!activeDetail} onSelect={onBuildingSelect} onNeighborhoodSelect={onNeighborhoodSelect} selectedBuildingId={selectedBuildingId} onHover={setHoverBuilding} />
    {label && labelPoint && <Html position={labelPoint} center style={{ pointerEvents: "none", whiteSpace: "nowrap" }} zIndexRange={[20, 0]}>
      <span style={{ display: "block", background: "#101f25", border: "1px solid #59756e", color: "#eaf1f3", padding: "6px 9px", borderRadius: 4, fontSize: 12, boxShadow: "0 4px 12px #0005" }}>{label}</span>
    </Html>}
    <WebGLStatus onReady={props.onReady} onError={props.onError} />
  </>;
}

/** Root supplies the accessible neighborhood/property list and loading state beside this canvas. */
export default function ManhattanScene(props: ManhattanSceneProps) {
  return <SceneBoundary onError={props.onError}>
    <Canvas aria-label="Interactive 3D Manhattan map. Drag to pan or orbit; scroll or pinch to zoom. Use the neighborhood and property lists for keyboard selection." role="img" frameloop="demand" dpr={[1, 1.5]} camera={{ position: [10000, 18000, 18000], fov: 38, near: 2, far: 150000 }} gl={{ antialias: true, alpha: false, powerPreference: "high-performance" }} fallback={<MapFallback onError={props.onError} />} style={{ touchAction: "none", background: "#0b1b23" }}>
      <City {...props} />
    </Canvas>
  </SceneBoundary>;
}
