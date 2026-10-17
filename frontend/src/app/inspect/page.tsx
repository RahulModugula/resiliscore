import Link from "next/link";
import { DemoInspection } from "@/components/HitlWorkbenchModal";
import { goldenScenarios } from "@/data/goldenScenarios";

export default async function InspectionPage({ searchParams }: { searchParams: Promise<{ apn?: string | string[] }> }) {
  const params = await searchParams;
  const apn = typeof params.apn === "string" ? params.apn : "";
  const parcel = Object.values(goldenScenarios).find(item => item.parcel_identity.apn_uid === apn);
  return <main className="inspection-page"><Link className="text-button" href="/">← Back to underwriting cockpit</Link><h1>Property self-inspection</h1><p className="notice">Offline demo. This page does not submit evidence to an insurer or connect to phone sensors.</p>{parcel ? <><h2>{parcel.parcel_identity.address}</h2><DemoInspection apn={apn} /><p className="footnote">Capture results stay on this page. Return to the review workbench and run its demo capture to resolve the alert.</p></> : <section className="panel"><h2>Parcel not found</h2><p>Open this page using the QR code or inspection link in the human review workbench.</p></section>}</main>;
}
