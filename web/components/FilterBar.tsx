"use client";
import { useEffect, useRef, useState } from "react";
import { CATEGORIES, VIBES } from "@/lib/vocab";
import { useTheme } from "./ThemeShell";

export type Filters = { vibes: string[]; category: string | null; neighborhood: string | null; goodFor: string | null };

function MoodMenu({ value, onChange }: { value: string[]; onChange: (v: string[]) => void }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const h = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", h); return () => document.removeEventListener("mousedown", h);
  }, []);
  const toggle = (t: string) => onChange(value.includes(t) ? value.filter((x) => x !== t) : [...value, t]);
  return (
    <div className="menu" ref={ref}>
      <button className={`control${value.length ? " active" : ""}`} onClick={() => setOpen((o) => !o)}>
        Mood{value.length ? <span className="count">{value.length}</span> : null} <span className="caret">▾</span>
      </button>
      {open && (
        <div className="popover">
          <div className="popover-head"><span>Venues must match every mood you tick</span>{value.length > 0 && <button className="link" onClick={() => onChange([])}>clear</button>}</div>
          <div className="popover-grid">
            {VIBES.map((t) => (
              <label key={t} className={`opt${value.includes(t) ? " on" : ""}`}>
                <input type="checkbox" checked={value.includes(t)} onChange={() => toggle(t)} /> {t}
              </label>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export function FilterBar({ filters, onChange, neighborhoods, goodFors, counts }: {
  filters: Filters; onChange: (f: Filters) => void; neighborhoods: string[]; goodFors: string[];
  counts: { venues: number; insight: number; results: number };
}) {
  const { mode, toggle } = useTheme();
  const sel = (v: string) => (v === "" ? null : v);
  const active = filters.vibes.length + (filters.category ? 1 : 0) + (filters.neighborhood ? 1 : 0) + (filters.goodFor ? 1 : 0);
  return (
    <div className="toolbar">
      <span className="brand">Venue Insight Explorer</span>
      <MoodMenu value={filters.vibes} onChange={(vibes) => onChange({ ...filters, vibes })} />
      <label className="field"><span>Type</span>
        <select value={filters.category ?? ""} onChange={(e) => onChange({ ...filters, category: sel(e.target.value) })}>
          <option value="">Any</option>{CATEGORIES.map((c) => <option key={c} value={c}>{c.replace("_", " ")}</option>)}
        </select></label>
      <label className="field"><span>Neighborhood</span>
        <select value={filters.neighborhood ?? ""} onChange={(e) => onChange({ ...filters, neighborhood: sel(e.target.value) })}>
          <option value="">Any</option>{neighborhoods.map((n) => <option key={n} value={n}>{n}</option>)}
        </select></label>
      <label className="field"><span>Good for</span>
        <select value={filters.goodFor ?? ""} onChange={(e) => onChange({ ...filters, goodFor: sel(e.target.value) })}>
          <option value="">Any</option>{goodFors.map((g) => <option key={g} value={g}>{g}</option>)}
        </select></label>
      {active > 0 && <button className="link" onClick={() => onChange({ vibes: [], category: null, neighborhood: null, goodFor: null })}>Reset</button>}
      <span className="stat grow">{counts.results} of {counts.insight.toLocaleString()} venues with insights · {counts.venues.toLocaleString()} mapped</span>
      <a href="/review" className="control">Review</a>
      <button className="control icon" onClick={toggle} title="Toggle theme">{mode === "dark" ? "☀︎" : "☾"}</button>
    </div>
  );
}
