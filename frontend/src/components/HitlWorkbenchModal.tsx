"use client";

import { useEffect, useState } from "react";
import Image from "next/image";
import QRCode from "qrcode";
import { AlertTriangle, Check, ScanLine, Smartphone } from "lucide-react";
import { Modal } from "./Modal";
import type { ParcelScoreResponse } from "@/types/resiliscore";

export function DemoInspection({ apn, onCapture }: { apn: string; onCapture?: () => void }) {
  const [captured, setCaptured] = useState(false);
  return <section className="phone-inspection" aria-label="Simulated smartphone inspection">
    <div className="phone-topline"><Smartphone size={18} /><strong>Self-inspection demo</strong><span className="badge warning">Simulated</span></div>
    <p className="section-description">APN {apn}</p>
    <div className={`scan-viewport ${captured ? "captured" : ""}`}>
      <svg viewBox="0 0 280 180" role="img" aria-label="Illustration of an open aluminum pergola under review">
        <path d="M35 150 140 106 248 150M63 66 165 29 228 58 126 98Z" fill="none" stroke="currentColor" strokeWidth="3" />
        <path d="M63 66V148M126 98V168M228 58V143M165 29V108M79 60 143 92M98 53 162 84M118 46 182 77M138 39 202 69M63 79 126 111 228 71" fill="none" stroke="currentColor" strokeWidth="2" />
        <path d="M20 45V20H45M235 20H260V45M20 135V160H45M235 160H260V135" fill="none" stroke="currentColor" strokeWidth="2" />
      </svg>
      <span><ScanLine size={15} />{captured ? "Demo capture complete" : "Ready for simulated capture"}</span>
    </div>
    <p className="footnote">This illustration simulates GPS and LiDAR evidence. It does not access a camera, GPS, or depth sensor.</p>
    <button className="primary-button" disabled={captured} onClick={() => { setCaptured(true); onCapture?.(); }}><ScanLine size={16} />{captured ? "Demo capture complete" : "Run demo capture"}</button>
    <div className="inspection-results" aria-live="polite">
      <dl className="audit-details"><div><dt>RTK-GPS footprint match</dt><dd>{captured ? "Verified in simulation" : "Awaiting demo capture"}</dd></div><div><dt>LiDAR structure classification</dt><dd>{captured ? "Open aluminum pergola, simulated" : "Unknown"}</dd></div><div><dt>Enclosed combustible area</dt><dd>{captured ? "None, simulated" : "Unknown"}</dd></div></dl>
    </div>
  </section>;
}

export function HitlWorkbenchModal({ parcel, onClose, onVerify, onLoading }: { parcel: ParcelScoreResponse; onClose: () => void; onVerify: () => void; onLoading: () => void }) {
  const [inspectionOpen, setInspectionOpen] = useState(false);
  const [captured, setCaptured] = useState(false);
  const [qr, setQr] = useState<string | null>(null);
  const [inspectionUrl, setInspectionUrl] = useState("");
  const [qrError, setQrError] = useState(false);
  const apn = parcel.parcel_identity.apn_uid;
  useEffect(() => {
    let active = true;
    const url = `${window.location.origin}/inspect?apn=${encodeURIComponent(apn)}`;
    QRCode.toDataURL(url, { width: 192, margin: 2, errorCorrectionLevel: "M" }).then(value => {
      if (active) { setQr(value); setInspectionUrl(url); }
    }).catch(() => { if (active) { setQrError(true); setInspectionUrl(url); } });
    return () => { active = false; };
  }, [apn]);

  return <Modal title="Human review workbench" onClose={onClose}>
    <div className="hitl-alert" role="alert"><AlertTriangle size={22} /><div><strong>Straight-through processing paused</strong><p>{parcel.hitl_status.trigger_code === "NONE" ? "HITL_TRIGGER_02_UNPERMITTED_ADDITION" : parcel.hitl_status.trigger_code}</p><p>{parcel.hitl_status.trigger_reason ?? "Simulated satellite change detection found a +240 sq ft addition in Zone 1, above the 150 sq ft review threshold."}</p></div></div>
    <p className="notice">Demo escalation to Guidewire UnderwritingCenter. No external workflow has been created.</p>
    <h3>{parcel.parcel_identity.address}</h3>
    <p className="section-description">Resolve the alert with simulated inspection evidence or apply the demo structure loading and route to a 60-day conditional bind.</p>
    {!inspectionOpen && <button className="primary-button" onClick={() => setInspectionOpen(true)}><Smartphone size={16} />Request smartphone verification</button>}
    {inspectionOpen && <div className="inspection-workbench">
      <div className="inspection-link"><h3>Open the mobile inspection</h3>{qr && <Image className="inspection-qr" src={qr} alt="QR code linking to this parcel's mobile demo inspection" width={192} height={192} unoptimized />}{!qr && <p role="status">{qrError ? "QR generation failed. Use the inspection link below." : "Generating inspection QR code locally…"}</p>}{inspectionUrl && <a className="text-button" href={inspectionUrl} target="_blank" rel="noreferrer">Open inspection page</a>}<p className="footnote">The linked page works without a backend. Captures stay on that device. Run the demo capture here to complete this workbench review.</p></div>
      <DemoInspection apn={apn} onCapture={() => setCaptured(true)} />
    </div>}
    <div className="workbench-actions"><button className="primary-button" disabled={!captured} onClick={onVerify}><Check size={16} />Verify & restore auto-bind</button><button className="secondary-button" onClick={onLoading}>Apply structure loading (+35 bps LCR)</button></div>
    <p className="footnote" aria-live="polite">{captured ? "Simulated evidence is ready for underwriter approval. Restoring eligibility does not issue a policy." : "Run a demo capture before restoring auto-bind eligibility."} Loading assumes +240 sq ft at $250/sq ft and requires permit review.</p>
  </Modal>;
}
