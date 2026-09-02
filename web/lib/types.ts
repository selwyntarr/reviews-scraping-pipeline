export type MapVenue = {
  id: number; name: string; category: string | null; lat: number; lon: number;
  neighborhood: string | null; has_insights: boolean;
};
export type Profile = {
  venue_id: number; key: string; name: string; category: string | null; housenumber: string | null;
  street: string | null; zip: string | null; lat: number | null; lon: number | null;
  review_count: number; sources: string[]; top_vibe_tags: string[]; vibe_tag_counts: Record<string, number>;
  noise_level: string | null; crowd_level: string | null; best_time: string | null;
  recurring_events: string[] | null; good_for: string[] | null; sentiment_score: number | null;
  mean_confidence: number | null; evidence: { field: string; quote: string }[] | null;
};
export type Evidence = { venue_id: number; source: string; url: string | null; source_title: string; field: string; quote: string; published_at: string | null };
export type Claim = { venue_id: number; score: number; components: Record<string, number> };
