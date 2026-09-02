-- Core job-state and raw-ingestion tables. Raw tables are append/upsert only and never mutated
-- by downstream stages, so any stage can be re-run from them.

create table if not exists pipeline_runs (
    id          bigserial primary key,
    stage       text        not null,
    started_at  timestamptz not null default now(),
    finished_at timestamptz,
    status      text        not null default 'running'
                check (status in ('running', 'succeeded', 'failed', 'interrupted')),
    stats       jsonb       not null default '{}'::jsonb,
    error       text
);
create index if not exists pipeline_runs_stage_idx on pipeline_runs (stage, started_at desc);

-- Per-unit progress within a stage (e.g. one Overpass chunk, one Socrata page, one subreddit
-- query). Lets a crashed run resume without redoing finished units.
create table if not exists stage_progress (
    stage       text        not null,
    unit_key    text        not null,
    done_at     timestamptz not null default now(),
    run_id      bigint      references pipeline_runs (id),
    stats       jsonb       not null default '{}'::jsonb,
    primary key (stage, unit_key)
);

create table if not exists raw_venues (
    id           bigserial primary key,
    source       text        not null,          -- 'osm' | 'dohmh'
    source_id    text        not null,          -- osm 'node/123' | dohmh camis
    payload      jsonb       not null,
    content_hash text        not null,          -- sha256 of canonical payload; unchanged rows skip re-processing
    fetched_at   timestamptz not null default now(),
    first_seen   timestamptz not null default now(),
    unique (source, source_id)
);
create index if not exists raw_venues_source_idx on raw_venues (source);

-- Cached administrative boundaries (GeoJSON) used to clip bbox-based source pulls.
create table if not exists boundaries (
    name       text primary key,
    geojson    jsonb       not null,
    fetched_at timestamptz not null default now()
);
