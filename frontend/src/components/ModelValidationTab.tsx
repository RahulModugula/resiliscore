"use client";

import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { Activity, ArrowRight, Download, Info, Microscope } from "lucide-react";
import { validationReport } from "@/data/validationReport";
import { requestValidationReport } from "@/lib/validation";
import { downloadText } from "@/lib/download";
import type { FloodValidation, ValidationReport, WildfireValidation } from "@/types/validation";
import "./model-validation.css";

const number = (value: number, digits = 0) => value.toLocaleString("en-US", { maximumFractionDigits: digits });
const decimal = (value: number | null, digits = 3) => value === null ? "Not reported" : value.toFixed(digits);
const percent = (value: number) => `${number(value * 100, 1)}%`;
const signedPercent = (value: number) => `${value > 0 ? "+" : ""}${number(value * 100, 1)} pp`;
const date = (value: string) => new Intl.DateTimeFormat("en-US", { dateStyle: "medium", timeZone: "UTC" }).format(new Date(value));
const label = (value: string) => ({ roof_class_a: "Class A roof", enclosed_eaves: "Enclosed eaves", screened_vents: "Screened vents", noncombustible_siding: "Noncombustible siding", multipane_windows: "Multipane windows", no_wood_deck: "No wood deck", no_shed_within_30ft: "No shed within 30 ft", era_1980_2007: "Built 1980–2007", era_2008_plus: "Built 2008 or later" }[value] ?? value.replaceAll("_", " "));

function Source({ section }: { section: { data_source: string; fetched_on: string; data_vintage: string } }) {
  return <figcaption className="validation-source"><span>Source: {section.data_source}</span><span>Fetched <time dateTime={section.fetched_on}>{date(section.fetched_on)}</time> · {section.data_vintage}</span></figcaption>;
}

function Pending({ name }: { name: string }) {
  return <div className="validation-pending"><Microscope size={23} aria-hidden="true" /><div><h4>Results pending</h4><p>{name} results have not been published in this report.</p></div></div>;
}

function Note({ text }: { text: string }) {
  const id = useId();
  const [anchor, setAnchor] = useState<{ top: number; left: number; host: Element } | null>(null);
  const active = useRef({ hover: false, focus: false });
  const timer = useRef<number | null>(null);
  function cancelClose() { if (timer.current !== null) window.clearTimeout(timer.current); }
  function closeSoon() {
    cancelClose();
    timer.current = window.setTimeout(() => { if (!active.current.hover && !active.current.focus) setAnchor(null); }, 120);
  }
  function open(element: HTMLElement) {
    cancelClose();
    const rect = element.getBoundingClientRect();
    setAnchor({ top: Math.min(rect.bottom + 8, window.innerHeight * .6 - 8), left: Math.max(8, Math.min(rect.left, window.innerWidth - 260)), host: element.closest(".app-shell") ?? document.body });
  }
  useEffect(() => () => { if (timer.current !== null) window.clearTimeout(timer.current); }, []);
  return <span className="validation-note" tabIndex={0} aria-label="Result caveat" aria-describedby={anchor ? id : undefined}
    onMouseEnter={event => { active.current.hover = true; open(event.currentTarget); }}
    onFocus={event => { active.current.focus = true; open(event.currentTarget); }}
    onMouseLeave={() => { active.current.hover = false; closeSoon(); }} onBlur={() => { active.current.focus = false; closeSoon(); }} onKeyDown={event => { if (event.key === "Escape") { cancelClose(); setAnchor(null); } }}>
    <Info size={13} />{anchor && createPortal(<span role="tooltip" id={id} tabIndex={0} className="validation-tooltip" style={{ top: anchor.top, left: anchor.left }}
      onMouseEnter={() => { active.current.hover = true; cancelClose(); }} onMouseLeave={() => { active.current.hover = false; closeSoon(); }}
      onFocus={() => { active.current.focus = true; cancelClose(); }} onBlur={() => { active.current.focus = false; closeSoon(); }}
      onKeyDown={event => { if (event.key === "Escape") { cancelClose(); setAnchor(null); } }}>{text}</span>, anchor.host)}
  </span>;
}

