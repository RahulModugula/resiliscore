"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { SelectedPropertySummary, SelectedPropertyEvidence, SelectedPropertyMitigations } from "@/components/SelectedPropertyAssessment";
import { ArrowRight, CheckCheck, Clock3, Download, FileCheck2, MapPin, ShieldAlert, Wrench, Moon, Sun } from "lucide-react";
import { HeaderScenarioBar } from "@/components/HeaderScenarioBar";
import { BlockContextView } from "@/components/manhattan/BlockContextView";
import { ParcelMapCanvas } from "@/components/ParcelMapCanvas";
import { FreeboardCrossSection } from "@/components/FreeboardCrossSection";
import { ScoreGaugeCard } from "@/components/ScoreGaugeCard";
import { MitigationDrawer } from "@/components/MitigationDrawer";
import { BindingReceipt } from "@/components/BindingReceipt";
import { HitlWorkbenchModal } from "@/components/HitlWorkbenchModal";
import { RegulatoryAuditTab } from "@/components/RegulatoryAuditTab";
import { getScenario } from "@/data/goldenScenarios";
import { simulateMitigations, applyStructureLoading } from "@/lib/simulation";
import { requestParcel } from "@/lib/api";
import { downloadText } from "@/lib/download";
import { money } from "@/lib/format";
import type { GoldenScenarioKey, ParcelScoreResponse } from "@/types/resiliscore";

const tabs = ["Underwriting copilot", "Mitigation & grant ROI", "Regulatory audit"];
type Resolution = "none" | "verified" | "loaded";

export interface SelectedProperty {
  id: string;
  label: string;
  neighborhoodId: string;
}

export interface UnderwritingWorkspaceProps {
  initialParcel?: ParcelScoreResponse;
  selectedProperty?: SelectedProperty;
  assessmentSource?: "live" | "local";
  assessmentNotice?: string;
}

