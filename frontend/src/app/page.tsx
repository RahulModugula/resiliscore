"use client";

import { useEffect, useMemo, useState } from "react";
import { ArrowRight, ChartNoAxesCombined, CheckCheck, Clock3, Download, FileCheck2, MapPin, ShieldAlert, Wrench } from "lucide-react";
import { HeaderScenarioBar } from "@/components/HeaderScenarioBar";
import { ParcelMapCanvas } from "@/components/ParcelMapCanvas";
import { FreeboardCrossSection } from "@/components/FreeboardCrossSection";
import { ScoreGaugeCard } from "@/components/ScoreGaugeCard";
import { MitigationDrawer } from "@/components/MitigationDrawer";
import { BindingReceipt } from "@/components/BindingReceipt";
import { HitlWorkbenchModal } from "@/components/HitlWorkbenchModal";
import { ModelValidationTab } from "@/components/ModelValidationTab";
import { RegulatoryAuditTab } from "@/components/RegulatoryAuditTab";
import { getScenario } from "@/data/goldenScenarios";
import { simulateMitigations, applyStructureLoading } from "@/lib/simulation";
import { requestParcel } from "@/lib/api";
import { downloadText } from "@/lib/download";
import { money } from "@/lib/format";
import type { GoldenScenarioKey, ParcelScoreResponse } from "@/types/resiliscore";

const tabs = ["Underwriting copilot", "Mitigation & grant ROI", "Regulatory audit", "Model Validation"];
type Resolution = "none" | "verified" | "loaded";

