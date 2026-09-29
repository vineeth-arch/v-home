-- Studio (business command center): aggregate numbers only, written by the business-sync Edge Function (service role).
-- Members and paired displays of the household read them; no client can write.
create table public.business_metrics (
  household_id uuid not null references public.households(id) on delete cascade,
  key text not null,
  source text not null,
  label text not null,
  value numeric,
  detail jsonb not null default '{}',
  ok boolean not null default true,
  fetched_at timestamptz not null default now(),
  primary key (household_id, key)
);
alter table public.business_metrics enable row level security;
create policy bm_select on public.business_metrics for select to authenticated
  using (public.is_member(household_id) or public.is_display(household_id));
grant select on public.business_metrics to authenticated;
create trigger touch after insert or update or delete on public.business_metrics for each row execute function public.tg_touch_version();
-- business-sync runs as service_role: it checks membership and settings, and is the only writer of the metrics.
grant select on public.members, public.households to service_role;
grant select, insert, update, delete on public.business_metrics to service_role;
