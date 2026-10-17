import { FileCheck2, ShieldAlert } from "lucide-react";
import type { ParcelScoreResponse } from "@/types/resiliscore";
import { PerilBreakdown } from "@/components/PerilBreakdown";
import { bps, money } from "@/lib/format";

/** Selected properties never inherit the golden demo's verified/bindable presentation. */
export function SelectedPropertySummary({ parcel, offline }: { parcel: ParcelScoreResponse; offline: boolean }) {
  const a = parcel.actuarial_breakdown;
  return <section className="score-panel panel"><div className="panel-heading"><h2>Property risk assessment</h2><span className="badge warning">{offline ? "Offline model screening" : parcel.indicative_only ? "Indicative only" : "Live model result"}</span></div>
    <div className="gauge-wrap warning"><p className="tier-text">{`ResiliScore ${a.resili_score} / 850`}</p><p className="section-description">{offline ? "Indicative screening from the canonical risk engine using national defaults and a nonlocal NRI reference tract. Buildings share these assumptions; this does not rank local geographic risk." : "Computed by the parcel risk engine for the selected building. This is an assessment, with no authority to bind a policy."}</p></div>
    <dl className="audit-details"><div><dt>Expected annual loss {offline && "(default inputs)"}</dt><dd>{money(a.expected_annual_loss_usd)}</dd></div><div><dt>Posterior loss cost</dt><dd>{bps(a.posterior_lcr)}</dd></div><div><dt>Premium</dt><dd>No filed quote supplied</dd></div><div><dt>Verified mitigation credit</dt><dd>Not established</dd></div><div><dt>Elevation certificate</dt><dd>{parcel.private_verification_layer.elev_cert_verified ? "Recorded verified by API" : "Not verified"}</dd></div></dl>
    <PerilBreakdown perils={a.peril_split} />
    <p className="status-notice warning"><ShieldAlert size={17} />Binding unavailable. Evidence and underwriting review required.</p>
    <p className="footnote">NYC map elevation is not certified first-floor height. A building footprint is not a parcel boundary. Missing inputs remain unknown.</p>
  </section>;
}

export function SelectedPropertyMitigations({ parcel, offline, contextOnly }: { parcel: ParcelScoreResponse; offline: boolean; contextOnly: boolean }) {
  const h = parcel.public_hazard_layer;
  return <section className="panel hazard-summary"><div className="panel-heading"><h2>{contextOnly ? "Hazard evidence" : "Mitigation review"}</h2><span className="badge">Selected building</span></div>
    {contextOnly ? <><dl className="audit-details"><div><dt>FEMA flood zone</dt><dd>{h.fema_flood_zone === "UNAVAILABLE" ? "Unknown" : `${h.fema_flood_zone}${offline ? " (default)" : ""}`}</dd></div><div><dt>Base flood elevation</dt><dd>{h.bfe_ft_navd88 === null ? "Unknown" : `${h.bfe_ft_navd88} ft NAVD88`}</dd></div><div><dt>Freeboard</dt><dd>{h.freeboard_delta_h_ft === null ? "Unknown" : `${h.freeboard_delta_h_ft} ft`}</dd></div></dl><p className="footnote">Ground elevation alone does not establish flood exposure or first-floor clearance.</p></> : <><p className="section-description">{offline ? "These recommendations come from the canonical model under default inputs. They are not verified property evidence. No local simulations, filed credits or binding actions are enabled." : "Review the engine's recommendations with an underwriter. Local action simulations and filed premium credits are unavailable for this property."}</p>{parcel.prescriptive_mitigations.length > 0 && <ul className="evidence-list">{parcel.prescriptive_mitigations.map(action => <li key={action.action_id}><span>{action.title}</span><span>{action.currently_applied ? "API reports applied" : "Review required"}</span></li>)}</ul>}</>}
  </section>;
}

export function SelectedPropertyEvidence({ parcel, offline }: { parcel: ParcelScoreResponse; offline: boolean }) {
  return <div className="audit-tab"><section className="panel"><div className="panel-heading"><h2><FileCheck2 size={18} />Assessment evidence</h2><span className="badge warning">No regulatory approval established</span></div><p className="section-description">{offline ? "The offline screen uses the actual backend risk engine with national defaults and a nonlocal FEMA NRI reference tract. The selected building geometry is real, but its local hazard inputs and replacement value are not measured. The model also assumes a LiDAR credibility weight without measured elevation. No policy decision or regulatory approval is established." : "Input provenance supplied by the risk assessment service. Defaults and missing evidence do not establish verification or filing readiness."}</p><div className="vintage-table-wrap"><table className="vintage-table"><caption>Input sources and availability</caption><thead><tr><th scope="col">Input</th><th scope="col">Status</th><th scope="col">Source</th></tr></thead><tbody>{parcel.input_provenance?.map((item, i) => <tr key={`${item.field}-${i}`}><th scope="row">{item.field}</th><td>{item.value_source}</td><td>{item.source_name}</td></tr>)}</tbody></table></div><p className="footnote">Map data provenance describes a cached geographic observation. It is not LiDAR verification, a roof inspection, an elevation certificate, or a statutory credit.</p></section></div>;
}
