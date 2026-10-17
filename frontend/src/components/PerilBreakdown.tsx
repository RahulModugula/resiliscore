import type { PerilSplit } from "@/types/resiliscore";
import { money, perilLabel } from "@/lib/format";

export function PerilBreakdown({ perils }: { perils: PerilSplit[] }) {
  return <dl className="peril-split" aria-label="Expected annual loss by peril">{perils.map(item => <div key={item.peril}><dt>{perilLabel(item.peril)}</dt><dd>{money(item.peril_aal_usd)} / yr</dd></div>)}</dl>;
}