export default function Home() {
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
  const requestedScenario = alert && resolution !== "verified" ? "SCENARIO_3_ESCONDIDO_HITL__UNPERMITTED" : scenario;
  const key = JSON.stringify([requestedScenario, selected, resolution, live]);
  const baseline = useMemo(() => getScenario(requestedScenario), [requestedScenario]);
  const local = useMemo(() => {
    const projected = simulateMitigations(baseline, selected);
    if (resolution === "loaded") return applyStructureLoading(projected);
    if (resolution === "verified") projected.private_verification_layer.cv_confidence = .99;
    return projected;
  }, [baseline, selected, resolution]);
  const parcel = live && remote?.key === key ? remote.parcel : local;
  const pending = live && (network.key !== key || network.status === "loading");
  const isRemote = live && remote?.key === key;
  const isEscondido = scenario === "SCENARIO_3_ESCONDIDO_HITL";

  useEffect(() => {
    if (!live) return;
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
  }, [key, live, requestedScenario, selected, resolution]);

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
  const bindable = !escalated && (a.underwriting_tier === "TIER_1_AUTO_BIND" || a.underwriting_tier === "TIER_2_CONDITIONAL");
  return <div className="app-shell" data-theme={dark ? "dark" : "light"}>
    <a className="skip-link" href="#workspace">Skip to workspace</a>
    <HeaderScenarioBar active={scenario} onSelect={selectScenario} live={live} onLive={changeLive} dark={dark} onTheme={() => setDark(v => !v)} loading={pending} />
    <main className="main-content" id="workspace">
      <div className="workspace-tabs" role="tablist" aria-label="Workspace views">{tabs.map((name, i) => <button key={name} role="tab" aria-selected={tab === i} aria-controls={`workspace-panel-${i}`} id={`workspace-tab-${i}`} tabIndex={tab === i ? 0 : -1} className={tab === i ? "active" : ""} onClick={() => setTab(i)} onKeyDown={e => {
        if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key)) {
          e.preventDefault(); const index = e.key === "Home" ? 0 : e.key === "End" ? tabs.length - 1 : (tab + (e.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length;
          setTab(index); document.getElementById(`workspace-tab-${index}`)?.focus();
        }
      }}>{i === 0 ? <MapPin size={16} /> : i === 1 ? <Wrench size={16} /> : i === 2 ? <FileCheck2 size={16} /> : <ChartNoAxesCombined size={16} />}{name}</button>)}{tab !== 3 && <span className="workspace-tab-meta"><Clock3 size={13} />{(parcel.processing_time_ms / 1000).toFixed(2)}s fixture pipeline</span>}</div>
      {tab !== 3 && live && <div className={`status-notice ${network.status === "fallback" ? "warning" : ""}`} role="status">{network.key === key ? network.message : "Loading live evidence…"}</div>}
      {tab !== 3 && <>
      <div className="property-heading"><div><h2>{p.address.split(",")[0]}</h2><p><MapPin size={14} />{p.address.split(",").slice(1).join(",").trim()}<span className="badge">{isRemote ? "Live API" : "Golden demo parcel"}</span></p></div><div className="property-details"><span>APN <strong>{p.apn_uid}</strong></span><span>Built <strong>{p.year_built}</strong></span><span>Replacement value <strong>{money(p.rcv_usd)}</strong></span><button className="icon-button" aria-label="Download parcel JSON" onClick={() => downloadText(`parcel-${p.apn_uid}.json`, JSON.stringify(parcel, null, 2))}><Download size={17} /></button></div></div>
      {isEscondido && <label className="change-toggle"><input type="checkbox" checked={alert} onChange={e => toggleAlert(e.target.checked)} /><span><strong>Simulate satellite change-detection alert</strong><small>+240 sq ft unpermitted Zone 1 structure</small></span><span className="badge warning">HITL guardrail</span></label>}
      {escalated && <div className="hitl-banner" role="alert"><ShieldAlert size={25} /><div><strong>{parcel.hitl_status.trigger_code.replaceAll("_", " ")}</strong><p>{parcel.hitl_status.trigger_reason}</p><p>Straight-through processing paused. Escalated to the demo UnderwritingCenter.</p></div><button className="secondary-button" onClick={() => setModal("hitl")}>Open review workbench<ArrowRight size={16} /></button></div>}
      {resolution !== "none" && !escalated && <div className="status-notice success" role="status"><CheckCheck size={17} />{resolution === "verified" ? `Demo mobile evidence accepted. Open aluminum pergola verified. Auto-bind restored at ${a.resili_score}.` : "Demo structure loading applied: +35 bps LCR and $60,000 RCV at an assumed $250/sq ft. Conditional review required."}</div>}
      </>}
      <div role="tabpanel" id={`workspace-panel-${tab}`} aria-labelledby={`workspace-tab-${tab}`} className="tab-content">
        {tab === 3 ? <ModelValidationTab live={live} /> : tab === 2 ? <RegulatoryAuditTab parcel={parcel} simulated={selected.length > 0 || resolution !== "none"} /> : <>
          <div className="workspace-grid"><div className="spatial-column"><ParcelMapCanvas key={scenario} parcel={parcel} />{tab === 0 ? <FreeboardCrossSection hazard={parcel.public_hazard_layer} /> : <MitigationDrawer baseline={baseline} selected={selected} onToggle={toggleAction} onReset={() => setSelected([])} />}</div><ScoreGaugeCard parcel={parcel} simulated={selected.length > 0 || resolution === "loaded"} onAction={() => { if (bindable) setModal("receipt"); else setTab(1); }} /></div>
          {tab === 0 && <MitigationDrawer baseline={baseline} selected={selected} onToggle={toggleAction} onReset={() => setSelected([])} compact />}
        </>}
      </div>
      <footer className="app-footer">{tab === 3 ? <span><ShieldAlert size={14} />Model validation · Results retain their source caveats and adoption decisions</span> : <><span><ShieldAlert size={14} />Demonstration workspace · Synthetic parcel evidence · No policy issued</span><span>300–850 resilience scale · Contract v0.1</span></>}</footer>
    </main>
    {modal === "receipt" && bindable && <BindingReceipt parcel={parcel} selected={selected} onClose={() => setModal(null)} />}
    {modal === "hitl" && <HitlWorkbenchModal parcel={parcel} onClose={() => setModal(null)} onVerify={() => { setResolution("verified"); setModal(null); }} onLoading={() => { setResolution("loaded"); setModal(null); }} />}
  </div>;
}