function Verdict({ section }: { section: FloodValidation | WildfireValidation }) {
  return <div className="validation-verdict"><div className="validation-verdict-heading"><h3>Validation verdict</h3><span className={`badge ${section.adopted ? "success" : "warning"}`}>{section.adopted ? "Adopted" : "Not adopted"}</span></div><p>{section.verdict}</p>{section.adoption_note !== null && <p className="validation-adoption">{section.adoption_note}</p>}<details className="validation-method"><summary>Method & limitations</summary><p>{section.method}</p></details></div>;
}

function Legend({ children }: { children: ReactNode }) {
  return <div className="validation-legend">{children}</div>;
}

function ForestPlot({ section }: { section: WildfireValidation }) {
  const features = section.features;
  const roof = features.find(feature => feature.feature === "roof_class_a");
  const reduction = roof ? (1 - roof.odds_ratio) * 100 : null;
  const title = reduction !== null && reduction > 0 ? `Class A roof cuts destruction odds ${number(reduction)}%` : "Hardening and destruction odds";
  const values = features.flatMap(feature => [feature.ci_low, feature.ci_high, feature.odds_ratio, feature.model_implied_ratio]).filter((value): value is number => value !== null && value > 0);
  const low = Math.min(1, ...values) / 1.15;
  const high = Math.max(1, ...values) * 1.15;
  const x = (value: number) => (Math.log(value) - Math.log(low)) / (Math.log(high) - Math.log(low)) * 100;
  const ticks = [...new Set([low, Math.sqrt(low), 1, Math.sqrt(high), high])].sort((a, b) => a - b);
  return <article className="panel validation-panel"><div className="validation-chart-heading"><h3>{title}</h3><p>Fire-adjusted odds ratios. A value below unity indicates lower destruction odds.</p></div>
    {!features.length ? <Pending name="Hardening feature" /> : <figure><Legend><span><i className="legend-dot observed" />Fitted odds ratio & 95% CI</span><span><i className="legend-dot hollow" />Model-implied ratio</span></Legend>
      <p className="validation-scroll-hint">Scroll horizontally to compare all values.</p>
      <div className="validation-scroll" role="region" aria-label="Hardening odds ratio chart" tabIndex={0}><div className="validation-forest">
        <div className="validation-plot-row validation-plot-header"><span>Hardening feature / n</span><span>Odds ratio · log scale</span><span>Estimate [95% CI]</span></div>
        {features.map(feature => <div className="validation-plot-row" key={feature.feature}><div className="validation-row-label"><strong>{label(feature.feature)}</strong><small>n = {number(feature.n)} · {feature.supported ? "Supported" : "Not supported"}</small></div>
          <svg role="img" aria-label={`${label(feature.feature)} odds ratio ${feature.odds_ratio}, confidence interval ${feature.ci_low} to ${feature.ci_high}, model-implied ${decimal(feature.model_implied_ratio)}`}>
            <line x1={`${x(1)}%`} x2={`${x(1)}%`} y1="0" y2="32" className="validation-reference" />
            <g className={feature.supported ? "validation-observed" : "validation-unsupported"}><line x1={`${x(feature.ci_low)}%`} x2={`${x(feature.ci_high)}%`} y1="16" y2="16" /><line x1={`${x(feature.ci_low)}%`} x2={`${x(feature.ci_low)}%`} y1="11" y2="21" /><line x1={`${x(feature.ci_high)}%`} x2={`${x(feature.ci_high)}%`} y1="11" y2="21" /></g>
            <circle cx={`${x(feature.odds_ratio)}%`} cy="16" r="3.5" className={feature.supported ? "validation-observed-dot" : "validation-unsupported-dot"} />
            {feature.model_implied_ratio !== null && <circle cx={`${x(feature.model_implied_ratio)}%`} cy="16" r="3.5" className="validation-model-dot" />}
          </svg><span className="validation-estimate">{decimal(feature.odds_ratio, 2)} <small>[{decimal(feature.ci_low, 2)}, {decimal(feature.ci_high, 2)}]</small></span></div>)}
        <div className="validation-plot-row validation-axis-row"><span /><div className="validation-axis">{ticks.map(tick => <span key={tick} style={{ left: `${x(tick)}%` }}>{decimal(tick, 2)}</span>)}</div><span /></div>
      </div></div><Source section={section} /></figure>}
  </article>;
}

