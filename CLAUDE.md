# Venue Insight Pipeline

Portfolio project: multi-source venue discovery, dedup, and LLM insight extraction for Manhattan.
Design decisions live in PLAN.md. Read it before changing pipeline stages.

## Run
- `supabase start` (Docker must be running), then `supabase db reset` to apply migrations.
- `cp .env.example .env`
- `docker compose run --rm pipeline discover` (or `uv run pipeline discover` on the host with the host DATABASE_URL).

## Rules
- Raw tables (`raw_*`) are never mutated by downstream stages.
- Every stage must be idempotent: record units in `stage_progress`, skip done units on rerun.
- External calls go through `pipeline/http.py` for retry/backoff and rate limiting.
- Schema changes are new files in `supabase/migrations/`, never edits to applied ones.
