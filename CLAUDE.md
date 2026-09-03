# Venue Insight Pipeline

Read PLAN.md before changing a stage; keep PIPELINE.md current when one lands.

## Run
`supabase start` → `cp .env.example .env` → `uv run pipeline <stage>` or `docker compose run --rm pipeline <stage>`.
Web: `docker compose up -d web` (never `npm install` on the host; edit `web/package.json`, regenerate the lockfile in a `node:22-alpine` container, `docker compose build web`).

## Rules
- `raw_*` tables are never mutated downstream; every stage is idempotent via `stage_progress`.
- Logging via `pipeline/logging_setup.py` (console + `logs/pipeline.log`); never print. External calls go through `pipeline/http.py`. Schema changes are new files in `supabase/migrations/`.
- After a collector's first hundred rows, check average text length and one full row before letting it run.
- Verify model output mechanically (verbatim evidence) before trusting it.

## Git
Conventional Commits with scopes discover, dedupe, collect, match, extract, review, pipeline, web. No AI attribution trailers. Commit as selwyntarr / selwyntarr@gmail.com; push to `main` only when asked.

## Memory
Canonical memory is `agent-memory/` (MCP `venue-memory`: `remember_fact`, `recall_semantic`, `list_board`). `/standup` opens, `/wrap` closes a session. `agent-memory/` and `.claude/` are local-only. The machine clock says PST but is UTC+8.
