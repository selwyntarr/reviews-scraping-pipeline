"use client";
import type { Claim, Evidence, MapVenue, Profile } from "@/lib/types";
import { SOURCE_LABEL, sentimentLabel } from "@/lib/vocab";

export function VenueDrawer({ venue, profile, evidence, claim, onClose }: {
  venue: MapVenue | null; profile: Profile | null; evidence: Evidence[]; claim: Claim | null; onClose: () => void;
}) {
  if (!venue) return null;
  const p = profile;
  const tagCounts = p ? Object.entries(p.vibe_tag_counts ?? {}).sort((a, b) => b[1] - a[1]) : [];
  return (
    <aside className="drawer">
      <button className="close" onClick={onClose} aria-label="Close">×</button>
      <h2>{venue.name}</h2>
      <div className="meta">{[venue.category?.replace("_", " "), venue.neighborhood, p?.housenumber && p?.street ? `${p.housenumber} ${p.street}` : null].filter(Boolean).join(" · ")}</div>
      {!p && <div className="empty">No extracted insights for this venue yet.</div>}
      {p && (<>
        <div className="section"><h5>Vibe</h5>
          {tagCounts.length ? tagCounts.map(([t, n]) => <span key={t} className="tag">{t}{n > 1 ? ` ×${n}` : ""}</span>) : <span className="stat">nothing described</span>}
        </div>
        <div className="section"><h5>Insider details</h5>
          <div className="tip"><b>Sentiment:</b> {sentimentLabel(p.sentiment_score)} · <b>Confidence:</b> {p.mean_confidence ?? "—"} · <b>Reviews:</b> {p.review_count}</div>
          {p.best_time && <div className="tip"><b>Best time:</b> {p.best_time}</div>}
          {(p.noise_level || p.crowd_level) && <div className="tip"><b>Scene:</b> {[p.noise_level && `${p.noise_level} noise`, p.crowd_level && `${p.crowd_level} crowd`].filter(Boolean).join(", ")}</div>}
          {p.good_for?.length ? <div className="tip"><b>Good for:</b> {p.good_for.join(", ")}</div> : null}
          {p.recurring_events?.length ? <div className="tip"><b>Recurring:</b> {p.recurring_events.join("; ")}</div> : null}
        </div>
        <div className="section"><h5>Evidence ({evidence.length})</h5>
          {evidence.map((e, i) => (
            <div key={i} className="quote">“{e.quote}”
              <small>{e.field} · {e.url ? <a href={e.url} target="_blank" rel="noreferrer">{SOURCE_LABEL[e.source] ?? e.source}</a> : (SOURCE_LABEL[e.source] ?? e.source)}{e.published_at ? ` · ${e.published_at.slice(0, 4)}` : ""}</small>
            </div>
          ))}
        </div>
      </>)}
      {claim && (
        <div className="section"><h5>Claim readiness {Math.round(claim.score * 100)}%</h5>
          <div className="bar"><i style={{ width: `${Math.round(claim.score * 100)}%` }} /></div>
          <div className="stat" style={{ marginTop: 6 }}>
            insight {Math.round((claim.components.insight ?? 0) * 100)}% · active {Math.round((claim.components.active ?? 0) * 100)}% · contact {Math.round((claim.components.contact ?? 0) * 100)}% · corroboration {Math.round((claim.components.corroboration ?? 0) * 100)}%
          </div>
        </div>
      )}
    </aside>
  );
}
