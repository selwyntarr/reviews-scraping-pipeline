-- Stage 3b (collect_reviews): venue-centric text from open web sources. One row per (source, item).
-- Unlike Reddit comments, these items already name their venue and usually carry an address and
-- coordinates, so they also feed venue matching directly.

create table if not exists raw_reviews (
    id           bigserial primary key,
    source       text        not null,          -- 'infatuation' | 'wikipedia' | 'wikivoyage'
    source_id    text        not null,          -- slug / page title / listing key
    url          text,
    venue_name   text        not null,
    street       text,
    zip          text,
    lat          double precision,
    lon          double precision,
    neighborhood text,
    tags         text[]      not null default '{}',   -- cuisine, perfect-for, venue type
    price        text,
    hours        text,
    published_at date,
    title        text,
    text         text        not null,           -- the prose to extract from
    payload      jsonb       not null,
    content_hash text        not null,
    fetched_at   timestamptz not null default now(),
    unique (source, source_id)
);
create index if not exists raw_reviews_source_idx on raw_reviews (source);
