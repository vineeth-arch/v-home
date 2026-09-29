-- Run in the outreach cockpit project (SQL editor, as postgres). Brand names are returned for "Today's 3";
-- V/HOME drops them unless "Show names" is on in the phone's Studio settings.
create or replace function public.di_studio_summary() returns jsonb
language sql stable security definer set search_path = public as $$
  with d as (select (now() at time zone 'Asia/Kolkata')::date as today),
  w as (select today, today + (6 - (extract(isodow from today)::int - 1)) as sunday from d),
  due as (
    select f.due_date, p.stage::text as stage, p.brand_name
    from public.followups f join public.prospects p on p.id = f.prospect_id, w
    where f.status = 'Pending' and f.due_date <= w.sunday
  )
  select jsonb_build_array(
    jsonb_build_object('key', 'followups_now', 'label', 'Follow-ups due now', 'value',
      (select count(*) from due, w where due.due_date <= w.today), 'detail', jsonb_build_object('attention', true)),
    jsonb_build_object('key', 'followups_week', 'label', 'Follow-ups this week', 'value', (select count(*) from due)),
    jsonb_build_object('key', 'leads_open', 'label', 'Leads in play', 'value',
      (select count(*) from public.prospects where stage not in ('Won', 'Passed')),
      'detail', jsonb_build_object('byStage', (select coalesce(jsonb_object_agg(stage, n), '{}') from
        (select stage::text as stage, count(*) as n from public.prospects where stage not in ('Won', 'Passed') group by stage) s))),
    jsonb_build_object('key', 'followups_next', 'label', 'Next follow-ups', 'value', (select least(count(*), 3) from due),
      'detail', jsonb_build_object('items', (select coalesce(jsonb_agg(jsonb_build_object('due', due_date, 'stage', stage, 'name', brand_name) order by due_date), '[]')
        from (select * from due order by due_date limit 3) t)))
  )
$$;
revoke all on function public.di_studio_summary() from public, anon, authenticated;
