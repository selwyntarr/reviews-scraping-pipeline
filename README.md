# Venue Insight Pipeline

[![ci](https://github.com/selwyntarr/reviews-scraping-pipeline/actions/workflows/ci.yml/badge.svg)](https://github.com/selwyntarr/reviews-scraping-pipeline/actions/workflows/ci.yml)

Discovers Manhattan venues from open data, deduplicates them, extracts "insider" details (vibe,
best time, good-for, sentiment) from open review text with a local LLM, and serves the result in a
one-page map explorer. Built as a portfolio answer to a venue-discovery data-engineering brief.
Runs entirely on a laptop at zero cost: Supabase (Postgres) in Docker, Qwen through Ollama.

What matters more than the numbers: every stage is **resumable**, raw data is **never mutated**,
every match and every extracted fact carries **its own evidence**, and a **review loop** measures
the model instead of trusting it.

- [PIPELINE.md](PIPELINE.md): live status, numbers, what's next
- [PLAN.md](PLAN.md): design decisions and why

## Stages

| # | Stage | Does |
|---|---|---|
| 1 | discover | OSM (Overpass) + NYC DOHMH inspections → `raw_venues`, one resumable unit per amenity type / page |
| 2 | dedupe | Normalise, block by 150 m geohash, score name + address + distance + phone, merge same-source re-registrations, one-to-one cross-source matching. Every scored pair kept in `match_candidates` |
| 3 | collect | The Infatuation, Wikipedia, Wikivoyage → `raw_reviews`, one unit per page. Reddit adapter exists but needs API credentials |
| 5 | match | Links each review to a venue with the stage-2 scorer, Manhattan polygon filter |
| 6 | extract | Qwen 2.5 7B structured output: vibe tags from a 25-word vocabulary, noise/crowd, best time, events, good-for, sentiment, confidence, verbatim evidence. Fields without a verbatim quote are dropped |
| 7 | review | Markdown sample or the web review page → verdicts per reviewer → `scorecard` |
| 8 | freshness | Expires units past a per-source TTL, re-pulls, relinks, re-extracts changed text, rescores. Run nightly by the scheduler container |
| 9 | claim readiness | Explainable 0–1 score per venue for a business-claim flow |

Stage 4 (LLM mention extraction for text that doesn't name its venue) is designed but unnecessary
for the adopted sources.

## Run

Needs Docker Desktop, the [Supabase CLI](https://supabase.com/docs/guides/cli), [uv](https://docs.astral.sh/uv/),
and [Ollama](https://ollama.com) with `ollama pull qwen2.5:7b-instruct`.

```bash
supabase start                          # Postgres + Studio at http://127.0.0.1:54323
cp .env.example .env                    # add SUPABASE_ANON_KEY from `supabase status -o env`
uv sync

uv run pipeline discover                # ~80 s
uv run pipeline dedupe                  # ~30 s
uv run pipeline collect-reviews --max-pages 100   # full Infatuation pull is ~3 h
uv run pipeline match-reviews
uv run pipeline extract-insights --limit 50       # ~30 s per review on a MacBook Air
uv run pipeline claim-readiness
uv run pipeline scorecard
uv run pipeline status

docker compose up -d web scheduler      # explorer at http://localhost:3000, nightly freshness
```

Every stage logs to `logs/pipeline.log` (daily rotation, 14 days kept); `uv run pipeline logs --stage extract_insights` tails it. `docker compose run --rm pipeline <command>` runs any stage in a container. `LLM_PROVIDER=anthropic`
plus an API key swaps the model. `uv run pytest` runs the tests; CI runs ruff, pytest, tsc and eslint.

## Web explorer

`web/` is a Next.js app (Radix Themes, MapLibre GL with OpenFreeMap tiles, supabase-js against
PostgREST views) served from Docker with hot reload.

- `/` map of every venue; insight-backed venues filterable by mood, type, neighborhood, good-for;
  drawer with evidence quotes linked to sources and the claim-readiness score
- `/review` source text with evidence highlighted, per-field verdicts, saved per reviewer
- `/pipeline` stage checklist with progress, table counts, scheduler heartbeat

## How the hard parts work

**Deduplication.** "MCSORLEYS OLD ALE HOUSE, WEST   7 STREET" and "McSorley's Old Ale House,
East 7th Street" must meet. Names lose apostrophes, corporate suffixes and store numbers; streets
canonicalise ordinals and directions; phones reduce to digits; `/`-joined multi-concept names split
into variants. Blocking is by geohash cell (or zip + street without coordinates). Same-source
duplicates merge first, which catches DOHMH re-registering one venue under a new license. A name
floor stops different businesses at one address from merging; a near-certain override keeps exact
pairs from being orphaned by the one-to-one rule. Venue ids are stable across rebuilds.

**Extraction you can check.** The model must quote, verbatim, a passage for every non-empty field.
The pipeline verifies each quote against the source and drops fields without one, logging what it
dropped. That mechanically removed the invented "date night / solo lunch" values of the first
prompt. What it cannot catch is inference ("located in The Fifth Avenue Hotel" quoted as evidence for
"upscale"), which is what the review loop exists for. Two passes of 20 insights each, judged against
the source text:

| | prompt v2 | prompt v3 |
|---|---|---|
| overall | 4 correct · 15 partial · 1 wrong | 6 correct · 12 partial · 2 wrong |
| vibe_tags | 5 / 11 / 4 | 7 / 4 / 4 |
| dominant fault | vibe inferred from awards, hotels, press | under-extraction: best time and events present in the text but missed; two neutral texts marked negative |
| evidence fully verbatim | 60 % | 89 % |

v3 forbade deriving atmosphere from awards or history, which fixed the v2 fault; the v3 findings are
the input to the next prompt. Verdicts are stored per reviewer, so a second reviewer's disagreement
is measurable, and each prompt version's extractions sit side by side in `insights`.

**Resumability.** Every stage writes a `pipeline_runs` row and per-unit `stage_progress` markers, so a
crash or a rate-limit stop resumes where it left off. One HTTP client handles throttling, jittered
retries and `Retry-After` for every source.

## Sources

| Source | Role | Notes |
|---|---|---|
| OpenStreetMap (Overpass) | venues | public API; bbox + borough polygon clip because area lookups fail |
| NYC DOHMH inspections (Socrata) | venues | public API; uppercase legal names, zero coordinates, never-inspected registrations |
| The Infatuation | text | public pages allowed by robots; server-rendered JSON parsed per page |
| Wikipedia, Wikivoyage | text | MediaWiki API |
| Reddit | text | official API only; blocked here without app credentials |

Google, Yelp and TripAdvisor were deliberately not scraped. Facebook, X, Foursquare and Bluesky were
tested and ruled out (login walls, terms, or blocked from this network).

## Layout

```
pipeline/            config, db (runs + progress), http, geo, geohash, normalize, llm, stages/
supabase/migrations/ schema, one file per change
tests/               normaliser, scoring, geohash, scheduler
web/                 Next.js explorer (Docker dev service)
```
