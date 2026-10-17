"use client";

import { ArrowRight, Check, FileCheck2, ShieldCheck } from "lucide-react";
import { motion, useReducedMotion } from "framer-motion";
import type { ParcelScoreResponse } from "@/types/resiliscore";
import { bps, money, percent, tierLabel, perilLabel } from "@/lib/format";

export function ScoreGaugeCard({ parcel, simulated, localProjection = false, onAction }: { parcel: ParcelScoreResponse; simulated: boolean; localProjection?: boolean; onAction: () => void }) {
  const a = parcel.actuarial_breakdown, p = parcel.private_verification_layer;
  const reduced = useReducedMotion();
  const conditional = a.underwriting_tier === "TIER_2_CONDITIONAL";
  const tier = conditional ? 2 : a.resili_score >= 720 ? 1 : a.resili_score >= 580 ? 2 : 3;
  const tone = tier === 1 ? "success" : tier === 2 ? "warning" : "error";
  const delta = a.resili_score - a.baseline_macro_score;
  const angle = -90 + (a.resili_score - 300) / 550 * 180;
  const radians = angle * Math.PI / 180;
  const marker = `M${160 + 116 * Math.sin(radians)} ${150 - 116 * Math.cos(radians)}L${160 + 135 * Math.sin(radians)} ${150 - 135 * Math.cos(radians)}`;
  const channels = [
    ["USGS 3DEP · Ground elevation", "Supplied"],
    ["OpenFEMA · Elevation certificate", p.elev_cert_verified ? "Verified" : "Not verified"],
    ["Aerial computer vision", `${Math.round(p.cv_confidence * 100)}% confidence`],
    ["IBHS registry", p.ibhs_fortified_tier !== "NONE" ? `FORTIFIED ${p.ibhs_fortified_tier}` : p.ibhs_wph_tier !== "NONE" ? `WPH ${p.ibhs_wph_tier}` : "Not verified"],
    ["Flo · Water shutoff", p.iot_shutoff_active ? "Active" : "Not active"],
  ];
  return <section className="score-panel panel">
    <div className="panel-heading"><h2>Parcel ResiliScore</h2><span className={`badge ${tone}`}>{simulated ? "Projected" : "Verified parcel"}</span></div>
    <div className={`gauge-wrap ${tone}`}>
      <svg viewBox="0 0 320 190" className="score-gauge" role="img" aria-label={`ResiliScore ${a.resili_score} on a scale from 300 to 850`}>
        <path d="M35 150 A125 125 0 0 1 285 150" fill="none" stroke="var(--border)" strokeWidth="12" />
        <path d="M35 150 A125 125 0 0 1 163 25" fill="none" stroke="var(--red)" strokeWidth="12" />
        <path d="M168 25 A125 125 0 0 1 248 61" fill="none" stroke="var(--amber)" strokeWidth="12" />
        <path d="M252 66 A125 125 0 0 1 285 150" fill="none" stroke="var(--green)" strokeWidth="12" />
        <motion.path data-testid="score-marker" initial={false} animate={{ d: marker }} transition={{ duration: reduced ? 0 : .6, ease: [.16, 1, .3, 1] }} stroke="var(--text)" strokeWidth="4" strokeLinecap="round" />
        <text x="160" y="128" textAnchor="middle" className="score-number" fill="var(--text)" data-testid="score">{a.resili_score}</text><text x="160" y="151" textAnchor="middle" fill="var(--muted)" fontSize="12">of 850</text><text x="28" y="177" fill="var(--muted)" fontSize="11">300</text><text x="272" y="177" fill="var(--muted)" fontSize="11">850</text>
      </svg>
      <p className={`tier-text ${tone}`}>{parcel.hitl_status.escalated ? "Auto-bind paused · Human review" : conditional ? "Tier 2 · Conditional bind" : tierLabel(a.resili_score)}</p>
    </div>
    <div className="prior-comparison"><span>Macro census-tract score <strong>{a.baseline_macro_score}</strong></span><span className={`delta ${delta >= 0 ? "success" : "error"}`}>{delta >= 0 ? "+" : ""}{delta} pts</span></div>
    <div className="score-financials"><div><span>Expected annual loss</span><strong>{money(a.expected_annual_loss_usd)}<small> / yr</small></strong></div><div><span>Parcel loss cost</span><strong>{bps(a.posterior_lcr)}</strong></div></div>
    <dl className="peril-split" aria-label="Expected annual loss by peril">{a.peril_split.map(item => <div key={item.peril}><dt>{perilLabel(item.peril)}</dt><dd>{money(item.peril_aal_usd)} / yr</dd></div>)}</dl>
    {localProjection && <p className="footnote">Offline projections retain the baseline peril allocation.</p>}
    <div className="premium-line"><span>Annual premium</span><span>{a.annual_base_premium_usd !== a.annual_discounted_premium_usd && <del>{money(a.annual_base_premium_usd)}</del>} <strong>{money(a.annual_discounted_premium_usd)}</strong></span></div>
    <button className={`primary-button ${tone}`} onClick={onAction} disabled={parcel.hitl_status.escalated}><ShieldCheck size={17} />{parcel.hitl_status.escalated ? "Binding paused for verification" : tier === 1 ? "Auto-bind in PolicyCenter" : tier === 2 ? "Issue 60-day conditional bind" : "Explore mitigation plan"}<ArrowRight size={16} /></button>
    <p className="cta-note">{tier === 1 ? `${percent(a.statutory_discount_pct)} statutory credit · Demo receipt` : tier === 2 ? "Action plan and review required · Demo only" : "Test physical improvements before underwriting."}</p>
    <div className="credibility"><div className="panel-heading"><h3>Bühlmann-Straub credibility</h3><strong>Z = {a.credibility_weight_z.toFixed(2)}</strong></div>
      <div className="credibility-track" role="meter" aria-label="Parcel credibility weight" aria-valuenow={a.credibility_weight_z * 100} aria-valuemin={0} aria-valuemax={100}><span style={{ width: `${a.credibility_weight_z * 100}%` }} /></div><div className="bar-labels"><span>{Math.round(a.credibility_weight_z * 100)}% parcel evidence</span><span>{Math.round((1-a.credibility_weight_z)*100)}% tract prior</span></div>
      <div className="formula">LCR<sub>post</sub> = Z × LCR<sub>parcel</sub> + (1 − Z) × μ<sub>tract</sub></div>
      <div className="formula-values"><span>Tract prior <strong>{bps(a.tract_prior_lcr)}</strong></span><span>Parcel raw <strong>{bps(a.parcel_raw_lcr)}</strong></span></div>
      <ul className="evidence-list">{channels.map(([label,status]) => <li key={label}><span><FileCheck2 size={14} />{label}</span><span>{/Not |Estimate/.test(status) ? null : <Check size={12} />}{status}</span></li>)}</ul>
      <p className="footnote">Channel statuses are supplied evidence. Individual precision weights are not included in this contract.</p>
    </div>
  </section>;
}
