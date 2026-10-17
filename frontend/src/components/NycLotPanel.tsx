import type { NycLayer } from "@/types/resiliscore";

const number = (value: number | null, unit = "") => value == null ? "No data" : `${value.toLocaleString("en-US")}${unit}`;
const count = (value: number | null) => value === 0 ? "None reported" : number(value);

export function NycLotPanel({ nyc }: { nyc?: NycLayer | null }) {
  if (!nyc) return null;
  const rows = [
    ["BBL", nyc.bbl || "No data"],
    ["Basement type", ({ FULL: "Full", PARTIAL: "Partial", NONE: "None", UNKNOWN: "No data" })[nyc.basement_type] ?? "No data"],
    ["Ground elevation", number(nyc.ground_elevation_ft, " ft")],
    ["Sandy-inundated", nyc.sandy_inundated == null ? "No data" : nyc.sandy_inundated ? "Yes" : "No"],
    ["Hurricane evacuation zone", nyc.evacuation_zone ?? "No data"],
    ["FloodNet max depth", number(nyc.floodnet_max_depth_in, " in")],
    ["311 sewer backups · 500 m / 5 years", count(nyc.sewer_backup_311_500m_5y)],
    ["311 street flooding · 500 m / 5 years", count(nyc.street_flooding_311_500m_5y)],
    ["Catch basins · within 150 m", count(nyc.catch_basins_150m)],
    ["DOB open violations", count(nyc.dob_open_violations)],
  ];
  return <section className="panel nyc-lot-panel" aria-labelledby="nyc-lot-heading">
    <div className="panel-heading"><h2 id="nyc-lot-heading">NYC Lot</h2></div>
    <dl className="lot-evidence">{rows.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
    <p className="footnote">No data means the source did not supply a value. Nearby reports describe the neighborhood, not confirmed damage to this lot.</p>
  </section>;
}
