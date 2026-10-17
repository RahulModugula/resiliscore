"use client";

import { ArrowUpRight, Check, RotateCcw, Wrench } from "lucide-react";
import type { ParcelScoreResponse } from "@/types/resiliscore";
import { money } from "@/lib/format";
import { actionTotals } from "@/lib/simulation";

export function MitigationDrawer({ baseline, selected, onToggle, onReset, compact = false }: { baseline: ParcelScoreResponse; selected: string[]; onToggle: (id: string) => void; onReset: () => void; compact?: boolean }) {
  const totals = actionTotals(baseline, selected);
  return <section className={`panel mitigation-panel ${compact ? "compact" : ""}`}><div className="panel-heading"><h2><Wrench size={17} />{compact ? "Mitigation opportunities" : "Prescriptive mitigation & grant ROI"}</h2>{selected.length > 0 && <button className="text-button" onClick={onReset}><RotateCcw size={13} />Reset plan</button>}</div>
    <p className="section-description">{baseline.prescriptive_mitigations.every(a => a.currently_applied) ? "Verified improvements are already reflected in this parcel's score and premium." : "Build an action plan. Compare the projected score and premium as you go."}</p>
    <div className="mitigation-list">{baseline.prescriptive_mitigations.map(a => <label key={a.action_id} className={`mitigation-row ${selected.includes(a.action_id) ? "chosen" : ""} ${a.currently_applied ? "applied" : ""}`}>
      <input type="checkbox" checked={a.currently_applied || selected.includes(a.action_id)} disabled={a.currently_applied} onChange={() => onToggle(a.action_id)} />
      <span className="mitigation-copy"><strong>{a.title}</strong><small>{a.statutory_authority}</small><span className="mitigation-costs"><span>{money(a.net_capex_usd)} net cost</span><span>{a.payback_years} yr payback</span><span>+{a.resale_value_bump_pct}% resale estimate</span></span>{a.grant_subsidy_usd > 0 && <span className="grant-line">{money(a.gross_capex_usd)} gross − {money(a.grant_subsidy_usd)} grant = {money(a.net_capex_usd)} net</span>}</span>
      <span className="mitigation-impact">{a.currently_applied ? <span className="badge success"><Check size={12} />Applied</span> : <strong>+{a.score_delta_pts} pts</strong>}<span>{money(a.annual_premium_savings_usd)} / yr saved</span></span>
    </label>)}</div>
    {!baseline.prescriptive_mitigations.every(a => a.currently_applied) && <><dl className="metrics four plan-totals"><div><dt>Net investment</dt><dd data-testid="net-investment">{money(totals.net)}</dd></div><div><dt>Annual savings</dt><dd className="success" data-testid="annual-savings">{money(totals.savings)}</dd></div><div><dt>Grant offsets</dt><dd>{money(totals.grants)}</dd></div><div><dt>Simple payback</dt><dd>{totals.savings ? `${(totals.net / totals.savings).toFixed(1)} yr` : "Select actions"}</dd></div></dl><p className="footnote"><ArrowUpRight size={13} />Combined projections use backend-generated model results. Quotes require verified completion.</p></>}
  </section>;
}
