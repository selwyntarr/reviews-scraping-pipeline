-- Status page: latest run per stage plus unit counts and a few live table counts.
create or replace view pipeline_status as
with last_run as (
    select distinct on (stage) stage, id as run_id, status, started_at, finished_at, stats, error
    from pipeline_runs order by stage, id desc
),
units as (
    select stage, count(*) as units_done, max(done_at) as last_unit_at from stage_progress group by stage
),
running as (
    select stage, count(*) as running from pipeline_runs where status = 'running' group by stage
)
select s.stage, l.run_id, coalesce(l.status, 'never') as status, l.started_at, l.finished_at, l.stats, l.error,
       coalesce(u.units_done, 0) as units_done, u.last_unit_at, coalesce(r.running, 0) > 0 as is_running,
       (select count(*) from pipeline_runs p where p.stage = s.stage) as runs
from (values ('discover'), ('dedupe'), ('collect_reviews'), ('collect_text'), ('match_reviews'),
             ('extract_insights'), ('review_sample'), ('freshness'), ('claim_readiness')) as s(stage)
left join last_run l on l.stage = s.stage
left join units u on u.stage = s.stage
left join running r on r.stage = s.stage;

create or replace view pipeline_counts as
select
  (select count(*) from raw_venues) as raw_venues,
  (select count(*) from venues where retired_at is null) as venues,
  (select count(*) from raw_reviews) as raw_reviews,
  (select count(*) from raw_reviews where source = 'infatuation') as raw_reviews_infatuation,
  (select count(*) from review_venue_links where decision = 'matched') as reviews_matched,
  (select count(*) from insights) as insights,
  (select count(*) from extraction_reviews) as verdicts,
  (select count(*) from claim_readiness) as claims_scored,
  (select count(*) from stage_progress where unit_key like 'infatuation:%') as infatuation_units;

grant select on pipeline_status, pipeline_counts to anon, authenticated;