function FirePlot({ section }: { section: WildfireValidation }) {
  const fires = [...section.fires].sort((a, b) => b.n_structures - a.n_structures);
  return <article className="panel validation-panel"><div className="validation-chart-heading"><h3>Fire-by-fire backtest</h3><p>Leave-one-fire-out AUC · sorted by inspected structures, largest first.</p></div>
    {!fires.length ? <Pending name="Fire backtest" /> : <figure><Legend><span><i className="legend-dot current" />Current</span><span><i className="legend-dot observed" />Fitted</span><span>Higher AUC is better</span></Legend>
      <p className="validation-scroll-hint">Scroll horizontally to compare all values. Scroll down for every fire.</p>
      <div className="validation-scroll validation-fire-scroll" role="region" aria-label="Fire-by-fire AUC chart" tabIndex={0}><div className="validation-fires">
        <div className="validation-plot-row validation-plot-header"><span>Fire / inspected n</span><span>AUC</span><span>Current / fitted</span></div>
        {fires.map(fire => <div key={`${fire.fire}-${fire.year}`} className="validation-plot-row"><div className="validation-row-label"><strong>{fire.fire} <small>{fire.year}</small></strong><small>n = {number(fire.n_structures)} {fire.note && <Note text={fire.note} />}</small></div>
          <svg role="img" aria-label={`${fire.fire}: current AUC ${fire.auc_current}, fitted AUC ${decimal(fire.auc_fitted)}`}>
            <line x1="50%" x2="50%" y1="0" y2="32" className="validation-reference" />
            {fire.auc_fitted !== null && <line x1={`${fire.auc_current * 100}%`} x2={`${fire.auc_fitted * 100}%`} y1="16" y2="16" className="validation-connector" />}
            <circle cx={`${fire.auc_current * 100}%`} cy="16" r="3.5" className="validation-current-dot" />
            {fire.auc_fitted !== null && <circle cx={`${fire.auc_fitted * 100}%`} cy="16" r="3.5" className="validation-observed-dot" />}
          </svg><span className="validation-estimate">{decimal(fire.auc_current)} / {fire.auc_fitted === null ? "Pending" : decimal(fire.auc_fitted)}</span></div>)}
        <div className="validation-plot-row validation-axis-row"><span /><div className="validation-axis">{[0, .25, .5, .75, 1].map(tick => <span key={tick} style={{ left: `${tick * 100}%` }}>{decimal(tick, 2)}</span>)}</div><span /></div>
      </div></div><Source section={section} /></figure>}
  </article>;
}

