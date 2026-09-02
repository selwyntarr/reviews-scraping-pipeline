# Design decisions

Why things are the way they are. Status lives in [PIPELINE.md](PIPELINE.md); mechanics in the
[README](README.md). Grilled with the user on 2026-09-02.

## Constraints

- Zero spend, open sources only, no accounts required to run, everything in Docker.
- Local Qwen via Ollama; the Anthropic API stays one env var away because the brief values Claude.
- One-time portfolio build, not an ongoing product: scope is the stages listed, nothing speculative.
- No fallbacks or graceful degradation unless asked; fail loudly.

## Decisions

| Area | Decision | Why |
|---|---|---|
| Scope | All of Manhattan | Mirrors the target product's coverage; big enough for real collisions |
| Venue sources | OpenStreetMap + NYC DOHMH inspections | Two feeds with different naming conventions make dedup real |
| Text sources | The Infatuation, Wikipedia, Wikivoyage; Reddit coded but blocked | Reddit refuses anonymous access from this network; Facebook/X/Foursquare/Bluesky have login walls, terms, or blocks; Google/Yelp/TripAdvisor are the target product's competitors with anti-scraping terms |
| Mention → venue linking | Deterministic matcher reusing the dedup scorer; LLM mention extraction deferred | All adopted sources name their venue and carry coordinates |
| Model | Qwen 2.5 7B over 3B | 3B was only 1.6× faster and put dish names in good-for |
| Grounding | Every field needs a verbatim quote or it is dropped mechanically | The first prompt invented values; the check removed them without trusting the model |
| Quality loop | Model extracts → Claude reviews a sample → human spot-checks → verdicts per reviewer → scorecard | Repeatable, and reviewer disagreement is itself a metric |
| Resumability | `pipeline_runs` + per-unit `stage_progress`; raw tables append-only; derived tables rebuilt with stable keys | Any stage resumes after a crash or rate limit |
| Freshness | Per-source TTL expiry of progress markers, nightly scheduler container | Editorial pages change slowly, inspections weekly |
| Frontend | Next.js + Radix Themes + MapLibre/OpenFreeMap + supabase-js on local PostgREST views | Matches the target stack; no API layer; no keys. Only the target's colour scheme was borrowed, layout is our own |
| Git | Conventional Commits, no AI attribution trailers | User's convention |

## Extraction schema

Vibe tags from a 25-word controlled vocabulary; noise and crowd level; best time; recurring events;
good-for; sentiment; confidence; evidence quotes. Specials and pricing are out of scope.
