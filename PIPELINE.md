# Venue Insight Pipeline — living status report

Multi-source venue discovery, deduplication and LLM insight extraction for Manhattan, built as a
portfolio answer to the Moodap data-engineer brief. This file is the running account of what exists,
what the numbers are, and what is next. Design decisions live in [PLAN.md](PLAN.md); this file tracks
execution. Updated as stages land.

_Last updated: 2026-09-02 night shift. Commit `9e29e54`._

## Pipeline at a glance

```mermaid
flowchart LR
  classDef n fill:#d1e9ff,stroke:#175cd3,color:#1a2233
  classDef done fill:#d1e9ff,stroke:#0b4bb3,stroke-width:3px,color:#1a2233
  classDef todo fill:#ffffff,stroke:#175cd3,stroke-dasharray:4 3,color:#1a2233

  subgraph S1[Venue sources]
    OSM[OpenStreetMap]:::n
    DOH[NYC DOHMH inspections]:::n
  end
  subgraph S2[Text sources]
    INF[The Infatuation]:::n
    WP[Wikipedia + Wikivoyage]:::n
    RD[Reddit API]:::todo
  end

  OSM --> D1[1 discover]:::done
  DOH --> D1
  D1 --> RV[(raw_venues)]:::n
  RV --> D2[2 dedupe]:::done
  D2 --> V[(venues)]:::n

  INF --> D3[3 collect]:::done
  WP --> D3
  RD -.-> D3
  D3 --> RR[(raw_reviews)]:::n

  RR --> D4[5 match reviews]:::done
  V --> D4
  D4 --> D6[6 extract insights]:::done
  D6 --> I[(insights)]:::n
  I --> VP[(venue_profiles)]:::n
  I --> D7[7 review loop]:::done
  D7 --> SC[scorecard]:::n
  VP --> D9[9 claim readiness]:::done
  D8[8 nightly freshness]:::done -.-> D3
  style S1 fill:#f4f8fc,stroke:#175cd3,color:#1a2233
  style S2 fill:#f4f8fc,stroke:#175cd3,color:#1a2233
```

Solid boxes with a heavy border are built and verified. Dashed boxes are designed but not built (Reddit is coded but blocked on credentials).
Cylinders are Postgres tables in the local Supabase stack. The Reddit path is coded but blocked on API
credentials, so it is dashed.

## Stage status

| # | Stage | What it does | Status | Key numbers |
|---|---|---|---|---|
| 1 | discover | Pull venue candidates from OSM (Overpass, bbox + borough polygon clip) and DOHMH (Socrata) into append-only `raw_venues`. Each amenity type / page is a resumable unit. | Done | 7,130 OSM + 12,500 DOHMH in 79 s; rerun skips all units in 2 s |
| 2 | dedupe | Normalise names/streets/phones, block by geohash (150 m) or zip+street, score name + address + distance + phone, merge same-source re-registrations, greedy one-to-one cross-source matching with a near-certain override. Every scored pair kept in `match_candidates`. | Done | 19,630 raw → 14,504 venues; 4,892 cross-source pairs matched; 436 DOHMH re-registrations + 43 OSM double-mappings merged; 1,486 pairs held for review. 10 unit tests |
| 3 | collect_reviews | Venue-centric prose from open web sources into `raw_reviews`: Infatuation review pages (sitemap → server-rendered JSON), Wikipedia category members (full extracts + coords), Wikivoyage eat/drink listings on 19 district pages. | Running | Infatuation 974 / 8,142 pages (background pull); Wikipedia 235; Wikivoyage ~200 (rerun in progress) |
| 3 | collect_text (Reddit) | Subreddit keyword search + comment trees via the official OAuth API. | Blocked | Reddit refuses anonymous JSON from this IP; needs script-app credentials or gets dropped |
| 5 | match_reviews | Deterministic matcher links each `raw_reviews` row to a canonical venue using the dedupe blocking + scoring against the `venues` table; Manhattan polygon filter; every link kept in `review_venue_links` with score components. | Done (reruns as collection grows) | On the first 524 rows: 221 matched, 57 review, 188 unmatched (mostly defunct Wikipedia venues), 58 outside Manhattan. Random matched samples all correct |
| 4 | mention extraction | LLM pulls venue mentions out of free text that does not name its venue (Reddit-style). | Deferred | Not needed for the three adopted sources, which all name their venue |
| 6 | extract_insights | Structured output per matched review: vibe tags from a 25-word controlled vocabulary, noise/crowd, best time, recurring events, good-for, sentiment, confidence, evidence quotes. A grounding filter drops any field without a verbatim quote. Provider interface: Ollama Qwen 2.5 7B locally, Anthropic API by env var. Resumable per (review, model, prompt version). | Done, batch 1 running | Prompt v1→v3 after two review passes; 7B kept over 3B; ~30 s/review under load |
| 7 | review loop | `review-sample` writes a markdown sample (source text, extraction, evidence); `review-ingest` reads verdicts per reviewer into `extraction_reviews`; `scorecard` prints verbatim-evidence rate, grounding drops, verdicts per field. Loop: Qwen extracts → Claude reviews → human spot-checks. | Done | First pass (20, reviewer claude): 4 correct · 15 partial · 1 wrong. Main fault: vibe inferred from awards/press, fixed in prompt v3 |
| 8 | freshness | Expires `stage_progress` units older than a per-source TTL (DOHMH 7 d, wiki 14 d, OSM/Infatuation 30 d), reruns discover + collectors (upsert only changed content), relinks, re-extracts rows whose content hash changed, rescoring claims. `--force` expires everything. Runs nightly from the scheduler container. | Done | — |
| 9 | claim_readiness | Per-venue score = 0.45 insight richness + 0.25 activity (recent inspection) + 0.20 contact (website/phone) + 0.10 cross-source corroboration; components stored for explainability. | Done | 14,504 venues scored |