function FloodCurve({ section }: { section: FloodValidation }) {
  const buckets = [...section.severity_by_depth].sort((a, b) => a.depth_mid_ft - b.depth_mid_ft);
  const minDepth = Math.min(0, ...buckets.map(bucket => bucket.depth_mid_ft));
  const maxDepth = Math.max(...buckets.map(bucket => bucket.depth_mid_ft));
  const maxDamage = Math.max(...buckets.flatMap(bucket => [bucket.observed_ci_high, bucket.hazus_pred_dr, bucket.fitted_pred_dr ?? 0]));
  const x = (depth: number) => 62 + (depth - minDepth) / (maxDepth - minDepth || 1) * 520;
  const y = (damage: number) => 270 - damage / (maxDamage || 1) * 238;
  const line = (key: "hazus_pred_dr" | "fitted_pred_dr") => {
    let penDown = false;
    return buckets.map(bucket => {
      const value = bucket[key];
      if (value === null) { penDown = false; return ""; }
      const segment = `${penDown ? "L" : "M"}${x(bucket.depth_mid_ft)},${y(value)}`;
      penDown = true;
      return segment;
    }).join(" ");
  };
  return <article className="panel validation-panel"><div className="validation-chart-heading"><h3>Flood damage curve</h3><p>Observed damage ratio against depth above the first floor.</p></div>
    {!buckets.length ? <Pending name="Flood severity" /> : <figure><Legend><span><i className="legend-dot observed" />Observed & 95% CI</span><span><i className="legend-line" />Hazus</span><span><i className="legend-line fitted" />Fitted</span></Legend>
      <p className="validation-scroll-hint">Scroll horizontally to inspect every depth and confidence interval.</p>
      <div className="validation-scroll" role="region" aria-label="Flood damage curve" tabIndex={0}><svg className="validation-flood-chart" viewBox="0 0 610 330" role="img" aria-label="Flood damage ratio by depth, with observed confidence intervals and Hazus and fitted curves">
        <text x="62" y="14" className="validation-svg-label">Mean damage ratio</text>
        {Array.from({ length: 5 }, (_, index) => maxDamage * index / 4).map((tick, index) => <g key={index}><line x1="62" x2="582" y1={y(tick)} y2={y(tick)} className="validation-gridline" /><text x="49" y={y(tick) + 4} textAnchor="end" className="validation-svg-label">{percent(tick)}</text></g>)}
        <path d={line("hazus_pred_dr")} className="validation-hazus-line" /><path d={line("fitted_pred_dr")} className="validation-fitted-line" />
        {buckets.filter(bucket => bucket.fitted_pred_dr !== null).map(bucket => <rect key={bucket.depth_bucket} x={x(bucket.depth_mid_ft) - 3} y={y(bucket.fitted_pred_dr!) - 3} width="6" height="6" className="validation-fitted-point"><title>{`${bucket.depth_bucket} ft · fitted ${percent(bucket.fitted_pred_dr!)}`}</title></rect>)}
        {buckets.map(bucket => <g key={bucket.depth_bucket}><title>{`${bucket.depth_bucket} ft · n = ${number(bucket.n)} · observed ${percent(bucket.observed_mean_dr)} [${percent(bucket.observed_ci_low)}, ${percent(bucket.observed_ci_high)}] · Hazus ${percent(bucket.hazus_pred_dr)} · fitted ${bucket.fitted_pred_dr === null ? "not reported" : percent(bucket.fitted_pred_dr)}`}</title><line x1={x(bucket.depth_mid_ft)} x2={x(bucket.depth_mid_ft)} y1={y(bucket.observed_ci_low)} y2={y(bucket.observed_ci_high)} className="validation-observed" />{[bucket.observed_ci_low, bucket.observed_ci_high].map((bound, index) => <line key={index} x1={x(bucket.depth_mid_ft) - 4} x2={x(bucket.depth_mid_ft) + 4} y1={y(bound)} y2={y(bound)} className="validation-observed" />)}<circle cx={x(bucket.depth_mid_ft)} cy={y(bucket.observed_mean_dr)} r="4" className="validation-observed-dot" /><text x={x(bucket.depth_mid_ft)} y="291" textAnchor="middle" className="validation-svg-label">{number(bucket.depth_mid_ft, 2)}</text></g>)}
        <text x="322" y="320" textAnchor="middle" className="validation-svg-label">Depth above first floor (ft)</text>
      </svg></div><details className="validation-data-details"><summary>Inspect depth bucket data</summary><div className="validation-scroll"><table className="validation-table"><caption className="sr-only">Flood severity by depth</caption><thead><tr><th>Depth (ft)</th><th>Claims</th><th>Observed [95% CI]</th><th>Hazus</th><th>Fitted</th></tr></thead><tbody>{buckets.map(bucket => <tr key={bucket.depth_bucket}><th scope="row">{bucket.depth_bucket}</th><td>{number(bucket.n)}</td><td>{percent(bucket.observed_mean_dr)} [{percent(bucket.observed_ci_low)}, {percent(bucket.observed_ci_high)}]</td><td>{percent(bucket.hazus_pred_dr)}</td><td>{bucket.fitted_pred_dr === null ? "Not reported" : percent(bucket.fitted_pred_dr)}</td></tr>)}</tbody></table></div></details><Source section={section} /></figure>}
  </article>;
}

