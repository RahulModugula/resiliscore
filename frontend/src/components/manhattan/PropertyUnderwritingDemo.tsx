"use client";

import { useEffect, useMemo, useReducer, useRef, useState } from "react";
import { CheckCheck, Download, RotateCcw, ScanLine, ShieldAlert, ShieldCheck } from "lucide-react";
import { Modal } from "@/components/Modal";
import { money } from "@/lib/format";
import { downloadText } from "@/lib/download";
import { buildingDemoReceipt, buildingDemoReducer, canCreateBuildingDemoReceipt, initialBuildingDemo, projectBuildingDemo } from "@/lib/manhattan/buildingDemo";
import type { ParcelScoreResponse } from "@/types/resiliscore";
import styles from "./PropertyUnderwritingDemo.module.css";

export default function PropertyUnderwritingDemo({ parcel, buildingId }: { parcel: ParcelScoreResponse; buildingId: string }) {
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    const element = heading.current;
    if (!element) return;
    element.focus({ preventScroll: true });
    const bounds = element.getBoundingClientRect();
    if (bounds.top < 0 || bounds.bottom > window.innerHeight) element.scrollIntoView({ block: "start" });
  }, []);
  const [state, dispatch] = useReducer(buildingDemoReducer, initialBuildingDemo);
  const [reviewOpen, setReviewOpen] = useState(false);
  const [receiptOpen, setReceiptOpen] = useState(false);
  const baseline = useMemo(() => projectBuildingDemo(parcel, initialBuildingDemo), [parcel]);
  const projected = useMemo(() => projectBuildingDemo(parcel, state), [parcel, state]);
  const a = projected.actuarial_breakdown;
  const action = baseline.prescriptive_mitigations.find(row => row.action_id === "HAIL_CLASS4_ROOF");
  const ready = canCreateBuildingDemoReceipt(state, projected);
  const receipt = receiptOpen && ready ? buildingDemoReceipt(buildingId, parcel, state) : null;
  const delta = a.resili_score - baseline.actuarial_breakdown.resili_score;
  function reset() { dispatch({ type: "reset" }); setReviewOpen(false); setReceiptOpen(false); }
  return <section className={`panel ${styles.demo}`} aria-label="Selected building underwriting demo">
    <div className="panel-heading"><h2 ref={heading} tabIndex={-1}>Building underwriting demo</h2><span className="badge warning">Simulated</span></div>
    <p className={styles.intro}>Test an improvement, run a simulated review, then prepare a demo receipt for building {buildingId}.</p>
    <p className="notice">National-default hazards, a nonlocal reference tract and a $350,000 assumed replacement value. These scenarios do not update this building&apos;s recorded assessment or verify its condition.</p>
    <table className={styles.comparison}>
      <caption>Canonical model scenarios for the selected building</caption>
      <thead><tr><th scope="col">Model output</th><th scope="col">Baseline</th><th scope="col">Scenario</th></tr></thead>
      <tbody>
        <tr><th scope="row">SaveMyHome / 850</th><td>{baseline.actuarial_breakdown.resili_score}</td><td data-testid="building-demo-score">{a.resili_score} <small>{delta >= 0 ? "+" : ""}{delta}</small></td></tr>
        <tr><th scope="row">Annual loss</th><td>{money(baseline.actuarial_breakdown.expected_annual_loss_usd)}</td><td data-testid="building-demo-loss">{money(a.expected_annual_loss_usd)}</td></tr>
        <tr><th scope="row">Modeled premium</th><td>{money(baseline.premium_build?.indicated_premium_usd ?? 0)}</td><td>{money(projected.premium_build?.indicated_premium_usd ?? 0)}</td></tr>
      </tbody>
    </table>
    <p className="footnote">Modeled premium includes the engine&apos;s assumed expense and profit loads. No filed New York quote or statutory credit is established. A score may stay flat or fall when assumed evidence changes.</p>
    <div className={styles.step}><h3>1. Test a mitigation</h3>
      {action && <label className={styles.action}><input type="checkbox" checked={state.roof} onChange={event => { dispatch({ type: "roof", selected: event.target.checked }); setReceiptOpen(false); }} /><span><strong>Assume a Class 4 impact-resistant roof</strong><small>{money(action.net_capex_usd)} assumed installation cost. The engine models completed work; no roof condition is measured.</small></span></label>}
      <button className="text-button" onClick={reset}><RotateCcw size={14} />Reset demo plan</button>
    </div>
    <div className={styles.step}><h3>2. Review simulated evidence</h3>
      <p role="status" className={styles.status}>{state.phase === "reviewed" ? <><CheckCheck size={17} />Demo review accepted. Actual verification remains unestablished.</> : <><ShieldAlert size={17} />Demo binding paused until simulated capture and review are complete.</>}</p>
      <button className="secondary-button" onClick={() => setReviewOpen(true)}>{state.phase === "reviewed" ? "View demo review" : "Open demo verification"}</button>
    </div>
    <div className={styles.step}><h3>3. Prepare a demo receipt</h3>
      <button className="primary-button" disabled={!ready} onClick={() => setReceiptOpen(true)}><ShieldCheck size={17} />Prepare demo binding receipt</button>
      <p className="footnote">Demo only. No policy, quote, payment or external underwriting workflow is created. Changing the assumed roof requires a new demo review.</p>
      {state.phase === "reviewed" && projected.hitl_status.escalated && <p role="status">The model still requires review: {projected.hitl_status.trigger_reason}</p>}
    </div>
    {reviewOpen && <Modal title="Demo property verification" onClose={() => setReviewOpen(false)}>
      <h3>{parcel.parcel_identity.address}</h3>
      <p className="notice">Building {buildingId} stays selected on the real map. This exercise accesses no camera, GPS, LiDAR, registry or insurer.</p>
      <dl className="audit-details"><div><dt>Roof assumption</dt><dd>{state.roof ? "Class 4 roof installed, simulated" : "Existing condition unknown"}</dd></div><div><dt>Capture</dt><dd>{state.phase === "planning" ? "Awaiting simulated capture" : "Complete in this demo only"}</dd></div><div><dt>Human review</dt><dd>{state.phase === "reviewed" ? "Accepted in this demo only" : "Awaiting demo approval"}</dd></div></dl>
      <div className={styles.reviewActions}>
        <button className="secondary-button" disabled={state.phase !== "planning"} onClick={() => dispatch({ type: "capture" })}><ScanLine size={16} />Run simulated building capture</button>
        <button className="primary-button" disabled={state.phase !== "captured"} onClick={() => { dispatch({ type: "approve" }); setReviewOpen(false); }}><CheckCheck size={16} />Accept demo evidence</button>
      </div>
      <p className="footnote">Approval assumes CV confidence of 0.99 for the model scenario. It does not establish an elevation certificate, roof inspection or actual verified mitigation.</p>
    </Modal>}
    {receipt && <Modal title="Selected building demo receipt" onClose={() => setReceiptOpen(false)}>
      <p className="notice">Simulated binding for building {buildingId}. No policy has been issued or sent to Guidewire.</p>
      <h3>{receipt.address}</h3>
      <dl className="audit-details"><div><dt>Demo status</dt><dd>{receipt.status}</dd></div><div><dt>Building</dt><dd>{receipt.building_id}</dd></div><div><dt>Actual policy number</dt><dd>None</dd></div></dl>
      <pre className="json-receipt">{JSON.stringify(receipt, null, 2)}</pre>
      <button className="primary-button" onClick={() => downloadText(`building-${buildingId}-demo-receipt.json`, JSON.stringify(receipt, null, 2))}><Download size={16} />Download building demo receipt</button>
    </Modal>}
  </section>;
}
