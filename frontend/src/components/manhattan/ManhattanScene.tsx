"use client";

import { Component, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Canvas, useThree, type ThreeEvent } from "@react-three/fiber";
import { Bvh, CameraControls, Html } from "@react-three/drei";
import { BufferGeometry, DoubleSide, Float32BufferAttribute } from "three";
import { buildingAtFace, buildingGeometry, buildingGroundElevation, cameraFrame, combineBounds, outlineGeometry, terrainElevation, terrainGeometry, worldPoint } from "@/lib/manhattan/sceneGeometry";
import { terrainSurface } from "@/lib/manhattan/terrainSurface";
import { pointInGeometry, unprojectMeters } from "@/lib/manhattan/geo";
import type { Bounds, Building, Infrastructure, ManhattanOverview, Neighborhood, NeighborhoodDetail, TerrainGrid } from "@/lib/manhattan/types";

export interface ManhattanSceneProps {
  neighborhoods: Neighborhood[];
  overview: ManhattanOverview | null;
  detail: NeighborhoodDetail | null;
  selectedNeighborhoodId: string | null;
  selectedBuildingId?: string | null;
  showUnderground?: boolean;
  showTerrain?: boolean;
  verticalScale?: number;
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

function MapFallback() {
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

function CameraRig({ bounds, reducedMotion, maxElevation }: { bounds: Bounds; reducedMotion: boolean; maxElevation: number }) {
  const controls = useRef<CameraControls>(null);
  const size = useThree((state) => state.size);
  const invalidate = useThree((state) => state.invalidate);
  const [w, s, e, n] = bounds;
  useEffect(() => {
    const frame = cameraFrame([w, s, e, n], size.width / Math.max(size.height, 1), maxElevation);
    const control = controls.current;
    if (!control) return;
    control.minDistance = 90;
    control.maxDistance = 100_000;
    control.smoothTime = reducedMotion ? 0 : 0.45;
    void control.setLookAt(...frame.position, ...frame.target, !reducedMotion);
    invalidate();
  }, [w, s, e, n, size.width, size.height, reducedMotion, maxElevation, invalidate]);
  return <CameraControls ref={controls} makeDefault minPolarAngle={0.12} maxPolarAngle={Math.PI / 2.15} dollySpeed={0.8} draggingSmoothTime={0.08} />;
}

function NeighborhoodMesh({ neighborhood, terrain, selected, muted, underground, verticalScale }: {
  neighborhood: Neighborhood; terrain?: TerrainGrid; selected: boolean; muted: boolean; underground: boolean; verticalScale: number;
}) {
  const border = useMemo(() => outlineGeometry(neighborhood.geometry, terrain, selected ? 7 : 4, verticalScale), [neighborhood.geometry, terrain, selected, verticalScale]);
  useEffect(() => () => border.dispose(), [border]);
  return <lineSegments geometry={border} renderOrder={3} raycast={() => null}>
    <lineBasicMaterial color={selected ? "#7ff4e5" : underground ? "#9ab5b3" : "#16343f"} transparent opacity={selected ? 1 : muted ? 0.85 : 1} depthTest={false} />
  </lineSegments>;
}

function BuildingMesh({ buildings, activeNeighborhoodId, onSelect, onNeighborhoodSelect, selectedBuildingId, underground, showTerrain, verticalScale, terrainAt, onHover }: {
  buildings: Building[]; activeNeighborhoodId: string | null; selectedBuildingId?: string | null; underground: boolean; showTerrain: boolean; verticalScale: number; terrainAt: (point: [number, number]) => TerrainGrid | undefined;
  onSelect: (building: Building) => void; onNeighborhoodSelect: (id: string) => void; onHover: (building: Building | null) => void;
}) {
  const merged = useMemo(() => buildingGeometry(buildings, { terrainAt, verticalScale }), [buildings, terrainAt, verticalScale]);
  const [hoverId, setHoverId] = useState<string | null>(null);
  const selected = buildings.find((building) => building.id === (hoverId ?? selectedBuildingId));
  const highlight = useMemo(() => selected ? buildingGeometry([selected], { terrainAt, verticalScale }).geometry : null, [selected, terrainAt, verticalScale]);
  useEffect(() => () => merged.geometry.dispose(), [merged]);
  useEffect(() => () => highlight?.dispose(), [highlight]);
  function pick(event: ThreeEvent<PointerEvent | MouseEvent>) {
    if (event.faceIndex == null) return null;
    return buildings[buildingAtFace(event.faceIndex, merged.triangleEnds)] ?? null;
  }
  return <group>
    <mesh geometry={merged.geometry} onClick={(event) => {
      event.stopPropagation();
      if (event.delta > 6) return;
      const building = pick(event);
      if (!building) return;
      if (building.neighborhoodId === activeNeighborhoodId) onSelect(building);
      else onNeighborhoodSelect(building.neighborhoodId);
    }} onPointerMove={(event) => {
      event.stopPropagation();
      const building = pick(event);
      setHoverId(building?.id ?? null);
      onHover(building);
    }} onPointerOut={() => { setHoverId(null); onHover(null); }}>
      <meshStandardMaterial vertexColors flatShading roughness={0.92} side={DoubleSide} transparent={underground || showTerrain} opacity={underground ? 0.2 : showTerrain ? 0.12 : 1} depthWrite={!underground && !showTerrain} />
    </mesh>
    {highlight && <mesh geometry={highlight} renderOrder={2} raycast={() => null}>
      <meshStandardMaterial color="#57d3bf" flatShading roughness={0.8} side={DoubleSide} polygonOffset polygonOffsetFactor={-2} polygonOffsetUnits={-2} />
    </mesh>}
  </group>;
}

function Landscape({ neighborhoods, overview, detail, showUnderground, showTerrain, verticalScale = 1, onNeighborhoodSelect, onHover }: Pick<ManhattanSceneProps, "neighborhoods" | "overview" | "detail" | "showUnderground" | "showTerrain" | "verticalScale" | "onNeighborhoodSelect"> & { onHover: (id: string | null) => void }) {
  const focused = neighborhoods.find((neighborhood) => neighborhood.id === detail?.neighborhoodId);
  const land = useMemo(() => overview?.terrain ? terrainGeometry(overview.terrain, neighborhoods.filter((neighborhood) => neighborhood.id !== detail?.neighborhoodId), { verticalScale, showTerrain }) : null, [overview, detail, neighborhoods, verticalScale, showTerrain]);
  const detailLand = useMemo(() => detail?.terrain ? terrainGeometry(detail.terrain, neighborhoods.filter((neighborhood) => neighborhood.id === detail.neighborhoodId), { verticalScale, showTerrain }) : null, [detail, neighborhoods, verticalScale, showTerrain]);
  const parks = useMemo(() => overview?.terrain ? terrainSurface(overview.terrain, overview.parks.map((park) => park.geometry), { verticalScale, showTerrain, color: "#4d8066", lift: 0.06, exclude: focused ? [focused.geometry] : [] }) : null, [overview, focused, verticalScale, showTerrain]);
  const detailParks = useMemo(() => detail?.terrain && focused ? terrainSurface(detail.terrain, detail.parks.map((park) => park.geometry), { verticalScale, showTerrain, color: "#4d8066", lift: 0.06, include: focused.geometry }) : null, [detail, focused, verticalScale, showTerrain]);
  useEffect(() => () => { parks?.dispose(); detailParks?.dispose(); land?.dispose(); detailLand?.dispose(); }, [parks, detailParks, land, detailLand]);
  const neighborhoodAt = (event: ThreeEvent<PointerEvent | MouseEvent>) => {
    const point = unprojectMeters([event.point.x, -event.point.z]);
    return neighborhoods.find((neighborhood) => pointInGeometry(point, neighborhood.geometry));
  };
  return <group>
    {[land, detailLand, parks, detailParks].map((geometry, index) => geometry && <mesh key={index} geometry={geometry} onClick={(event) => {
      event.stopPropagation();
      const neighborhood = neighborhoodAt(event);
      if (event.delta <= 6 && neighborhood) onNeighborhoodSelect(neighborhood.id);
    }} onPointerMove={(event) => { event.stopPropagation(); onHover(neighborhoodAt(event)?.id ?? null); }} onPointerOut={() => onHover(null)}>
      <meshStandardMaterial vertexColors roughness={1} side={DoubleSide} transparent={showUnderground} opacity={showUnderground ? 0.15 : 1} depthWrite={!showUnderground} polygonOffset polygonOffsetFactor={index >= 2 ? -1 : 0} />
    </mesh>)}
  </group>;
}

/** Unknown depths use a schematic display plane; horizontal coordinates remain sourced. */
function Underground({ infrastructure, terrain, verticalScale }: { infrastructure?: Infrastructure; terrain?: TerrainGrid; verticalScale: number }) {
  const geometries = useMemo(() => {
    const drains: number[] = [];
    const pipes: number[] = [];
    for (const drain of infrastructure?.stormDrains ?? []) drains.push(...worldPoint(drain.position, (terrainElevation(drain.position, terrain) ?? 0) * verticalScale - (drain.depthM ?? 12)));
    for (const line of infrastructure?.sewerLines ?? []) for (let i = 1; i < line.coordinates.length; i++) {
      for (const point of [line.coordinates[i - 1], line.coordinates[i]]) pipes.push(...worldPoint(point, (terrainElevation(point, terrain) ?? 0) * verticalScale - (line.depthM ?? 12)));
    }
    return {
      drains: new BufferGeometry().setAttribute("position", new Float32BufferAttribute(drains, 3)),
      pipes: new BufferGeometry().setAttribute("position", new Float32BufferAttribute(pipes, 3)),
    };
  }, [infrastructure, terrain, verticalScale]);
  useEffect(() => () => { geometries.drains.dispose(); geometries.pipes.dispose(); }, [geometries]);
  return <group renderOrder={10}>
    <lineSegments geometry={geometries.pipes} raycast={() => null}><lineBasicMaterial color="#f2c56e" depthTest={false} transparent opacity={0.95} /></lineSegments>
    <points geometry={geometries.drains} raycast={() => null}><pointsMaterial color="#73e5f3" size={4.5} sizeAttenuation={false} depthTest={false} transparent opacity={0.95} /></points>
  </group>;
}

function WebGLStatus({ onReady, onError }: Pick<ManhattanSceneProps, "onReady" | "onError">) {
  const gl = useThree((state) => state.gl);
  const invalidate = useThree((state) => state.invalidate);
  const callbacks = useRef({ onReady, onError });
  useEffect(() => { callbacks.current = { onReady, onError }; }, [onReady, onError]);
  useEffect(() => {
    const canvas = gl.domElement;
    const lost = (event: Event) => { event.preventDefault(); callbacks.current.onError?.(WEBGL_MESSAGE); };
    const restored = () => { callbacks.current.onReady?.(); invalidate(); };
    canvas.addEventListener("webglcontextlost", lost);
    canvas.addEventListener("webglcontextrestored", restored);
    // This effect runs only once the Canvas renderer and scene have mounted.
    callbacks.current.onReady?.();
    return () => { canvas.removeEventListener("webglcontextlost", lost); canvas.removeEventListener("webglcontextrestored", restored); };
  }, [gl, invalidate]);
  return null;
}

function City(props: ManhattanSceneProps) {
  const { neighborhoods, overview, detail, selectedNeighborhoodId, selectedBuildingId, onNeighborhoodSelect, onBuildingSelect } = props;
  const [hoverNeighborhoodId, setHoverNeighborhoodId] = useState<string | null>(null);
  const [hoverBuilding, setHoverBuilding] = useState<Building | null>(null);
  const gl = useThree((state) => state.gl);
  useEffect(() => {
    setHoverNeighborhoodId(null);
    setHoverBuilding(null);
  }, [selectedNeighborhoodId]);
  useEffect(() => {
    gl.domElement.style.cursor = hoverNeighborhoodId || hoverBuilding ? "pointer" : "grab";
    return () => { gl.domElement.style.cursor = ""; };
  }, [gl, hoverNeighborhoodId, hoverBuilding]);
  const reducedMotion = useReducedMotion();
  const selected = neighborhoods.find((neighborhood) => neighborhood.id === selectedNeighborhoodId);
  const bounds = selected?.bounds ?? combineBounds(neighborhoods);
  const activeDetail = detail?.neighborhoodId === selectedNeighborhoodId ? detail : null;
  const buildings = useMemo(() => activeDetail
    ? [...(overview?.buildings ?? []).filter((building) => building.neighborhoodId !== activeDetail.neighborhoodId), ...activeDetail.buildings]
    : overview?.buildings ?? [], [overview, activeDetail]);
  const verticalScale = Number.isFinite(props.verticalScale) && props.verticalScale! > 0 ? props.verticalScale! : 1;
  const terrain = (activeDetail ?? overview)?.terrain;
  const terrainAt = useMemo(() => (point: [number, number]) => {
    if (activeDetail && selected && point[0] >= selected.bounds[0] && point[0] <= selected.bounds[2] && point[1] >= selected.bounds[1] && point[1] <= selected.bounds[3] && pointInGeometry(point, selected.geometry)) return activeDetail.terrain;
    return overview?.terrain;
  }, [activeDetail, selected, overview]);
  const maxElevation = useMemo(() => Math.max((terrain?.elevationsM.reduce<number>((max, value) => Math.max(max, value ?? 0), 0) ?? 0) * verticalScale, buildings.reduce((max, building) => selectedNeighborhoodId && building.neighborhoodId !== selectedNeighborhoodId ? max : Math.max(max, (buildingGroundElevation(building, terrainAt(building.center)) ?? 0) * verticalScale + (building.heightM ?? 0)), 0)), [buildings, selectedNeighborhoodId, terrain, terrainAt, verticalScale]);
  const hovered = neighborhoods.find((neighborhood) => neighborhood.id === (hoverBuilding?.neighborhoodId ?? hoverNeighborhoodId));
  const propertyHover = hoverBuilding && hoverBuilding.neighborhoodId === activeDetail?.neighborhoodId ? hoverBuilding : null;
  const label = propertyHover ? propertyHover.address ?? "Address unavailable" : hovered?.name;
  const labelPoint = propertyHover ? worldPoint(propertyHover.center, (buildingGroundElevation(propertyHover, terrainAt(propertyHover.center)) ?? 0) * verticalScale + (propertyHover.heightM ?? 0) + 20) : hovered ? worldPoint(hovered.center, (terrainElevation(hovered.center, terrainAt(hovered.center)) ?? 0) * verticalScale + 20) : null;
  return <>
    <color attach="background" args={["#0b1b23"]} />
    <ambientLight intensity={props.showTerrain ? 0.45 : 1.15} />
    <directionalLight position={[-6000, props.showTerrain ? 4500 : 10000, 4000]} intensity={props.showTerrain ? 2.6 : 2.3} color="#fff4d9" />
    <hemisphereLight args={["#d4e4ed", "#47584b", props.showTerrain ? 0.4 : 1.2]} />
    <CameraRig bounds={bounds} reducedMotion={reducedMotion} maxElevation={maxElevation} />
    <Bvh key={`${activeDetail?.neighborhoodId ?? "overview"}-${overview?.buildings.length ?? 0}-${verticalScale}-${props.showTerrain ? 1 : 0}`} firstHitOnly indirect>
      <Landscape neighborhoods={neighborhoods} overview={overview} detail={activeDetail} showUnderground={props.showUnderground} showTerrain={props.showTerrain} verticalScale={verticalScale} onNeighborhoodSelect={onNeighborhoodSelect} onHover={setHoverNeighborhoodId} />
      {neighborhoods.map((neighborhood) => <NeighborhoodMesh key={neighborhood.id} neighborhood={neighborhood} terrain={neighborhood.id === activeDetail?.neighborhoodId ? activeDetail.terrain : overview?.terrain} selected={neighborhood.id === selectedNeighborhoodId || neighborhood.id === hovered?.id} muted={!!selectedNeighborhoodId} underground={!!props.showUnderground} verticalScale={verticalScale} />)}
      <BuildingMesh buildings={buildings} activeNeighborhoodId={activeDetail?.neighborhoodId ?? null} onSelect={onBuildingSelect} onNeighborhoodSelect={onNeighborhoodSelect} selectedBuildingId={selectedBuildingId} underground={!!props.showUnderground} showTerrain={!!props.showTerrain} verticalScale={verticalScale} terrainAt={terrainAt} onHover={setHoverBuilding} />
      {props.showUnderground && <Underground infrastructure={(activeDetail ?? overview)?.infrastructure} terrain={terrain} verticalScale={verticalScale} />}
    </Bvh>
    {label && labelPoint && <Html position={labelPoint} center style={{ pointerEvents: "none", whiteSpace: "nowrap" }} zIndexRange={[20, 0]}>
      <span style={{ display: "block", background: "#101f25", border: "1px solid #59756e", color: "#eaf1f3", padding: "6px 9px", borderRadius: 4, fontSize: 12, boxShadow: "0 4px 12px #0005" }}>{label}</span>
    </Html>}
    <WebGLStatus onReady={props.onReady} onError={props.onError} />
  </>;
}

/** Root supplies the accessible neighborhood/property list and loading state beside this canvas. */
export default function ManhattanScene(props: ManhattanSceneProps) {
  return <SceneBoundary onError={props.onError}>
    <Canvas aria-label="Interactive 3D Manhattan map. Drag to pan or orbit; scroll or pinch to zoom. Use the neighborhood and property lists for keyboard selection." role="img" frameloop="demand" dpr={[1, 1.5]} camera={{ position: [10000, 18000, 18000], fov: 38, near: 2, far: 150000 }} gl={{ antialias: true, alpha: false, powerPreference: "high-performance" }} fallback={<MapFallback />} style={{ touchAction: "none", background: "#0b1b23" }}>
      <City {...props} />
    </Canvas>
  </SceneBoundary>;
}
