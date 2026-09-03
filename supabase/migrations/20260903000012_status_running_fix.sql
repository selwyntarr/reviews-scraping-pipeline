-- is_running should reflect the latest run only; orphaned 'running' rows from a crashed process must not
-- keep a stage marked as running forever.
create or replace view pipeline_status as
with last_run as (
    select distinct on (stage) stage, id as run_id, status, started_at, finished_at, stats, error
    from pipeline_runs order by stage, id desc
),
units as (
    select stage, count(*) as units_done, max(done_at) as last_unit_at from stage_progress group by stage
)
select s.stage, l.run_id, coalesce(l.status, 'never') as status, l.started_at, l.finished_at, l.stats, l.error,
       coalesce(u.units_done, 0) as units_done, u.last_unit_at,
       coalesce(l.status = 'running' and l.started_at > now() - interval '2 days', false) as is_running,
       (select count(*) from pipeline_runs p where p.stage = s.stage) as runs
from (values ('discover'), ('dedupe'), ('collect_reviews'), ('collect_text'), ('match_reviews'),
             ('extract_insights'), ('review_sample'), ('freshness'), ('claim_readiness')) as s(stage)
left join last_run l on l.stage = s.stage
left join units u on u.stage = s.stage;
