"use client";

import { Check, Download, FileText, ShieldCheck, X } from "lucide-react";
import type { Ca26449Factors, ParcelScoreResponse } from "@/types/resiliscore";
import { downloadText } from "@/lib/download";
import { bps, money, tierLabel } from "@/lib/format";

const factorGroups: { title: string; factors: [keyof Ca26449Factors, string][] }[] = [
  { title: "A · Community", factors: [
    ["cat_a_fire_risk_reduction_community", "Fire risk reduction community"],
    ["cat_a_firewise_usa", "Firewise USA community"],
    ["cat_a_shelter_in_place", "Shelter-in-place designation"],
  ] },
  { title: "B1 · Immediate surroundings", factors: [
    ["cat_b1_under_deck_clearing", "Under-deck clearing"],
    ["cat_b1_zone0_clear_0_5ft", "Clear 0–5 ft noncombustible zone"],
    ["cat_b1_no_sheds_within_30ft", "No combustible sheds within 30 ft"],
    ["cat_b1_prc_4291_compliance", "PRC § 4291 clearance"],
  ] },
  { title: "B2 · Structure hardening", factors: [
    ["cat_b2_class_a_roof", "Class A roof"],
    ["cat_b2_enclosed_eaves", "Enclosed eaves"],
    ["cat_b2_ember_vents", "Ember-resistant vents"],
    ["cat_b2_multi_pane_windows", "Multi-pane windows"],
    ["cat_b2_vertical_siding_clearance_6in", "6-inch vertical siding clearance"],
  ] },
];

