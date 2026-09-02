-- Review page: one row per insight with its source text and any existing verdicts.
create or replace view review_queue as
select i.id as insight_id, i.venue_id, v.name as venue_name, r.source, r.url, r.text,
       i.model, i.prompt_version, i.vibe_tags, i.noise_level, i.crowd_level, i.best_time,
       i.recurring_events, i.good_for, i.sentiment, i.confidence, i.evidence, i.evidence_verbatim,
       i.raw_output->'dropped_fields' as dropped_fields, i.created_at,
       coalesce((select jsonb_object_agg(e.reviewer, jsonb_build_object('verdict', e.verdict, 'fields', e.field_verdicts, 'notes', e.notes))
                 from extraction_reviews e where e.insight_id = i.id), '{}'::jsonb) as verdicts
from insights i
join raw_reviews r on r.id = i.raw_review_id
left join venues v on v.id = i.venue_id;

grant select on review_queue to anon, authenticated;
grant select, insert, update on extraction_reviews to anon, authenticated;
grant usage, select on sequence extraction_reviews_id_seq to anon, authenticated;