export function UnderwritingWorkspace({ initialParcel, selectedProperty, assessmentSource, assessmentNotice }: UnderwritingWorkspaceProps = {}) {
  const [contextAddress, setContextAddress] = useState<{ id: string; address: string | null } | null>(null);
  const resolveAddress = useCallback((address: string | null) => { if (selectedProperty) setContextAddress({ id: selectedProperty.id, address }); }, [selectedProperty]);
  const propertyTitle = selectedProperty ? contextAddress?.id === selectedProperty.id ? contextAddress.address ?? "Address unavailable" : selectedProperty.label : initialParcel?.parcel_identity.address;
  const [scenario, setScenario] = useState<GoldenScenarioKey>("SCENARIO_1_LA_FLOOD");
  const [tab, setTab] = useState(0);
  const [dark, setDark] = useState(true);
  const [live, setLive] = useState(false);
  const [selected, setSelected] = useState<string[]>([]);
  const [alert, setAlert] = useState(false);
  const [resolution, setResolution] = useState<Resolution>("none");
  const [modal, setModal] = useState<"receipt" | "hitl" | null>(null);
  const [remote, setRemote] = useState<{ key: string; parcel: ParcelScoreResponse } | null>(null);
  const [network, setNetwork] = useState({ key: "", status: "idle", message: "" });
  const isSelectedProperty = !!initialParcel;
  const offlineScreening = isSelectedProperty && assessmentSource === "local";
  const requestedScenario = alert && resolution !== "verified" ? "SCENARIO_3_ESCONDIDO_HITL__UNPERMITTED" : scenario;
  const key = JSON.stringify([requestedScenario, selected, resolution, live]);
  const baseline = useMemo(() => initialParcel ?? getScenario(requestedScenario), [initialParcel, requestedScenario]);
  const local = useMemo(() => {
    const projected = simulateMitigations(baseline, selected);
    if (resolution === "loaded") return applyStructureLoading(projected);
    if (resolution === "verified") projected.private_verification_layer.cv_confidence = .99;
    return projected;
  }, [baseline, selected, resolution]);
  const parcel = live && remote?.key === key ? remote.parcel : local;
  const pending = live && (network.key !== key || network.status === "loading");
  const isRemote = live && remote?.key === key;
  const isEscondido = !isSelectedProperty && scenario === "SCENARIO_3_ESCONDIDO_HITL";

  useEffect(() => {
    if (!live || isSelectedProperty) return;
    const controller = new AbortController();
    setNetwork({ key, status: "loading", message: "Requesting live parcel evidence. The demo remains available." });
    async function fetchParcel() {
      try {
        let result = await requestParcel("/v1/parcel/score", { scenario_id: requestedScenario }, controller.signal);
        if (selected.length) result = await requestParcel("/v1/parcel/simulate-mitigation", { apn_uid: result.parcel_identity.apn_uid, action_ids: selected }, controller.signal);
        if (resolution !== "none") result = await requestParcel("/v1/hitl/verify-override", {
          apn_uid: result.parcel_identity.apn_uid, resolution, approved: resolution === "verified", verification_method: "demo_mobile_inspection", simulate: true,
        }, controller.signal);
        if (!controller.signal.aborted) {
          setRemote({ key, parcel: result });
          setNetwork({ key, status: "ready", message: "Live API response validated against the parcel contract." });
        }
      } catch (error) {
        if (!controller.signal.aborted) setNetwork({ key, status: "fallback", message: `${error instanceof Error ? error.message : "API unavailable"}. Showing the local demo. All controls remain available.` });
      }
    }
    void fetchParcel();
    return () => controller.abort();
  }, [key, live, requestedScenario, selected, resolution, isSelectedProperty]);

  function selectScenario(id: GoldenScenarioKey) {
    setScenario(id); setSelected([]); setAlert(false); setResolution("none"); setModal(null); setRemote(null);
  }
  function toggleAction(id: string) {
    setSelected(values => values.includes(id) ? values.filter(v => v !== id) : [...values, id]);
    setModal(null);
  }
  function toggleAlert(value: boolean) {
    setAlert(value); setResolution("none"); setModal(null);
  }
  function changeLive(value: boolean) {
    setRemote(null); setNetwork({ key: "", status: "idle", message: "" }); setModal(null); setLive(value);
  }
  const a = parcel.actuarial_breakdown;
  const p = parcel.parcel_identity;
  const escalated = parcel.hitl_status.escalated;
  const bindable = !isSelectedProperty && !escalated && (a.underwriting_tier === "TIER_1_AUTO_BIND" || a.underwriting_tier === "TIER_2_CONDITIONAL");
  return <div className="app-shell" data-theme={dark ? "dark" : "light"}>
    <a className="skip-link" href="#workspace">Skip to workspace</a>
    {isSelectedProperty ? <header className="topbar"><Link className="brand" href="/">ResiliScore</Link><span className="brand-description">Manhattan property assessment</span><div className="header-actions"><Link className="secondary-button" href={selectedProperty ? `/?neighborhood=${encodeURIComponent(selectedProperty.neighborhoodId)}` : "/"}>Back to Manhattan map</Link><button className="icon-button" onClick={() => setDark(v => !v)} aria-label={dark ? "Use light theme" : "Use dark theme"}>{dark ? <Sun size={18} /> : <Moon size={18} />}</button></div></header> : <HeaderScenarioBar active={scenario} onSelect={selectScenario} live={live} onLive={changeLive} dark={dark} onTheme={() => setDark(v => !v)} loading={pending} />}
    <main className="main-content" id="workspace">
      <div className="workspace-tabs" role="tablist" aria-label="Workspace views">{tabs.map((name, i) => <button key={name} role="tab" aria-selected={tab === i} aria-controls={`workspace-panel-${i}`} id={`workspace-tab-${i}`} tabIndex={tab === i ? 0 : -1} className={tab === i ? "active" : ""} onClick={() => setTab(i)} onKeyDown={e => {
        if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key)) {
          e.preventDefault(); const index = e.key === "Home" ? 0 : e.key === "End" ? 2 : (tab + (e.key === "ArrowRight" ? 1 : 2)) % 3;
          setTab(index); document.getElementById(`workspace-tab-${index}`)?.focus();
        }
      }}>{i === 0 ? <MapPin size={16} /> : i === 1 ? <Wrench size={16} /> : <FileCheck2 size={16} />}{name}</button>)}<span className="workspace-tab-meta"><Clock3 size={13} />{offlineScreening ? "Offline engine screening" : `${(parcel.processing_time_ms / 1000).toFixed(2)}s ${isSelectedProperty ? "assessment pipeline" : "fixture pipeline"}`}</span></div>
      {isSelectedProperty && <div className="status-notice warning" role="status">{assessmentNotice ?? "Selected property assessment. No policy is issued by this workspace."}</div>}
      {live && <div className={`status-notice ${network.status === "fallback" ? "warning" : ""}`} role="status">{network.key === key ? network.message : "Loading live evidence…"}</div>}
      <div className="property-heading"><div><h2>{isSelectedProperty ? propertyTitle : p.address.split(",")[0]}</h2><p><MapPin size={14} />{p.address.split(",").slice(1).join(",").trim()}<span className="badge">{isSelectedProperty ? offlineScreening ? "Offline model screening" : parcel.indicative_only ? "Indicative live assessment" : "Live assessment" : isRemote ? "Live API" : "Golden demo parcel"}</span></p></div><div className="property-details"><span>{isSelectedProperty ? "Building" : "APN"} <strong>{selectedProperty?.id ?? p.apn_uid}</strong></span><span>Built <strong>{p.year_built}{isSelectedProperty && parcel.input_provenance?.some(row => row.field === "year_built" && row.value_source === "DEFAULT") ? " (default)" : ""}</strong></span><span>Replacement value <strong>{offlineScreening ? `${money(p.rcv_usd)} default` : money(p.rcv_usd)}</strong></span><button className="icon-button" aria-label="Download parcel JSON" onClick={() => downloadText(`parcel-${p.apn_uid}.json`, JSON.stringify(parcel, null, 2))}><Download size={17} /></button></div></div>
      {isEscondido && <label className="change-toggle"><input type="checkbox" checked={alert} onChange={e => toggleAlert(e.target.checked)} /><span><strong>Simulate satellite change-detection alert</strong><small>+240 sq ft unpermitted Zone 1 structure</small></span><span className="badge warning">HITL guardrail</span></label>}
      {escalated && !isSelectedProperty && <div className="hitl-banner" role="alert"><ShieldAlert size={25} /><div><strong>{parcel.hitl_status.trigger_code.replaceAll("_", " ")}</strong><p>{parcel.hitl_status.trigger_reason}</p><p>Straight-through processing paused. Escalated to the demo UnderwritingCenter.</p></div><button className="secondary-button" onClick={() => setModal("hitl")}>Open review workbench<ArrowRight size={16} /></button></div>}
      {resolution !== "none" && !escalated && <div className="status-notice success" role="status"><CheckCheck size={17} />{resolution === "verified" ? `Demo mobile evidence accepted. Open aluminum pergola verified. Auto-bind restored at ${a.resili_score}.` : "Demo structure loading applied: +35 bps LCR and $60,000 RCV at an assumed $250/sq ft. Conditional review required."}</div>}
      <div role="tabpanel" id={`workspace-panel-${tab}`} aria-labelledby={`workspace-tab-${tab}`} className="tab-content">
        {tab === 2 ? isSelectedProperty ? <SelectedPropertyEvidence parcel={parcel} offline={offlineScreening} /> : <RegulatoryAuditTab parcel={parcel} simulated={selected.length > 0 || resolution !== "none"} /> : <>
          <div className="workspace-grid"><div className="spatial-column">{selectedProperty ? <BlockContextView property={selectedProperty} onAddressResolved={resolveAddress} /> : <ParcelMapCanvas key={scenario} parcel={parcel} showIllustrativeContext={!isSelectedProperty} />}{isSelectedProperty ? <SelectedPropertyMitigations parcel={parcel} offline={offlineScreening} contextOnly={tab === 0} /> : tab === 0 ? <FreeboardCrossSection hazard={parcel.public_hazard_layer} /> : <MitigationDrawer baseline={baseline} selected={selected} onToggle={toggleAction} onReset={() => setSelected([])} />}</div>{isSelectedProperty ? <SelectedPropertySummary parcel={parcel} offline={offlineScreening} /> : <ScoreGaugeCard parcel={parcel} simulated={selected.length > 0 || resolution === "loaded"} onAction={() => { if (bindable) setModal("receipt"); else setTab(1); }} />}</div>
          {tab === 0 && !isSelectedProperty && <MitigationDrawer baseline={baseline} selected={selected} onToggle={toggleAction} onReset={() => setSelected([])} compact />}
        </>}
      </div>
      <footer className="app-footer"><span><ShieldAlert size={14} />{isSelectedProperty ? "Selected NYC building · Evidence status shown explicitly · No policy issued" : "Demonstration workspace · Synthetic parcel evidence · No policy issued"}</span><span>300–850 resilience scale · Contract v2</span></footer>
    </main>
    {modal === "receipt" && bindable && <BindingReceipt parcel={parcel} selected={selected} onClose={() => setModal(null)} />}
    {modal === "hitl" && <HitlWorkbenchModal parcel={parcel} onClose={() => setModal(null)} onVerify={() => { setResolution("verified"); setModal(null); }} onLoading={() => { setResolution("loaded"); setModal(null); }} />}
  </div>;
}