function HurricaneTable({ section }: { section: FloodValidation }) {
  return <article className="panel validation-panel"><div className="validation-chart-heading"><h3>Hurricane backtest</h3><p>Mean damage ratios · bias = Hazus prediction minus observed.</p></div>
    {!section.events.length ? <Pending name="Hurricane event" /> : <figure><p className="validation-scroll-hint">Scroll horizontally to compare all values.</p><div className="validation-scroll" role="region" aria-label="Hurricane backtest table" tabIndex={0}><table className="validation-table"><caption className="sr-only">Hurricane claims and Hazus bias</caption><thead><tr><th>Event</th><th>Year</th><th>Claims</th><th>Observed</th><th>Hazus</th><th>Bias</th></tr></thead><tbody>{section.events.map(event => <tr key={`${event.event}-${event.year}`}><th scope="row"><span className="validation-event-name">{event.event}{event.note && <Note text={event.note} />}</span><small>{event.states.join(", ")}</small></th><td>{event.year}</td><td>{number(event.n_claims)}</td><td>{percent(event.observed_mean_dr)}</td><td>{percent(event.observed_mean_dr + event.bias)}</td><td className={`validation-bias ${event.bias < 0 ? "under" : event.bias > 0 ? "over" : "neutral"}`}>{signedPercent(event.bias)}<small>{event.bias < 0 ? "Underpredicts" : event.bias > 0 ? "Overpredicts" : "Unbiased"}</small></td></tr>)}</tbody></table></div><Source section={section} /></figure>}
  </article>;
}

function Performance({ report }: { report: ValidationReport }) {
  return <section className="panel validation-panel"><div className="validation-chart-heading"><h3>Performance</h3><p>Measured endpoint latency and throughput. Concurrency is shown per run.</p></div>
    {!report.benchmarks.length ? <Pending name="Benchmark" /> : <><p className="validation-scroll-hint">Scroll horizontally to compare all values.</p><div className="validation-scroll" role="region" aria-label="Performance benchmarks" tabIndex={0}><table className="validation-table"><caption className="sr-only">Latency percentiles and requests per second</caption><thead><tr><th>Benchmark</th><th>n</th><th>Concurrency</th><th>p50 (ms)</th><th>p95 (ms)</th><th>p99 (ms)</th><th>req/s</th></tr></thead><tbody>{report.benchmarks.map((row, index) => <tr key={`${row.name}-${index}`}><th scope="row">{row.name}</th><td>{number(row.n)}</td><td>{row.concurrency === null ? "Not reported" : number(row.concurrency)}</td><td>{number(row.p50_ms, 2)}</td><td>{number(row.p95_ms, 2)}</td><td>{number(row.p99_ms, 2)}</td><td>{row.rps === null ? "Not reported" : number(row.rps, 2)}</td></tr>)}</tbody></table></div></>}
    <p className="validation-source">Source: model validation benchmark runs · Report generated <time dateTime={report.generated_at}>{date(report.generated_at)}</time></p>
  </section>;
}

