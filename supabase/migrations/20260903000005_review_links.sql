-- Stage 5 (match_reviews): link each raw_reviews row to a canonical venue. Deterministic, rebuilt per run.
create table if not exists review_venue_links (
    raw_review_id bigint primary key references raw_reviews (id) on delete cascade,
    venue_id      bigint references venues (id) on delete set null,
    run_id        bigint references pipeline_runs (id),
    score         real,
    name_sim      real,
    dist_m        real,
    addr_score    real,
    decision      text not null check (decision in ('matched', 'review', 'unmatched', 'outside_manhattan')),
    candidates    int  not null default 0,
    linked_at     timestamptz not null default now()
);
create index if not exists review_venue_links_venue_idx on review_venue_links (venue_id);
create index if not exists review_venue_links_decision_idx on review_venue_links (decision);
