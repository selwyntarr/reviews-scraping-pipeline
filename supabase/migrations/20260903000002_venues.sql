-- Stage 2 (dedupe) output. Rebuilt deterministically from raw_venues; venue.key is stable across
-- rebuilds so downstream stages can reference venues safely.

create table if not exists venues (
    id           bigserial primary key,
    key          text        not null unique,     -- 'osm:node/123' or 'dohmh:41234567' (primary source)
    name         text        not null,
    name_norm    text        not null,
    category     text,                            -- bar | pub | restaurant | cafe | nightclub | fast_food | other
    housenumber  text,
    street       text,
    street_norm  text,
    zip          text,
    lat          double precision,
    lon          double precision,
    geohash      text,
    phone        text,                            -- 10 digits
    website      text,
    cuisine      text,
    last_inspection date,                          -- from DOHMH when present
    source_count int         not null default 1,
    created_at   timestamptz not null default now(),
    updated_at   timestamptz not null default now(),
    retired_at   timestamptz                       -- set when a rebuild no longer produces this key
);
create index if not exists venues_geohash_idx on venues (geohash);
create index if not exists venues_name_norm_idx on venues (name_norm);

create table if not exists venue_sources (
    venue_id     bigint  not null references venues (id) on delete cascade,
    source       text    not null,
    source_id    text    not null,
    raw_venue_id bigint  not null references raw_venues (id),
    match_score  real,                            -- null for the primary record
    match_method text,                            -- 'primary' | 'auto' | 'same-source'
    primary key (source, source_id)
);
create index if not exists venue_sources_venue_idx on venue_sources (venue_id);

-- Every scored candidate pair, kept for auditability and the README scorecard.
create table if not exists match_candidates (
    id           bigserial primary key,
    run_id       bigint references pipeline_runs (id),
    left_raw_id  bigint not null references raw_venues (id),
    right_raw_id bigint not null references raw_venues (id),
    score        real   not null,
    name_sim     real,
    dist_m       real,
    addr_score   real,
    phone_match  boolean,
    decision     text   not null check (decision in ('matched', 'review', 'rejected'))
);
create index if not exists match_candidates_run_idx on match_candidates (run_id, decision);
