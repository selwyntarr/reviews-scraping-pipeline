"use client";
import type { MapVenue, Profile } from "@/lib/types";
import { SOURCE_LABEL, sentimentLabel } from "@/lib/vocab";

export function tipFor(p: Profile): { label: string; text: string } | null {
  if (p.best_time) return { label: "Best time", text: p.best_time };
  if (p.good_for?.length) return { label: "Good for", text: p.good_for.slice(0, 3).join(", ") };
  if (p.recurring_events?.length) return { label: "Regularly", text: p.recurring_events[0] };
  if (p.noise_level || p.crowd_level) return { label: "Scene", text: [p.noise_level, p.crowd_level].filter(Boolean).join(", ") };
  return null;
}

export function ResultsPanel({ results, byId, selected, onSelect, loading }: {
  results: Profile[]; byId: Map<number, MapVenue>; selected: number | null; onSelect: (id: number) => void; loading: boolean;
}) {
  if (loading) return <div className="results"><div className="empty">Loading venues…</div></div>;
  return (
    <div className="results">
      {results.length === 0 && <div className="empty">No venue with insights matches every selected chip. Try fewer.</div>}
      {results.slice(0, 200).map((p) => {
        const v = byId.get(p.venue_id); const tip = tipFor(p); const s = sentimentLabel(p.sentiment_score);
        const quote = p.evidence?.[0]?.quote;
        return (
          <div key={p.venue_id} className={`card${selected === p.venue_id ? " on" : ""}`} onClick={() => onSelect(p.venue_id)}>
            <h4>{p.name}</h4>
            <div className="meta">{[p.category?.replace("_", " "), v?.neighborhood].filter(Boolean).join(" · ")}</div>
            <div>{p.top_vibe_tags.slice(0, 3).map((t) => <span key={t} className="tag">{t}</span>)}</div>
            {tip && <div className="tip"><b>{tip.label}:</b> {tip.text}</div>}
            {quote && <div className="tip"><q>{quote.length > 140 ? quote.slice(0, 137) + "…" : quote}</q></div>}
            <div style={{ marginTop: 6 }}>
              <span className={`badge ${s === "positive" ? "pos" : s === "negative" ? "neg" : "mix"}`}>{s}</span>
              {p.sources.map((src) => <span key={src} className="badge">{SOURCE_LABEL[src] ?? src}</span>)}
            </div>
          </div>
        );
      })}
    </div>
  );
}
