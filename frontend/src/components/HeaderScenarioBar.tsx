"use client";

import { Activity, ArrowUpRight, Droplets, Flame, MapPin, Moon, Search, ShieldCheck, Sun } from "lucide-react";
import { useState } from "react";
import Link from "next/link";
import { goldenScenarios, scenarios } from "@/data/goldenScenarios";
import type { GoldenScenarioKey } from "@/types/resiliscore";

export function HeaderScenarioBar({ active, onSelect, onAddress, live, onLive, dark, onTheme, loading }: {
  active: GoldenScenarioKey | null; onSelect: (id: GoldenScenarioKey) => void; onAddress: (address: string) => void; live: boolean;
  onLive: (value: boolean) => void; dark: boolean; onTheme: () => void; loading: boolean;
}) {
  const [query, setQuery] = useState("");
  const matches = query.trim() ? scenarios.filter(s => {
    const p = goldenScenarios[s.id]?.parcel_identity;
    return `${s.title} ${s.address} ${s.location} ${p?.address ?? ""} ${p?.apn_uid ?? ""}`.toLowerCase().includes(query.toLowerCase().trim());
  }) : [];
  const icons = [Droplets, Flame, ShieldCheck, Droplets, Droplets, Droplets];
  function submitAddress() {
    if (!query.trim()) return;
    onAddress(query.trim()); setQuery("");
  }
  return <>
    <header className="topbar">
      <Link className="brand" href="/" aria-label="ResiliScore home"><span className="brand-mark"><Activity size={23} /></span>ResiliScore<span className="trademark">™</span></Link>
      <span className="brand-description">Property resilience<br /><strong>Underwriting copilot</strong></span>
      <div className="connection"><span className={`status-dot ${loading ? "loading" : ""}`} /><span>{live ? "Live API selected" : "Guidewire & MCP · Demo"}</span></div>
      <div className="header-actions"><label className="mode-switch"><input type="checkbox" checked={live} onChange={e => onLive(e.target.checked)} />Live API</label>
        <button className="icon-button" onClick={onTheme} aria-label={dark ? "Use light theme" : "Use dark theme"}>{dark ? <Sun size={18} /> : <Moon size={18} />}</button>
      </div>
    </header>
    <section className="scenario-section" aria-label="Parcel search and demo scenarios">
      <div className="search-heading"><div><h1>Underwriting workspace</h1><p>A closer look changes the risk.</p></div>
        <form className="search-wrap" onSubmit={e => { e.preventDefault(); submitAddress(); }}><Search size={17} /><input aria-label="Search address or APN" placeholder="Search a demo parcel or enter a live address" value={query} onChange={e => setQuery(e.target.value)} onKeyDown={e => { if (e.key === "Escape") setQuery(""); }} />
          {query && <div className="search-results">{matches.length ? matches.map(s => <button type="button" key={s.id} onClick={() => { onSelect(s.id); setQuery(""); }}><MapPin size={16} />{goldenScenarios[s.id]?.parcel_identity.address ?? `${s.address}, ${s.location}`}</button>) : <p>No matching demo parcel.</p>}<button type="submit"><Search size={16} />Look up “{query.trim()}” via Live API</button></div>}
        </form>
      </div>
      <div className="scenario-grid">{scenarios.map((s, i) => { const Icon = icons[i]; return <button key={s.id} className={`scenario-button ${active === s.id ? "selected" : ""}`} onClick={() => onSelect(s.id)} aria-pressed={active === s.id}>
        <Icon size={21} /><span><strong>{s.title}</strong><span>{s.location}</span><small>{s.id.startsWith("NYC_") ? `${s.address} · ` : ""}{s.summary}</small></span><ArrowUpRight size={17} className="scenario-arrow" />
      </button>; })}</div>
    </section>
  </>;
}