export function RegulatoryAuditTab({ parcel, simulated = false }: { parcel: ParcelScoreResponse; simulated?: boolean }) {
  const compliance = parcel.regulatory_compliance;
  const actuarial = parcel.actuarial_breakdown;
  const vintageEntries = Object.entries(compliance.dataset_vintages);
  const dossier = {
    demo: true,
    simulated_counterfactual: simulated,
    regulatory_approval: "NOT_ESTABLISHED",
    evidence_scope: "Contract payload and local demo state. No live regulatory or external validation.",
    bisg_adverse_impact_test: "NOT_PROVIDED",
    live_partial_derivatives: "NOT_PROVIDED",
    module_independence_validation: "NOT_PROVIDED",
    score_calibration: "Golden fixture anchors; docs/DECISIONS.md D1 remains open.",
    parcel,
  };
  const notice = [
    "RESILISCORE DEMO CONSUMER MITIGATION NOTICE",
    "Sample only. This is not a filed or approved adverse action notice.",
    `Property: ${parcel.parcel_identity.address}`,
    `APN: ${parcel.parcel_identity.apn_uid}`,
    `Request: ${parcel.request_id}`,
    `ResiliScore: ${actuarial.resili_score}; ${tierLabel(actuarial.resili_score)}`,
    `Underwriting route: ${actuarial.underwriting_tier}`,
    `Posterior loss cost ratio: ${bps(actuarial.posterior_lcr)}`,
    `Annual premium in demo: ${money(actuarial.annual_discounted_premium_usd)}`,
    `Human review: ${parcel.hitl_status.escalated ? parcel.hitl_status.trigger_reason ?? parcel.hitl_status.trigger_code : "No active escalation"}`,
    "Factors recorded false or not established in the supplied payload:",
    ...factorGroups.flatMap(group => group.factors.filter(([key]) => !compliance.ca_2644_9_factors[key]).map(([, label]) => `- ${label}`)),
    "Available mitigation actions:",
    ...parcel.prescriptive_mitigations.map(action => `- ${action.title}; ${money(action.net_capex_usd)} net cost; ${action.currently_applied ? "already applied" : `${money(action.annual_premium_savings_usd)}/yr estimated savings`}`),
    "Request a human review and correction of inaccurate property information from the underwriting team. Contact details and appeal deadlines are not supplied by this demo.",
    "BISG adverse impact analysis, production validation, regulatory approval, and live sensor evidence are not supplied.",
    simulated ? "This notice includes locally simulated changes." : "Values are from the supplied scenario payload.",
  ].join("\n\n");

  return <div className="audit-tab">
    <section className="panel audit-intro"><div className="panel-heading"><h2><ShieldCheck size={18} />Regulatory filing & audit dossier</h2><span className="badge warning">Demo evidence</span></div><p className="section-description">Review the supplied parcel factors and model declarations. This dashboard does not establish approval by CDI, NY DFS, FL OIR, or FCHLPM.</p><div className="audit-downloads"><button className="secondary-button" onClick={() => downloadText(`consumer-notice-${parcel.parcel_identity.apn_uid}.txt`, notice, "text/plain;charset=utf-8")}><FileText size={16} />Download consumer notice</button><button className="primary-button" onClick={() => downloadText(`audit-dossier-${parcel.parcel_identity.apn_uid}.json`, JSON.stringify(dossier, null, 2))}><Download size={16} />Download full JSON dossier</button></div>{simulated && <p className="notice">This view includes local demo changes. Recheck source evidence before filing or quoting.</p>}</section>
    <div className="audit-grid">
      <section className="panel"><div className="panel-heading"><h2>Mathematical monotonicity</h2></div><p className="section-description">Bühlmann-Straub credibility blend from the contract.</p><div className="audit-formula">LCR_post = Z × LCR_parcel + (1 − Z) × μ_tract</div><dl className="audit-details"><div><dt>Credibility Z</dt><dd>{actuarial.credibility_weight_z.toFixed(2)}</dd></div><div><dt>Parcel raw / tract prior</dt><dd>{bps(actuarial.parcel_raw_lcr)} / {bps(actuarial.tract_prior_lcr)}</dd></div><div><dt>Supplied posterior</dt><dd>{bps(actuarial.posterior_lcr)}</dd></div><div><dt>Monotonicity declaration</dt><dd className={compliance.monotonicity_verified ? "success" : "warning"}>{compliance.monotonicity_verified ? "Verified flag supplied" : "Not verified"}</dd></div><div><dt>Live partial derivatives</dt><dd>Not provided</dd></div></dl><p className="footnote">The flag is a model declaration, not a derivative test run by this UI. Scores use the golden fixture anchors; score-curve calibration is still open in DECISIONS D1.</p></section>
      <section className="panel"><div className="panel-heading"><h2>NY DFS Circular Letter 7</h2></div><dl className="audit-details"><div><dt>ECDIS-free declaration</dt><dd className={compliance.ny_dfs_cl7_ecdis_free ? "success" : "warning"}>{compliance.ny_dfs_cl7_ecdis_free ? "True in supplied payload" : "False in supplied payload"}</dd></div><div><dt>Feature inventory / feature count</dt><dd>Not provided</dd></div><div><dt>BISG adverse impact analysis</dt><dd>Evidence not provided</dd></div><div><dt>Article 24 consumer notice</dt><dd>Sample download available</dd></div></dl><p className="footnote">A declaration alone does not establish fairness or filing readiness. The contract contains no BISG test result or approval evidence.</p></section>
    </div>
    <section className="panel"><div className="panel-heading"><h2>California 10 CCR § 2644.9 factors</h2><span className="badge">12 supplied factors</span></div><p className="section-description">True means recorded as met. False means recorded as not met or not established; the contract does not distinguish those states. California factors are shown for every demo parcel and may not apply outside California.</p><div className="factor-groups">{factorGroups.map(group => <div className="factor-group" key={group.title}><h3>{group.title}</h3><ul className="factor-list">{group.factors.map(([key, label]) => <li key={key}><span>{label}</span><span className={`factor-status ${compliance.ca_2644_9_factors[key] ? "success" : "muted"}`}>{compliance.ca_2644_9_factors[key] ? <Check size={14} /> : <X size={14} />}{compliance.ca_2644_9_factors[key] ? "True" : "False"}</span></li>)}</ul></div>)}</div></section>
    <section className="panel"><div className="panel-heading"><h2>Florida FCHLPM G-4 · Data provenance</h2></div><p className="section-description">Declared model separation is meteorology and hazard, vulnerability, then actuarial credibility. Independence testing, approval evidence, and USACE / IBHS dataset vintages are not supplied.</p><div className="vintage-table-wrap"><table className="vintage-table"><caption>Dataset identifiers exactly as supplied by the contract</caption><thead><tr><th scope="col">Dataset</th><th scope="col">Vintage / version identifier</th></tr></thead><tbody>{vintageEntries.map(([dataset, version]) => <tr key={dataset}><th scope="row">{dataset}</th><td>{version || "Unknown"}</td></tr>)}</tbody></table>{vintageEntries.length === 0 && <p className="notice">No dataset vintages supplied.</p>}</div><p className="footnote">Version labels are not necessarily acquisition dates. No live source freshness check has run. Request ID {parcel.request_id}.</p></section>
  </div>;
}
