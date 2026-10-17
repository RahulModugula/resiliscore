"use client";

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { UnderwritingWorkspace } from "@/components/UnderwritingWorkspace";
import { loadManhattanAssessment, propertyLabel, type ManhattanAssessment } from "@/lib/manhattan/assessment";

function AssessmentRoute() {
  const params = useSearchParams();
  const id = params.get("property");
  const demo = params.get("demo") === "true";
  const [loaded, setLoaded] = useState<{ id: string | null; result: ManhattanAssessment | null } | null>(null);
  useEffect(() => { setLoaded({ id, result: id ? loadManhattanAssessment(id) : null }); }, [id]);
  if (demo) return <UnderwritingWorkspace />;
  if (!loaded || loaded.id !== id) return <main className="app-shell main-content" data-theme="dark"><p role="status">Opening property assessment…</p></main>;
  const result = loaded.result;
  if (!result) return <main className="app-shell main-content" data-theme="dark"><section className="panel"><h1>Select a Manhattan property</h1><p>This assessment is missing or expired. Return to the map and select a building to run a new assessment.</p><Link className="primary-button" href="/">Back to Manhattan map</Link><p><Link href="/assessment?demo=true">Open the offline underwriting demo</Link></p></section></main>;
  return <UnderwritingWorkspace key={result.property.id} initialParcel={result.parcel} selectedProperty={{ id: result.property.id, label: propertyLabel(result.property), neighborhoodId: result.property.neighborhoodId }} assessmentSource={result.source} assessmentNotice={result.notice} />;
}

export default function AssessmentPage() {
  return <Suspense fallback={<main><p role="status">Opening assessment…</p></main>}><AssessmentRoute /></Suspense>;
}
