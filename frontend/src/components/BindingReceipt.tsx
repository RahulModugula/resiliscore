"use client";

import { Download, ShieldCheck } from "lucide-react";
import { Modal } from "./Modal";
import type { ParcelScoreResponse } from "@/types/resiliscore";
import { downloadText } from "@/lib/download";
import { money } from "@/lib/format";

export function BindingReceipt({ parcel, selected, onClose }: { parcel: ParcelScoreResponse; selected: string[]; onClose: () => void }) {
  const conditional = parcel.actuarial_breakdown.underwriting_tier === "TIER_2_CONDITIONAL";
  const receipt = {
    demo: true, status: conditional ? "CONDITIONAL_60_DAY" : "DEMO_ISSUED",
    policy_number: `DEMO-${parcel.parcel_identity.state}-${parcel.parcel_identity.apn_uid.slice(-7)}`,
    idm_document_id: `DEMO-IDM-${parcel.request_id}`,
    submission_id: parcel.request_id, apn_uid: parcel.parcel_identity.apn_uid,
    ResiliScore_Ext: { score: parcel.actuarial_breakdown.resili_score, posterior_lcr: parcel.actuarial_breakdown.posterior_lcr, credibility_z: parcel.actuarial_breakdown.credibility_weight_z },
    annual_premium_usd: parcel.actuarial_breakdown.annual_discounted_premium_usd,
    applied_rule_ids: parcel.parcel_identity.state === "LA" ? ["LA_FORTIFIED_ROOF_CREDIT"] : ["CA_CCR_2644_9_CAT_B1_B2"],
    action_plan: selected, review_due_days: conditional ? 60 : null,
  };
  return <Modal title="Guidewire PolicyCenter receipt" onClose={onClose}><div className="receipt-status"><ShieldCheck size={30} /><div><h3>{conditional ? "Conditional bind prepared" : "Demo policy issued"}</h3><p>{receipt.policy_number}</p></div></div><p className="notice">Simulated PolicyCenter and IDM response. No policy has been purchased or sent to Guidewire.</p><dl className="metrics"><div><dt>Annual premium</dt><dd>{money(receipt.annual_premium_usd)}</dd></div><div><dt>ResiliScore</dt><dd>{receipt.ResiliScore_Ext.score}</dd></div></dl><pre className="json-receipt">{JSON.stringify(receipt, null, 2)}</pre><button className="primary-button" onClick={() => downloadText(`${receipt.policy_number}.json`, JSON.stringify(receipt, null, 2))}><Download size={16} />Download IDM receipt</button></Modal>;
}
