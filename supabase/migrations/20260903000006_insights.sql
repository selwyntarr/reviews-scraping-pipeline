-- Stage 6 (extract_insights): one row per (raw_review, model) extraction. Stage 7 review verdicts.

create table if not exists insights (
    id            bigserial primary key,
    raw_review_id bigint not null references raw_reviews (id) on delete cascade,
    venue_id      bigint references venues (id) on delete set null,
    model         text   not null,                 -- e.g. 'ollama:qwen2.5:7b-instruct'
    prompt_version text  not null,
    content_hash  text   not null,                 -- raw_reviews.content_hash at extraction time
    vibe_tags     text[] not null default '{}',
    noise_level   text,
    crowd_level   text,
    best_time     text,
    recurring_events text[] not null default '{}',
    good_for      text[] not null default '{}',
    sentiment     text,
    evidence      jsonb  not null default '[]'::jsonb,   -- [{field, quote}]
    evidence_verbatim boolean,                     -- every quote found in the source text
    confidence    real,
    raw_output    jsonb  not null,
    duration_ms   int,
    run_id        bigint references pipeline_runs (id),
    created_at    timestamptz not null default now(),
    unique (raw_review_id, model, prompt_version)
);
create index if not exists insights_venue_idx on insights (venue_id);

create table if not exists extraction_reviews (
    id          bigserial primary key,
    insight_id  bigint not null references insights (id) on delete cascade,
    reviewer    text   not null,                   -- 'claude' | 'selwyn' | ...
    verdict     text   not null check (verdict in ('correct', 'partial', 'wrong')),
    field_verdicts jsonb not null default '{}'::jsonb,  -- {field: correct|partial|wrong}
    notes       text,
    reviewed_at timestamptz not null default now(),
    unique (insight_id, reviewer)
);
