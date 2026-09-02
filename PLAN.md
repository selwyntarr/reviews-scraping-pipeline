# Venue Insight Pipeline — agreed design

Portfolio project modelled on the Moodap data-engineer role: discover venues from
multiple open sources, deduplicate them, extract insider details from unstructured
community text with an LLM, verify quality, and keep data fresh unattended.

## Decisions (grilled 2026-09-03)

| Area | Decision |
|---|---|
| Scope | All of Manhattan |
| Venue source 1 | OpenStreetMap via Overpass (bars, pubs, restaurants, cafes, nightclubs) |
| Venue source 2 | NYC Open Data DOHMH restaurant inspections (Socrata, no key) |
| Text source | Reddit public JSON: r/AskNYC, r/FoodNYC, r/nycbars, r/nyc. Subreddit search for venue-ish keywords, top posts past year, all comments. ~1 req/s with backoff |
| Language | Python 3.12 |
| Database | Supabase local stack in Docker (supabase CLI), migrations in supabase/migrations |
| LLM | Ollama on Mac host (Qwen), reached at host.docker.internal. Provider interface so ANTHROPIC can be swapped in by env var |
| Scheduling | Cron service in docker-compose runs nightly freshness job |
| Deliverable | Public GitHub repo, README with architecture, scorecard, sample venue profiles |

## Pipeline stages (each idempotent and resumable)

1. **discover** — pull OSM + DOHMH into `raw_venues` (source, source_id, payload jsonb, fetched_at). Never mutated.
2. **dedupe** — normalise name/address, geohash blocking, rapidfuzz scoring → `venues` + `venue_sources` link table with match confidence. Decisions persisted, overridable.
3. **collect_text** — Reddit search → `raw_posts` / `raw_comments`, content-hashed so nothing is re-processed.
4. **extract_mentions** — LLM pulls venue mentions per comment (name, neighbourhood hints, cuisine) → `mentions`.
5. **match** — deterministic matcher links mentions to `venues` (name similarity + hint agreement) → `venue_mentions` with score.
6. **extract_insights** — LLM structured output per matched mention → `insights`:
   vibe tags (controlled vocabulary), noise/crowd level, best time to visit,
   recurring events, sentiment, verbatim evidence quote. Each with confidence.
7. **review_sample** — writes `reviews/run_<id>.md` with N sampled insights + source comment + matched venue. `pipeline review ingest <file>` writes verdicts (correct / partial / wrong) to `extraction_reviews`. Reviewer loop: Qwen extracts → Claude (Fable) reviews → human spot-checks.
8. **freshness** — nightly cron: re-pull Reddit, re-extract venues with insights older than N days, recompute `venue_profiles` view.
9. **claim_readiness** — score per venue (insight confidence, mention count, website/contact present) as a claim-priority signal.

## Job state

`pipeline_runs` (run_id, stage, started_at, finished_at, status, stats jsonb) and
per-entity stage markers so any stage can resume mid-way after a crash or rate-limit stop.

## Quality

Scorecard in README derived from `extraction_reviews`: per-field precision on the
reviewed sample, match precision, dedup precision on a hand-checked sample.

## Not in scope

Specials/price extraction, paid APIs, scraping of Google/Yelp/TripAdvisor.
