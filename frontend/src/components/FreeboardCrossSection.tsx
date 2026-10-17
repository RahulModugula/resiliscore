import { Droplets } from "lucide-react";
import type { PublicHazardLayer } from "@/types/resiliscore";

export function FreeboardCrossSection({ hazard: h }: { hazard: PublicHazardLayer }) {
  if (h.bfe_ft_navd88 === null) return <section className="panel hazard-summary"><div className="panel-heading"><h2>Local hazard context</h2><span className="subtle-label">FEMA Zone {h.fema_flood_zone}</span></div><dl className="metrics four"><div><dt>Fuel model</dt><dd>{h.landfire_fbfm40_code}</dd></div><div><dt>Terrain slope</dt><dd>{h.slope_deg}°</dd></div><div><dt>HAND elevation</dt><dd>{h.hand_rel_elev_ft} ft</dd></div><div><dt>100-year rainfall</dt><dd>{h.noaa_atlas15_p24h_100yr_in} in</dd></div></dl><p className="footnote">Base flood elevation unavailable. Freeboard is not inferred from a missing BFE.</p></section>;
  if (h.est_ffe_ft === null || h.usgs_lag_ft === null || h.freeboard_delta_h_ft === null) return <section className="panel hazard-summary"><div className="panel-heading"><h2>Local hazard context</h2><span className="subtle-label">FEMA Zone {h.fema_flood_zone}</span></div><dl className="metrics four"><div><dt>Fuel model</dt><dd>{h.landfire_fbfm40_code}</dd></div><div><dt>Terrain slope</dt><dd>{h.slope_deg}°</dd></div><div><dt>HAND elevation</dt><dd>{h.hand_rel_elev_ft} ft</dd></div><div><dt>100-year rainfall</dt><dd>{h.noaa_atlas15_p24h_100yr_in} in</dd></div></dl><p className="footnote">Elevation unavailable: first-floor height not verified. The score uses a documented default and is indicative only.</p></section>;
  const min = Math.min(h.usgs_lag_ft, h.bfe_ft_navd88, h.est_ffe_ft) - 1;
  const max = Math.max(h.usgs_lag_ft, h.bfe_ft_navd88, h.est_ffe_ft) + 5;
  const y = (ft: number) => 175 - (ft - min) / (max - min) * 145;
  const floor = y(h.est_ffe_ft), water = y(h.bfe_ft_navd88), ground = y(h.usgs_lag_ft);
  return <section className="panel freeboard"><div className="panel-heading"><h2><Droplets size={17} />The elevation advantage</h2><span className="badge success">+{h.freeboard_delta_h_ft.toFixed(1)} ft freeboard</span></div>
    <div className="elevation-layout"><svg viewBox="0 0 420 205" role="img" aria-label={`Estimated first floor elevation ${h.est_ffe_ft} feet, base flood elevation ${h.bfe_ft_navd88} feet, ground ${h.usgs_lag_ft} feet NAVD88. Freeboard ${h.freeboard_delta_h_ft} feet.`}>
      <rect x="25" y={water} width="370" height={ground-water} fill="var(--water)" opacity=".18" /><path d={`M25 ${water}H395`} stroke="var(--water)" strokeWidth="1.5" strokeDasharray="5 4" />
      <path d={`M25 ${ground}H395`} stroke="var(--muted)" /><path d={`M130 ${floor}V${ground}M240 ${floor}V${ground}`} stroke="var(--muted)" strokeWidth="5" />
      <path d={`M110 ${floor}V${floor-38}L185 ${floor-78}L260 ${floor-38}V${floor}Z`} fill="var(--surface-raised)" stroke="var(--text)" strokeWidth="2" /><path d={`M110 ${floor}H260`} stroke="var(--accent)" strokeWidth="3" />
      <path d={`M320 ${floor}V${water}M313 ${floor+6}L320 ${floor}L327 ${floor+6}M313 ${water-6}L320 ${water}L327 ${water-6}`} fill="none" stroke="var(--accent)" strokeWidth="2" />
    </svg><dl className="elevation-values"><div><dt>Estimated first floor</dt><dd>{h.est_ffe_ft.toFixed(1)} ft</dd></div><div><dt>FEMA base flood elevation</dt><dd>{h.bfe_ft_navd88.toFixed(1)} ft NAVD88</dd></div><div><dt>USGS bare-earth grade</dt><dd>{h.usgs_lag_ft.toFixed(1)} ft</dd></div></dl></div>
    <div className="cross-section-footer"><p>Estimated first floor above the modeled flood line.</p><span>NOAA 100-year / 24h rainfall <strong>{h.noaa_atlas15_p24h_100yr_in} in</strong></span></div>
    <p className="footnote">Illustrative USACE damage comparison: 49% at +4 ft inundation vs. &lt;2% with this freeboard. Rainfall depth is not a surge elevation.</p>
  </section>;
}
