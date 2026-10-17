"use client";

import { Activity, ArrowUpRight, Droplets, Flame, MapPin, Moon, Search, ShieldCheck, Sun } from "lucide-react";
import { useState } from "react";
import { goldenScenarios, scenarios } from "@/data/goldenScenarios";
import type { GoldenScenarioKey } from "@/types/resiliscore";

export function HeaderScenarioBar({ active, onSelect, live, onLive, dark, onTheme, loading }: {
  active: GoldenScenarioKey; onSelect: (id: GoldenScenarioKey) => void; live: boolean;
  onLive: (value: boolean) => void; dark: boolean; onTheme: () => void; loading: boolean;
}) {
  const [query, setQuery] = useState("");
  const matches = query.trim() ? scenarios.filter(s => {
    const p = goldenScenarios[s.id].parcel_identity;
    return `${p.address} ${p.apn_uid}`.toLowerCase().includes(query.toLowerCase().trim());
  }) : [];
  const icons = [Droplets, Flame, ShieldCheck];
  return <>
    <header className="topbar">
      <a className="brand" href="/" aria-label="ResiliScore home"><span className="brand-mark"><Activity size={23} /></span>ResiliScore<span className="trademark">™</span></a>
      <span className="brand-description">Property resilience<br /><strong>Underwriting copilot</strong></span>
      <div className="connection"><span className={`status-dot ${loading ? "loading" : ""}`} /><span>{live ? "Live API selected" : "Guidewire & MCP · Demo"}</span></div>
      <div className="header-actions"><label className="mode-switch"><input type="checkbox" checked={live} onChange={e => onLive(e.target.checked)} />Live API</label>
        <button className="icon-button" onClick={onTheme} aria-label={dark ? "Use light theme" : "Use dark theme"}>{dark ? <Sun size={18} /> : <Moon size={18} />}</button>
      </div>
    </header>
    <section className="scenario-section" aria-label="Parcel search and demo scenarios">
      <div className="search-heading"><div><h1>Underwriting workspace</h1><p>A closer look changes the risk.</p></div>
        <div className="search-wrap"><Search size={17} /><input aria-label="Search address or APN" placeholder="Find a demo address or 14-digit APN" value={query} onChange={e => setQuery(e.target.value)} />
          {query && <div className="search-results">{matches.length ? matches.map(s => <button key={s.id} onClick={() => { onSelect(s.id); setQuery(""); }}><MapPin size={16} />{goldenScenarios[s.id].parcel_identity.address}</button>) : <p>No demo parcel found. Search Bayou, Canyon, Dixon, or an APN.</p>}</div>}
        </div>
      </div>
      <div className="scenario-grid">{scenarios.map((s, i) => { const Icon = icons[i]; return <button key={s.id} className={`scenario-button ${active === s.id ? "selected" : ""}`} onClick={() => onSelect(s.id)} aria-pressed={active === s.id}>
        <Icon size={21} /><span><strong>{s.title}</strong><span>{s.location}</span><small>{s.summary}</small></span><ArrowUpRight size={17} className="scenario-arrow" />
      </button>; })}</div>
    </section>
  </>;
}
