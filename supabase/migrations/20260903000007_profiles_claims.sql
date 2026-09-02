-- Venue profiles: aggregate insights per venue (what a product would read). Claim readiness: stage 9 score.

create or replace view venue_profiles as
with ins as (
    select i.venue_id, i.raw_review_id, i.vibe_tags, i.noise_level, i.crowd_level, i.best_time,
           i.recurring_events, i.good_for, i.sentiment, i.confidence, i.evidence, r.source
    from insights i join raw_reviews r on r.id = i.raw_review_id
    where i.venue_id is not null
),
tags as (
    select venue_id, tag, count(*) as n
    from ins, unnest(vibe_tags) as tag group by 1, 2
),
tag_agg as (
    select venue_id, jsonb_object_agg(tag, n order by n desc, tag) as vibe_tag_counts,
           array_agg(tag order by n desc, tag) as vibe_tags_ranked
    from tags group by 1
)
select v.id as venue_id, v.key, v.name, v.category, v.housenumber, v.street, v.zip, v.lat, v.lon,
       count(distinct ins.raw_review_id)                          as review_count,
       array_agg(distinct ins.source)                             as sources,
       coalesce(ta.vibe_tags_ranked[1:5], '{}')                   as top_vibe_tags,
       coalesce(ta.vibe_tag_counts, '{}'::jsonb)                  as vibe_tag_counts,
       mode() within group (order by ins.noise_level)             as noise_level,
       mode() within group (order by ins.crowd_level)             as crowd_level,
       (array_remove(array_agg(ins.best_time), null))[1]          as best_time,
       (select array_agg(distinct e) from ins i2, unnest(i2.recurring_events) e where i2.venue_id = v.id) as recurring_events,
       (select array_agg(distinct g) from ins i3, unnest(i3.good_for) g where i3.venue_id = v.id)         as good_for,
       round(avg(case ins.sentiment when 'positive' then 1 when 'mixed' then 0 when 'negative' then -1 end)::numeric, 2) as sentiment_score,
       round(avg(ins.confidence)::numeric, 2)                     as mean_confidence,
       (select jsonb_agg(e) from (select jsonb_array_elements(i4.evidence) e from ins i4 where i4.venue_id = v.id limit 6) q) as evidence
from venues v
join ins on ins.venue_id = v.id
left join tag_agg ta on ta.venue_id = v.id
where v.retired_at is null
group by v.id, ta.vibe_tags_ranked, ta.vibe_tag_counts;

create table if not exists claim_readiness (
    venue_id       bigint primary key references venues (id) on delete cascade,
    run_id         bigint references pipeline_runs (id),
    score          real not null,
    components     jsonb not null,
    computed_at    timestamptz not null default now()
);
create index if not exists claim_readiness_score_idx on claim_readiness (score desc);