## Sources and why these

| Source | Role | Access | Notes |
|---|---|---|---|
| OpenStreetMap (Overpass) | venues | public API, no key | Needs a real User-Agent (406 otherwise); area lookups for Manhattan return nothing, so bbox + polygon clip |
| NYC DOHMH inspections (Socrata `43nn-pn8j`) | venues | public API, no key | 313 rows without coordinates, 1,659 never inspected, uppercase legal names, `/`-joined multi-concept names |
| The Infatuation | text | public pages, robots allows generic crawlers | Editorial reviews with address, coords, price, neighbourhood, cuisine, "perfect for" tags. Covers all five boroughs; Manhattan filter applied at match time |
| Wikipedia | text | MediaWiki API, no key | Notable venues only; full extracts are one page per request |
| Wikivoyage | text | MediaWiki API, no key | `{{eat}}`/`{{drink}}`/`{{listing}}` templates with address, coords, hours, price, description |
| Reddit | text | official OAuth API | Anonymous JSON blocked from this IP on every host/UA tried |
| Rejected | — | — | Facebook, X: login walls + ToS. Foursquare: login redirect. Bluesky public API: 403 here. Google/Yelp/TripAdvisor: Moodap's named competitors, anti-scraping terms |

## Runtime

- Python 3.12 package `pipeline/` with a Typer CLI (`pipeline discover | dedupe | collect-reviews | collect-text | freshness | status`).
- Supabase local stack in Docker (Postgres 17); migrations in `supabase/migrations/`, applied with `supabase migration up`.
- Ollama on the Mac host (`qwen2.5:7b-instruct`); containers reach it and Postgres via `host.docker.internal`.
- `docker compose run --rm pipeline <stage>`; `scheduler` service loops for the nightly job.
- All external calls go through one polite client: per-host throttle, retry with jittered backoff, honours 429 `Retry-After`.
- Every stage records a `pipeline_runs` row and per-unit `stage_progress` markers, so any stage resumes after a crash.

## Rules the code follows

1. `raw_*` tables are never mutated by downstream stages; everything derived can be rebuilt from raw.
2. Every stage is idempotent and resumable.
3. Derived venue ids are stable across rebuilds (`venues.key` = primary source id).
4. Every match decision is persisted with its component scores for audit.
5. Schema changes are new migration files, never edits.

## Open decisions

- Keep or drop the Reddit path (needs a free script app from the user).
- When to create the public GitHub remote.
- Freshness TTL policy per source (editorial pages change rarely; social text often).

## Change log

- 2026-09-02: scaffold, discover, dedupe, review collectors, LLM provider interface, this document.
- 2026-09-02 (03:00-04:00): stage 6 extraction with grounding filter, stage 7 review loop and first scorecard, `venue_profiles` view, stage 8 freshness with TTLs, stage 9 claim readiness. Pipeline complete end to end; batch 2 extraction pending the Infatuation pull.
- 2026-09-02 (later): Infatuation parser fix (body was nested under `content`; 1,806 preview-only rows re-pulled); stage 5 match_reviews built; stage 4 deferred.
