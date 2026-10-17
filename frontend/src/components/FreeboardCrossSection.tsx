import { Droplets } from "lucide-react";
import type { PublicHazardLayer } from "@/types/resiliscore";

export function FreeboardCrossSection({ hazard: h }: { hazard: PublicHazardLayer }) {
  if (h.bfe_ft_navd88 === null) return <section className="panel hazard-summary"><div className="panel-heading"><h2>Local hazard context</h2><span className="subtle-label">FEMA Zone {h.fema_flood_zone}</span></div><dl className="metrics four"><div><dt>Fuel model</dt><dd>{h.landfire_fbfm40_code}</dd></div><div><dt>Terrain slope</dt><dd>{h.slope_deg}°</dd></div><div><dt>HAND elevation</dt><dd>{h.hand_rel_elev_ft} ft</dd></div><div><dt>100-year rainfall</dt><dd>{h.noaa_atlas15_p24h_100yr_in} in</dd></div></dl><p className="footnote">Base flood elevation unavailable. Freeboard is not inferred from a missing BFE.</p></section>;
  const min = Math.min(h.usgs_lag_ft, h.bfe_ft_navd88, h.est_ffe_ft) - 1;
  const max = Math.max(h.usgs_lag_ft, h.bfe_ft_navd88, h.est_ffe_ft) + 3;
  const y = (ft: number) => 175 - (ft - min) / (max - min) * 145;
  const floor = y(h.est_ffe_ft), water = y(h.bfe_ft_navd88), ground = y(h.usgs_lag_ft);
  return <section className="panel freeboard"><div className="panel-heading"><h2><Droplets size={17} />The elevation advantage</h2><span className="badge success">+{h.freeboard_delta_h_ft.toFixed(1)} ft freeboard</span></div>
    <svg viewBox="0 0 720 205" role="img" aria-label={`First floor elevation ${h.est_ffe_ft} feet, base flood elevation ${h.bfe_ft_navd88} feet, ground ${h.usgs_lag_ft} feet NAVD88. Freeboard ${h.freeboard_delta_h_ft} feet.`}>
      <rect x="40" y={water} width="640" height={ground-water} fill="var(--water)" opacity=".18" /><path d={`M40 ${water}H680`} stroke="var(--water)" strokeWidth="1.5" strokeDasharray="5 4" />
      <path d={`M40 ${ground}H680`} stroke="var(--muted)" /><path d={`M170 ${floor}V${ground}M300 ${floor}V${ground}`} stroke="var(--muted)" strokeWidth="5" />
      <path d={`M145 ${floor}V${floor-38}L235 ${floor-78}L325 ${floor-38}V${floor}Z`} fill="var(--surface-raised)" stroke="var(--text)" strokeWidth="2" /><path d={`M145 ${floor}H325`} stroke="var(--accent)" strokeWidth="3" />
      <path d={`M375 ${floor}V${water}M368 ${floor+6}L375 ${floor}L382 ${floor+6}M368 ${water-6}L375 ${water}L382 ${water-6}`} fill="none" stroke="var(--accent)" strokeWidth="2" />
      <text x="420" y={floor+4} fill="var(--accent)">First floor · {h.est_ffe_ft.toFixed(1)} ft</text><text x="420" y={water+4} fill="var(--water)">FEMA BFE · {h.bfe_ft_navd88.toFixed(1)} ft NAVD88</text><text x="420" y={ground+19} fill="var(--muted)">Bare earth · {h.usgs_lag_ft.toFixed(1)} ft</text>
    </svg>
    <div className="cross-section-footer"><p>USGS 3DEP first floor above the modeled flood line.</p><span>NOAA 100-year / 24h rainfall <strong>{h.noaa_atlas15_p24h_100yr_in} in</strong></span></div>
    <p className="footnote">Illustrative USACE damage comparison: 49% at +4 ft inundation vs. &lt;2% with this freeboard. Rainfall depth is not a surge elevation.</p>
  </section>;
}
