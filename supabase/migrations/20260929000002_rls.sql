-- Helpers. SECURITY DEFINER so policies can read members without recursion; search_path pinned.
create function public.is_member(hh uuid) returns boolean
language sql stable security definer set search_path = '' as $$
  select exists (select 1 from public.members m where m.household_id = hh and m.user_id = auth.uid() and m.role = 'member')
$$;
create function public.is_display(hh uuid) returns boolean
language sql stable security definer set search_path = '' as $$
  select exists (select 1 from public.members m where m.household_id = hh and m.user_id = auth.uid() and m.role = 'display')
$$;
create function public.is_real_user() returns boolean
language sql stable set search_path = '' as $$
  select auth.uid() is not null and coalesce((auth.jwt() ->> 'is_anonymous')::boolean, false) = false
$$;

-- Immutable identity columns + revision bump on every update.
create function public.tg_bump() returns trigger language plpgsql set search_path = '' as $$
begin
  new.id := old.id; new.household_id := old.household_id; new.author_id := old.author_id; new.created_at := old.created_at;
  new.revision := old.revision + 1; new.updated_at := now();
  return new;
end $$;
create function public.tg_bump_household() returns trigger language plpgsql set search_path = '' as $$
begin
  new.id := old.id; new.created_at := old.created_at; new.revision := old.revision + 1; new.updated_at := now();
  return new;
end $$;

-- Version bump so TVs notice ANY change, including rows that became hidden or were deleted.
create function public.tg_touch_version() returns trigger language plpgsql security definer set search_path = '' as $$
declare hh uuid;
begin
  hh := case when tg_op = 'DELETE' then old.household_id else new.household_id end;
  insert into public.household_versions (household_id) values (hh)
    on conflict (household_id) do update set version = public.household_versions.version + 1;
  return null;
end $$;
create function public.tg_touch_version_hh() returns trigger language plpgsql security definer set search_path = '' as $$
begin
  insert into public.household_versions (household_id) values (new.id)
    on conflict (household_id) do update set version = public.household_versions.version + 1;
  return null;
end $$;

create trigger bump before update on public.households for each row execute function public.tg_bump_household();
create trigger touch after update on public.households for each row execute function public.tg_touch_version_hh();
create trigger touch after insert or delete on public.members for each row execute function public.tg_touch_version();
create trigger touch after insert or update or delete on public.media for each row execute function public.tg_touch_version();
create trigger touch after insert or update or delete on public.watch_prefs for each row execute function public.tg_touch_version();

alter table public.households enable row level security;
alter table public.members enable row level security;
alter table public.invites enable row level security;
alter table public.display_pairings enable row level security;
alter table public.household_versions enable row level security;
alter table public.watch_prefs enable row level security;
alter table public.media enable row level security;

-- households: members and displays read; members edit. Creation only through create_household().
create policy hh_select on public.households for select to authenticated using (public.is_member(id) or public.is_display(id));
create policy hh_update on public.households for update to authenticated using (public.is_member(id)) with check (public.is_member(id));
-- members: read-only to clients (RPC-only writes). invites, pairings: no client policies at all.
create policy members_select on public.members for select to authenticated using (public.is_member(household_id) or public.is_display(household_id));
create policy versions_select on public.household_versions for select to authenticated using (public.is_member(household_id) or public.is_display(household_id));

-- watch_prefs: visibility follows the entry's own RLS. Only a member writes, only their own row.
create policy prefs_select on public.watch_prefs for select to authenticated
  using (exists (select 1 from public.watch_entries e where e.id = watch_prefs.entry_id));
create policy prefs_insert on public.watch_prefs for insert to authenticated
  with check (user_id = auth.uid() and public.is_member(household_id)
    and exists (select 1 from public.watch_entries e where e.id = entry_id and e.household_id = watch_prefs.household_id));
create policy prefs_update on public.watch_prefs for update to authenticated
  using (user_id = auth.uid() and public.is_member(household_id)) with check (user_id = auth.uid() and public.is_member(household_id));
create policy prefs_delete on public.watch_prefs for delete to authenticated using (user_id = auth.uid() and public.is_member(household_id));

-- media
create policy media_member_select on public.media for select to authenticated using (public.is_member(household_id));
create policy media_display_select on public.media for select to authenticated using (public.is_display(household_id) and show_on_tv);
create policy media_insert on public.media for insert to authenticated with check (public.is_member(household_id) and author_id = auth.uid());
create policy media_update on public.media for update to authenticated using (public.is_member(household_id)) with check (public.is_member(household_id));
create policy media_delete on public.media for delete to authenticated using (public.is_member(household_id));

-- content tables
do $$
declare t text;
begin
  foreach t in array array['events','tasks','notes','dreams','dream_steps','ideas','watch_entries','quotes','ritual_selections']
  loop
    execute format('alter table public.%I enable row level security', t);
    execute format('create trigger bump before update on public.%I for each row execute function public.tg_bump()', t);
    execute format('create trigger touch after insert or update or delete on public.%I for each row execute function public.tg_touch_version()', t);
    -- members see shared rows plus their own drafts
    execute format($p$create policy member_select on public.%I for select to authenticated
      using (public.is_member(household_id) and (visibility = 'shared' or author_id = auth.uid()))$p$, t);
    -- displays see only rows explicitly approved for TV
    execute format($p$create policy display_select on public.%I for select to authenticated
      using (public.is_display(household_id) and visibility = 'shared' and show_on_tv)$p$, t);
    execute format($p$create policy member_insert on public.%I for insert to authenticated
      with check (public.is_member(household_id) and author_id = auth.uid())$p$, t);
    -- only the author can turn a row into a draft; nobody edits another person's draft
    execute format($p$create policy member_update on public.%I for update to authenticated
      using (public.is_member(household_id) and (visibility = 'shared' or author_id = auth.uid()))
      with check (public.is_member(household_id) and (visibility = 'shared' or author_id = auth.uid()))$p$, t);
    execute format($p$create policy member_delete on public.%I for delete to authenticated
      using (public.is_member(household_id) and (visibility = 'shared' or author_id = auth.uid()))$p$, t);
  end loop;
end $$;

-- realtime: only the version row is published (never content)
do $$ begin
  if exists (select 1 from pg_publication where pubname = 'supabase_realtime') then
    alter publication supabase_realtime add table public.household_versions;
  end if;
end $$;

-- lock down: unauthenticated role gets nothing
revoke all on all tables in schema public from anon;
revoke all on all functions in schema public from public, anon;
alter default privileges in schema public revoke all on tables from anon;
alter default privileges in schema public revoke all on functions from anon;
grant execute on function public.is_member(uuid), public.is_display(uuid), public.is_real_user() to authenticated;

-- Explicit least-privilege grants (new Supabase projects no longer auto-grant table access).
-- RLS above decides which rows; these decide which verbs exist at all.
grant select, update on public.households to authenticated;
grant select on public.members, public.household_versions to authenticated;
grant select, insert, update, delete on
  public.events, public.tasks, public.notes, public.dreams, public.dream_steps, public.ideas,
  public.watch_entries, public.quotes, public.ritual_selections, public.watch_prefs, public.media
  to authenticated;
-- invites and display_pairings: no client grants; RPC only.
