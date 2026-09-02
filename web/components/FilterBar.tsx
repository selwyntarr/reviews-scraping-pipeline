"use client";
import { CATEGORIES, VIBES } from "@/lib/vocab";
import { useTheme } from "./ThemeShell";

export type Filters = { vibes: string[]; category: string | null; neighborhood: string | null; goodFor: string | null };

export function FilterBar({ filters, onChange, neighborhoods, goodFors, counts }: {
  filters: Filters; onChange: (f: Filters) => void; neighborhoods: string[]; goodFors: string[];
  counts: { venues: number; insight: number; results: number };
}) {
  const { mode, toggle } = useTheme();
  const toggleVibe = (t: string) => onChange({ ...filters, vibes: filters.vibes.includes(t) ? filters.vibes.filter((x) => x !== t) : [...filters.vibes, t] });
  const sel = (v: string) => (v === "" ? null : v);
  return (
    <div className="filters">
      <span className="brand">Venue Insight Explorer</span>
      <span className="stat">{counts.venues.toLocaleString()} venues · {counts.insight.toLocaleString()} with insights · {counts.results} shown</span>
      <span style={{ flex: 1 }} />
      <select value={filters.category ?? ""} onChange={(e) => onChange({ ...filters, category: sel(e.target.value) })} className="chip">
        <option value="">any category</option>{CATEGORIES.map((c) => <option key={c} value={c}>{c.replace("_", " ")}</option>)}
      </select>
      <select value={filters.neighborhood ?? ""} onChange={(e) => onChange({ ...filters, neighborhood: sel(e.target.value) })} className="chip">
        <option value="">any neighborhood</option>{neighborhoods.map((n) => <option key={n} value={n}>{n}</option>)}
      </select>
      <select value={filters.goodFor ?? ""} onChange={(e) => onChange({ ...filters, goodFor: sel(e.target.value) })} className="chip amber">
        <option value="">good for…</option>{goodFors.map((g) => <option key={g} value={g}>{g}</option>)}
      </select>
      <button className="chip" onClick={toggle} title="Toggle theme">{mode === "dark" ? "☀︎" : "☾"}</button>
      <div className="chips" style={{ width: "100%" }}>
        {VIBES.map((t) => <button key={t} className={`chip${filters.vibes.includes(t) ? " on" : ""}`} onClick={() => toggleVibe(t)}>{t}</button>)}
        {filters.vibes.length > 0 && <button className="chip" onClick={() => onChange({ ...filters, vibes: [] })}>clear</button>}
      </div>
    </div>
  );
}
