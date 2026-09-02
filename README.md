# Venue Insight Pipeline

Multi-source venue discovery, deduplication and LLM insight extraction for Manhattan, built as a
portfolio answer to a "mood-based venue discovery" data-engineering brief. Everything runs locally at
zero cost: open data sources, Supabase (Postgres) in Docker, and a local Qwen model through Ollama,
with the Anthropic API available behind one environment variable.

The point is not the one-off numbers. It is that every stage is **resumable**, every raw record is
**kept**, every match and every extracted fact carries **its own evidence**, and a **review loop**
measures the LLM instead of trusting it.

- [PIPELINE.md](PIPELINE.md) — living status report with the stage diagram and current numbers
- [PLAN.md](PLAN.md) — the design decisions and why

## What it does

```
OpenStreetMap ─┐                                  Infatuation ─┐
NYC DOHMH ─────┴→ 1 discover → raw_venues → 2 dedupe → venues   Wikipedia ───┼→ 3 collect → raw_reviews
                                                        │        Wikivoyage ──┘        │
                                                        └──────── 5 match ←────────────┘
                                                                     │
                                                              6 extract insights → insights → venue_profiles
                                                                     │                          │
                                                              7 review loop → scorecard    9 claim readiness
                                                              8 nightly freshness (TTL per source)
```

| Stage | Result on Manhattan |
|---|---|
| 1 discover | 7,130 OSM + 12,500 DOHMH venue records in 79 s; rerun skips finished units in 2 s |
| 2 dedupe | 19,630 raw → 14,504 venues; 4,892 cross-source matches (79 % exact name, 73 % full address, 43 % phone); 436 DOHMH re-registrations + 43 OSM double-mappings merged; 1,486 pairs held for review; every scored pair kept |
| 3 collect | 8,142 Infatuation review pages, 440 Wikipedia articles, 226 Wikivoyage listings, each resumable per page |
| 5 match | Reviews linked to venues with the dedupe scorer; random matched samples all correct |
| 6 extract | Vibe tags (controlled vocabulary), noise/crowd, best time, recurring events, good-for, sentiment, confidence, verbatim evidence; ungrounded fields dropped mechanically |
| 7 review | Markdown sample → reviewer verdicts → scorecard; first pass: 4 correct / 15 partial / 1 wrong on 20, which drove prompt v3 |
| 8 freshness | Per-source TTLs expire progress markers; re-pull, relink, re-extract only changed content |
| 9 claim readiness | Explainable 0–1 score per venue for a business-claim flow |

## Run it

