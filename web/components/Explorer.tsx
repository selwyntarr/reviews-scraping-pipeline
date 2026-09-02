"use client";
import { useEffect, useMemo, useState } from "react";
import { fetchAll, supabase } from "@/lib/supabase";
import type { Claim, Evidence, MapVenue, Profile } from "@/lib/types";
import { FilterBar, type Filters } from "./FilterBar";
import { MapView } from "./MapView";
import { ResultsPanel } from "./ResultsPanel";
import { VenueDrawer } from "./VenueDrawer";

export function Explorer() {
  const [venues, setVenues] = useState<MapVenue[]>([]);
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [filters, setFilters] = useState<Filters>({ vibes: [], category: null, neighborhood: null, goodFor: null });
  const [selected, setSelected] = useState<number | null>(null);
  const [evidence, setEvidence] = useState<Evidence[]>([]);
  const [claim, setClaim] = useState<Claim | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      fetchAll<MapVenue>("venue_map", "id,name,category,lat,lon,neighborhood,has_insights"),
      fetchAll<Profile>("venue_profiles", "*", "venue_id"),
    ]).then(([v, p]) => { setVenues(v); setProfiles(p); }).catch((e) => setError(String(e.message ?? e)));
  }, []);

  useEffect(() => {
    if (selected == null) { setEvidence([]); setClaim(null); return; }
    supabase.from("venue_evidence").select("*").eq("venue_id", selected).then(({ data }) => setEvidence((data ?? []) as Evidence[]));
    supabase.from("claim_readiness").select("venue_id,score,components").eq("venue_id", selected).maybeSingle().then(({ data }) => setClaim(data as Claim | null));
  }, [selected]);

  const byId = useMemo(() => new Map(venues.map((v) => [v.id, v])), [venues]);
  const neighborhoods = useMemo(() => Array.from(new Set(venues.map((v) => v.neighborhood).filter(Boolean) as string[])).sort(), [venues]);
  const goodFors = useMemo(() => {
    const c = new Map<string, number>();
    profiles.forEach((p) => p.good_for?.forEach((g) => c.set(g, (c.get(g) ?? 0) + 1)));
    return Array.from(c.entries()).sort((a, b) => b[1] - a[1]).slice(0, 12).map(([g]) => g);
  }, [profiles]);

  const results = useMemo(() => profiles.filter((p) => {
    const v = byId.get(p.venue_id);
    if (filters.category && p.category !== filters.category) return false;
    if (filters.neighborhood && v?.neighborhood !== filters.neighborhood) return false;
    if (filters.goodFor && !p.good_for?.includes(filters.goodFor)) return false;
    return filters.vibes.every((t) => p.top_vibe_tags.includes(t) || (p.vibe_tag_counts && t in p.vibe_tag_counts));
  }).sort((a, b) => b.review_count - a.review_count || (b.mean_confidence ?? 0) - (a.mean_confidence ?? 0)), [profiles, filters, byId]);

  const resultIds = useMemo(() => new Set(results.map((r) => r.venue_id)), [results]);
  const selectedProfile = profiles.find((p) => p.venue_id === selected) ?? null;

  return (
    <div className="app">
      <MapView venues={venues} highlighted={resultIds} selected={selected} onSelect={setSelected} />
      <FilterBar filters={filters} onChange={setFilters} neighborhoods={neighborhoods} goodFors={goodFors}
        counts={{ venues: venues.length, insight: profiles.length, results: results.length }} />
      {error && <div className="results"><div className="empty">Could not load data: {error}</div></div>}
      {!error && <ResultsPanel results={results} byId={byId} selected={selected} onSelect={setSelected} loading={!venues.length} />}
      {selected != null && (
        <VenueDrawer venue={byId.get(selected) ?? null} profile={selectedProfile} evidence={evidence} claim={claim} onClose={() => setSelected(null)} />
      )}
    </div>
  );
}
