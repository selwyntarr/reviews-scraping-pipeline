-- Read models for the web explorer. Anon role reads these through PostgREST.

create table if not exists zip_neighborhoods (
    zip          text primary key,
    neighborhood text not null
);
insert into zip_neighborhoods (zip, neighborhood) values
('10001','Chelsea'),('10011','Chelsea'),('10002','Lower East Side'),('10003','East Village'),('10009','East Village'),
('10004','Financial District'),('10005','Financial District'),('10006','Financial District'),('10007','Tribeca'),
('10038','Financial District'),('10280','Battery Park City'),('10282','Battery Park City'),('10013','Tribeca'),
('10012','SoHo'),('10014','West Village'),('10010','Gramercy'),('10016','Murray Hill'),('10017','Midtown East'),
('10022','Midtown East'),('10018','Garment District'),('10036','Theater District'),('10019','Midtown West'),
('10020','Midtown'),('10103','Midtown'),('10111','Midtown'),('10112','Midtown'),('10152','Midtown East'),
('10153','Midtown East'),('10154','Midtown East'),('10155','Midtown East'),('10165','Midtown East'),('10166','Midtown East'),
('10167','Midtown East'),('10168','Midtown East'),('10169','Midtown East'),('10170','Midtown East'),('10171','Midtown East'),
('10172','Midtown East'),('10173','Midtown East'),('10174','Midtown East'),('10177','Midtown East'),('10021','Upper East Side'),
('10028','Upper East Side'),('10065','Upper East Side'),('10075','Upper East Side'),('10128','Upper East Side'),
('10023','Upper West Side'),('10024','Upper West Side'),('10025','Upper West Side'),('10069','Upper West Side'),
('10026','Harlem'),('10027','Harlem'),('10030','Harlem'),('10037','Harlem'),('10039','Harlem'),('10029','East Harlem'),
('10035','East Harlem'),('10031','Hamilton Heights'),('10032','Washington Heights'),('10033','Washington Heights'),
('10040','Washington Heights'),('10034','Inwood'),('10044','Roosevelt Island'),('10162','Upper East Side'),
('10115','Morningside Heights'),('10119','Chelsea'),('10121','Chelsea'),('10122','Chelsea'),('10123','Chelsea'),
('10271','Financial District'),('10278','Civic Center'),('10279','Financial District'),('10281','Battery Park City')
on conflict (zip) do nothing;

create or replace view venue_map as
select v.id, v.name, v.category, v.lat, v.lon, v.zip,
       coalesce(
           (select r.neighborhood from review_venue_links l join raw_reviews r on r.id = l.raw_review_id
             where l.venue_id = v.id and r.neighborhood is not null order by r.source limit 1),
           zn.neighborhood) as neighborhood,
       exists (select 1 from insights i where i.venue_id = v.id) as has_insights
from venues v
left join zip_neighborhoods zn on zn.zip = v.zip
where v.retired_at is null and v.lat is not null;

create or replace view venue_evidence as
select i.venue_id, r.source, r.url, r.venue_name as source_title, r.published_at,
       e->>'field' as field, e->>'quote' as quote, i.prompt_version, i.model
from insights i
join raw_reviews r on r.id = i.raw_review_id
cross join lateral jsonb_array_elements(i.evidence) e
where i.venue_id is not null;

grant select on venue_map, venue_profiles, venue_evidence, claim_readiness, zip_neighborhoods to anon, authenticated;