Prerequisites: Docker Desktop, the [Supabase CLI](https://supabase.com/docs/guides/cli), [uv](https://docs.astral.sh/uv/),
and [Ollama](https://ollama.com) on the host with `ollama pull qwen2.5:7b-instruct`.

```bash
supabase start                      # local Postgres + Studio at http://127.0.0.1:54323
cp .env.example .env                # host defaults; compose overrides hosts for containers
uv sync

uv run pipeline discover            # stage 1   ~80 s
uv run pipeline dedupe              # stage 2   ~30 s
uv run pipeline collect-reviews     # stage 3   ~3 h for the full Infatuation pull; --max-pages 50 to sample
uv run pipeline match-reviews       # stage 5   seconds
uv run pipeline extract-insights --limit 50   # stage 6   ~30 s per review on a MacBook Air
uv run pipeline review-sample --n 20          # stage 7   write reviews/sample_run<id>.md, fill verdicts,
uv run pipeline review-ingest reviews/sample_run<id>.md --reviewer you
uv run pipeline scorecard
uv run pipeline claim-readiness     # stage 9
uv run pipeline freshness           # stage 8, what the scheduler container runs nightly
uv run pipeline status
```

Or in Docker: `docker compose run --rm pipeline <command>`; `docker compose up scheduler` runs the
nightly freshness job. Switch the model with `LLM_PROVIDER=anthropic` and an API key.

Tests: `uv run pytest` (normaliser and scoring rules that caused real errors during development).

## How the hard parts work

**Deduplication.** Names are normalised (apostrophes, corporate suffixes, `/`-joined multi-concept
names split into variants), streets canonicalised ("WEST   23 STREET" and "West 23rd Street" both
become `w 23 st`), phones reduced to digits. Records are blocked by 150 m geohash cell (or zip + street
when coordinates are missing) and scored on name similarity, address agreement, distance and phone.
Same-source duplicates merge first, which is what catches DOHMH re-registering one venue under a new
license. Cross-source matching is greedy one-to-one at cluster level with a near-certain override, and a
name floor stops different businesses at one address from merging. Every scored pair is stored in
`match_candidates` with its components; venue ids are stable across rebuilds.

**Extraction that can be checked.** The model must return, for every non-empty field, a quote copied
verbatim from the review. After the call, the pipeline checks each quote against the source text and
drops any field without one, recording what it dropped. That single rule turned "date night / solo
lunch" hallucinations (prompt v1) into empty fields. What it cannot catch is *inference*: "located in
The Fifth Avenue Hotel" quoted as evidence for "upscale". That is what the review loop is for, and
the first pass led to prompt v3, which forbids deriving atmosphere from awards, press or history.

**Review loop.** `review-sample` writes a markdown file per run with source text, extraction and
evidence; a reviewer (Claude in-session, then a human spot-check) fills `verdict:` lines;
`review-ingest` stores them per reviewer so disagreement is itself measurable; `scorecard` reports
verbatim-evidence rate, grounding drops and verdicts per field. Prompt versions live side by side in
`insights`, so a new prompt is compared row for row against the old one.

**Resumability.** Every stage records a `pipeline_runs` row and per-unit `stage_progress` markers
(an Overpass amenity chunk, a Socrata page, a review URL, a district page). A crash or a rate-limit stop
resumes where it left off. Raw tables are never mutated downstream; everything derived can be rebuilt.
External calls go through one client with per-host throttling, jittered retries and `Retry-After`.

## Scorecard (first pass, 20 insights, prompt v2, reviewer: Claude)

| Metric | Value |
|---|---|
| Overall verdicts | 4 correct · 15 partial · 1 wrong |
| `vibe_tags` | 5 correct · 11 partial · 4 wrong |
| `sentiment` | 5 / 5 correct where judged |
| `good_for` | 1 correct · 2 wrong (dish names, not occasions) |
| Evidence fully verbatim | 33 of 55 insights |
| Fields dropped by the grounding filter | see `scorecard` |

The partials are almost all one pattern: a plausible tag inferred from a fact rather than a described
atmosphere. Prompt v3 addresses it; the scorecard is recomputed after each batch.

## Sample venue profiles

Extracted by the local 7B model with prompt v3 from The Infatuation's reviews; each value is backed by
the quote shown, checked verbatim against the source.

| Venue | Vibe | Noise | Best time / good for | Sentiment | Evidence |
|---|---|---|---|---|---|
| 169 Bar | classic, divey | — | — | positive | "169 Bar has been open since 1916, although we assume their leopard-print pool table arrived sometime in the 70's… it all seems to have come from a yard sale." |
| 11 Tigers | lively, no-frills | loud | — | negative | "a loud, lively scene" |
| 12 Matcha | upscale, trendy, quiet | — | — | positive | "looks like somewhere you'd take a $200 sound bath" |
| 230 Fifth Rooftop Lounge | tourist-heavy, lively | — | brunch | positive | "tourists and native New Yorkers flock here all year-round" |
| 100 Feast & Lounge | — | — | earlier in the day | positive | "Even on a weekday morning the room fills up surprisingly fast, so the earlier you can get here, the better." |
| 124 Old Rabbit Club | divey | — | craft beer nerds | positive | "a tiny basement bar, and a craft beer nerd's dream." |
| 20 Blocks | casual, trendy | — | lunch | positive | "feels like it's run by people who moonlight as DJs, or exceptionally committed kindergarten teachers." |

Where the text describes no atmosphere the fields stay empty rather than guessed. Per-venue
aggregates (tag frequencies, consensus sentiment, evidence) live in the `venue_profiles` view.

## Sources and why these

| Source | Role | Access |
|---|---|---|
| OpenStreetMap (Overpass) | venues | public API; needs a real User-Agent; area lookups failed so bbox + borough polygon clip |
| NYC DOHMH inspections (Socrata) | venues | public API; uppercase legal names, zero coordinates, never-inspected registrations |
| The Infatuation | text | public pages; robots allows generic crawlers; server-rendered JSON parsed per page |
| Wikipedia, Wikivoyage | text | MediaWiki API; notable and guide-listed venues |
| Reddit | text | coded against the official API; blocked here without app credentials |

Google, Yelp and TripAdvisor were deliberately not scraped. Facebook, X, Foursquare and Bluesky were
tested and ruled out (login walls, terms, or blocked from this network).

## Layout

```
pipeline/           config, db (runs + progress), http (polite client), geo, normalize, llm (provider interface)
pipeline/stages/    discover, dedupe, collect_reviews, collect_text (Reddit), match_reviews,
                    extract_insights, review_sample, freshness, claim_readiness
supabase/migrations/  schema, one file per change
tests/              normaliser + scoring rules
reviews/            review sample files (gitignored except the folder)
```
