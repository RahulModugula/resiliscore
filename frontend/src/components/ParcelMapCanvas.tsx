"use client";

import { useMemo, useState } from "react";
import { Crosshair, Layers, Minus, Navigation, Plus } from "lucide-react";
import type { Feature, ParcelScoreResponse } from "@/types/resiliscore";
import imagerySources from "../../public/imagery/sources.json";

const layerNames = ["Parcel", "Building", "Zone 0", "Zone 1", "Zone 2", "CV detections"];
const kinds = ["parcel_polygon", "building_footprint", "zone_0_ring_0_5ft", "zone_1_ring_5_30ft", "zone_2_ring_30_100ft", "cv_detection"];

export function ParcelMapCanvas({ parcel }: { parcel: ParcelScoreResponse }) {
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [drag, setDrag] = useState<{ x: number; y: number; px: number; py: number } | null>(null);
  const [visible, setVisible] = useState(layerNames);
  const [selected, setSelected] = useState<string | null>(null);
  const features = parcel.parcel_identity.geometries.features;
  const [lng, lat] = parcel.parcel_identity.centroid;
  const cos = Math.cos(lat * Math.PI / 180);
  const project = (point: number[]) => [400 + (point[0] - lng) * cos * 540000, 240 - (point[1] - lat) * 540000];
  const path = (f: Feature) => f.geometry.coordinates.map(ring => ring.map((p, i) => `${i ? "L" : "M"}${project(p).join(",")}`).join(" ") + "Z").join(" ");
  const trees = useMemo(() => Array.from({ length: 48 }, (_, i) => ({ x: (i * 157 + 23) % 800, y: (i * 89 + 57) % 480, r: 10 + i % 17 })), []);
  const privateLayer = parcel.private_verification_layer;
  const hasImagery = Object.hasOwn(imagerySources, `${parcel.parcel_identity.apn_uid}.jpg`);
  const color = (f: Feature) => {
    switch (f.properties.kind) {
      case "parcel_polygon": return "#e2ece4";
      case "building_footprint": return "#12B5CB";
      case "zone_0_ring_0_5ft": return privateLayer.cv_zone0_clear ? "#42d18b" : "#f36659";
      case "zone_1_ring_5_30ft": return privateLayer.cv_zone1_no_shed ? "#42d18b" : "#efba56";
      case "zone_2_ring_30_100ft": return "#a4c7a9";
      default: return /canopy|shed|unpermitted/i.test(f.properties.label ?? "") ? "#ff796d" : "#12B5CB";
    }
  };
  const sorted = [...features].sort((a,b) => kinds.indexOf(b.properties.kind) - kinds.indexOf(a.properties.kind));
  return <section className="map-panel" aria-label="Parcel spatial twin">
    <div className="panel-heading"><h2>Parcel spatial twin</h2><span className="subtle-label"><Layers size={14} />GeoJSON overlays</span></div>
    <div className="map-viewport">
      <svg className="parcel-map" viewBox="0 0 800 480" role="img" aria-label="Interactive parcel map. Drag to pan; use controls to zoom." onPointerDown={e => { e.currentTarget.setPointerCapture(e.pointerId); setDrag({ x: e.clientX, y: e.clientY, px: pan.x, py: pan.y }); }} onPointerMove={e => { if (drag) { const scale = 800 / e.currentTarget.getBoundingClientRect().width; setPan({ x: drag.px + (e.clientX - drag.x) * scale, y: drag.py + (e.clientY - drag.y) * scale }); } }} onPointerUp={() => setDrag(null)} onPointerCancel={() => setDrag(null)}>
        <defs><pattern id="survey-grid" width="40" height="40" patternUnits="userSpaceOnUse"><path d="M40 0H0V40" fill="none" stroke="#b8c7ab" strokeWidth=".5" opacity=".12" /></pattern></defs>
        <rect width="800" height="480" fill="#1c2b26" />
        <g transform={`translate(${pan.x} ${pan.y}) translate(400 240) scale(${zoom}) translate(-400 -240)`}>
          <rect x="-800" y="-480" width="2400" height="1440" fill="url(#survey-grid)" />
          {hasImagery ? <image href={`/imagery/${parcel.parcel_identity.apn_uid}.jpg`} x="0" y="0" width="800" height="480" preserveAspectRatio="none" opacity=".75" /> : <g className="map-context" opacity=".6"><path d="M-100 420L900 80M60-100L600 600" stroke="#46544a" strokeWidth="40" /><path d="M-100 420L900 80M60-100L600 600" stroke="#819080" strokeWidth="1" strokeDasharray="8 10" />
            {trees.map((t, i) => <circle key={i} cx={t.x} cy={t.y} r={t.r} fill={i % 2 ? "#344e35" : "#3c543c"} />)}
            <path d="M80 90h90v55H80zM620 300h100v70H620zM520 50h75v50h-75zM140 330h95v65h-95z" fill="#627064" stroke="#9ba99b" />
          </g>}
          {sorted.map((f, i) => {
            if (!visible.includes(layerNames[kinds.indexOf(f.properties.kind)])) return null;
            const detection = f.properties.kind === "cv_detection";
            return <path key={`${f.properties.kind}-${i}`} data-kind={f.properties.kind} d={path(f)} fill={color(f)} fillOpacity={detection ? .12 : f.properties.kind === "building_footprint" ? .22 : .07} fillRule="evenodd" stroke={color(f)} strokeWidth={detection ? 2 : 1.5} strokeDasharray={f.properties.kind === "zone_2_ring_30_100ft" ? "6 5" : f.properties.kind === "parcel_polygon" ? "3 3" : undefined} vectorEffect="non-scaling-stroke" className={detection && color(f) === "#ff796d" ? "detection" : "map-feature"} onClick={() => setSelected(f.properties.label)} role="button" tabIndex={0} aria-label={f.properties.label ?? f.properties.kind} onKeyDown={e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setSelected(f.properties.label); } }}><title>{f.properties.label}</title></path>;
          })}
          <circle cx="400" cy="240" r="4" fill="#fff" stroke="#12B5CB" strokeWidth="2" />
        </g>
      </svg>
      <div className="map-badge"><span className="status-dot" />{Math.round(privateLayer.cv_confidence * 100)}% CV confidence</div>
      <div className="compass"><Navigation size={18} /><span>N</span></div>
      <div className="map-tools"><button aria-label="Zoom in" onClick={() => setZoom(z => Math.min(3, z + .25))}><Plus size={17} /></button><button aria-label="Zoom out" onClick={() => setZoom(z => Math.max(.5, z - .25))}><Minus size={17} /></button><button aria-label="Reset map view" onClick={() => { setZoom(1); setPan({ x: 0, y: 0 }); }}><Crosshair size={17} /></button></div>
      <div className="map-coordinate">{lat.toFixed(5)}° N &nbsp; {Math.abs(lng).toFixed(5)}° W</div>
      <span className="map-disclaimer">{hasImagery ? "Esri / Maxar / Earthstar · Cached aerial" : "Illustrative basemap"}</span>
      {selected && <div className="map-popup" role="status">{selected}<button aria-label="Close feature details" onClick={() => setSelected(null)}>×</button></div>}
    </div>
    <div className="map-legend">{layerNames.map((name, i) => <label key={name}><input type="checkbox" checked={visible.includes(name)} onChange={() => setVisible(v => v.includes(name) ? v.filter(l => l !== name) : [...v, name])} /><span className={`legend-dot layer-${i}`} />{name}</label>)}</div>
    {hasImagery && <p className="footnote">Synthetic parcel overlays at the fixture centroid. Boundaries are not surveyed to the cached imagery.</p>}
    <div className="detection-list">{features.filter(f => f.properties.kind === "cv_detection").map((f,i) => <button key={i} onClick={() => setSelected(f.properties.label)}><span className={`status-dot ${/canopy|shed|unpermitted/i.test(f.properties.label ?? "") ? "danger" : ""}`} />{f.properties.label}<span>Inspect</span></button>)}</div>
  </section>;
}