export function ModelValidationTab({ live = false }: { live?: boolean }) {
  const [remote, setRemote] = useState<ValidationReport | null>(null);
  const [status, setStatus] = useState("Showing the bundled validation report. Available offline.");
  const [loading, setLoading] = useState(false);
  const [holdout, setHoldout] = useState("");
  useEffect(() => {
    setRemote(null);
    if (!live) { setStatus("Showing the bundled validation report. Available offline."); setLoading(false); return; }
    const controller = new AbortController();
    setLoading(true);
    setStatus("Loading live validation results. The bundled report remains available.");
    requestValidationReport(controller.signal).then(report => {
      if (!controller.signal.aborted) { setRemote(report); setStatus("Live validation report checked against the shared contract."); }
    }).catch(error => {
      if (!controller.signal.aborted) setStatus(`${error instanceof Error ? error.message : "Validation API unavailable"}. Showing the bundled validation report.`);
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [live]);
  const report = live && remote ? remote : validationReport;
  const wildfire = report.wildfire;
  const flood = report.flood;
  const fires = [...(wildfire?.fires ?? [])].sort((a, b) => b.n_structures - a.n_structures);
  const selectedFire = fires.find(fire => `${fire.fire}-${fire.year}` === holdout) ?? fires[0];
  const claims = flood?.severity_by_depth.reduce((sum, bucket) => sum + bucket.n, 0);
  const p95 = report.benchmarks.length ? Math.max(...report.benchmarks.map(row => row.p95_ms)) : null;
  return <div className="model-validation" aria-busy={loading}>
    <header className="validation-heading"><div><h2>Model Validation</h2><p>Measured against real outcomes. Every result, including what we chose not to adopt.</p></div><div className="validation-heading-actions"><span className={`badge ${report.status === "COMPLETE" ? "success" : "warning"}`}>{report.status.toLowerCase()} report</span><button className="secondary-button" onClick={() => downloadText("model-validation-report.json", JSON.stringify(report, null, 2))}><Download size={15} />Download report</button></div></header>
    <div className="validation-report-meta"><span><Activity size={14} />{live && remote ? "Live report" : "Offline snapshot"}</span><span>Model <code>{report.model_commit}</code></span><span>Generated <time dateTime={report.generated_at}>{date(report.generated_at)}</time></span><span>Schema {report.schema_version}</span></div>
    <p className={`validation-network ${live && !remote && !loading ? "warning" : ""}`} role="status">{status}</p>
    <dl className="validation-kpis">
      <div><dt>Wildfire holdout AUC</dt><dd>{selectedFire ? <><span>{decimal(selectedFire.auc_current)}</span><ArrowRight size={16} aria-label="versus" /><span className="validation-accent">{selectedFire.auc_fitted === null ? "Pending" : decimal(selectedFire.auc_fitted)}</span></> : "Results pending"}</dd><small>Current / fitted</small>{selectedFire && <select aria-label="Wildfire holdout fire" value={`${selectedFire.fire}-${selectedFire.year}`} onChange={event => setHoldout(event.target.value)}>{fires.map(fire => <option key={`${fire.fire}-${fire.year}`} value={`${fire.fire}-${fire.year}`}>{fire.fire} · {fire.year}</option>)}</select>}</div>
      <div><dt>Flood claims tested</dt><dd>{claims === undefined || !flood?.severity_by_depth.length ? "Results pending" : number(claims)}</dd><small>Claims in severity depth buckets</small></div>
      <div><dt>Events & cohorts backtested</dt><dd>{wildfire || flood ? number(fires.length + (flood?.events.length ?? 0)) : "Results pending"}</dd><small>{wildfire ? `${number(fires.length)} fires` : "Fires pending"} · {flood ? `${number(flood.events.length)} flood cohorts` : "Flood events pending"}</small></div>
      <div><dt>Constants validated / total</dt><dd>{number(report.model_card.constants_validated)}<span className="validation-kpi-divider">/ {number(report.model_card.constants_total)}</span></dd><small>{number(report.model_card.constants_calibration)} calibration constants · {report.model_card.perils.join(", ")}</small></div>
      <div><dt>p95 latency</dt><dd>{p95 === null ? "Results pending" : <>{number(p95, 2)}<span className="validation-kpi-unit">ms</span></>}</dd><small>Slowest reported benchmark p95</small></div>
    </dl>
    <section className="validation-section" aria-labelledby="validation-wildfire-title"><div className="validation-section-heading"><h2 id="validation-wildfire-title">Wildfire</h2><span>Hardening evidence & out-of-fire generalization</span></div>{wildfire ? <><Verdict section={wildfire} /><div className="validation-chart-grid"><ForestPlot section={wildfire} /><FirePlot section={wildfire} /></div></> : <div className="panel"><Pending name="Wildfire validation" /></div>}</section>
    <section className="validation-section" aria-labelledby="validation-flood-title"><div className="validation-section-heading"><h2 id="validation-flood-title">Flood</h2><span>Depth-damage calibration & event backtests</span></div>{flood ? <><Verdict section={flood} /><div className="validation-chart-grid"><FloodCurve section={flood} /><HurricaneTable section={flood} /></div></> : <div className="panel"><Pending name="Flood validation" /></div>}</section>
    <Performance report={report} />
    <details className="validation-references"><summary>Model card sources <span>{number(report.model_card.sources.length)} references</span></summary><ul>{report.model_card.sources.map((source, index) => <li key={`${source.url}-${index}`}><strong>{source.name}</strong><a href={source.url} target="_blank" rel="noreferrer">{source.url}</a><time dateTime={source.vintage}>{source.vintage}</time></li>)}</ul></details>
  </div>;
}
