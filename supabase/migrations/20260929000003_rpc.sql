-- Member-only RPCs reject anonymous (TV) callers. All pin search_path and qualify names.

create function public.create_household(p_name text, p_display_name text) returns uuid
language plpgsql security definer set search_path = '' as $$
declare hh uuid;
begin
  if not public.is_real_user() then raise exception 'sign in required'; end if;
  insert into public.households (name) values (coalesce(nullif(trim(p_name), ''), 'Our Home')) returning id into hh;
  insert into public.members (household_id, user_id, role, display_name) values (hh, auth.uid(), 'member', trim(p_display_name));
  insert into public.household_versions (household_id) values (hh) on conflict do nothing;
  return hh;
end $$;

create function public.create_invite(p_hh uuid) returns uuid
language plpgsql security definer set search_path = '' as $$
declare tok uuid;
begin
  if not public.is_real_user() or not public.is_member(p_hh) then raise exception 'not allowed'; end if;
  insert into public.invites (household_id, created_by) values (p_hh, auth.uid()) returning token into tok;
  return tok;
end $$;

create function public.accept_invite(p_token uuid, p_display_name text) returns uuid
language plpgsql security definer set search_path = '' as $$
declare inv public.invites%rowtype;
begin
  if not public.is_real_user() then raise exception 'sign in required'; end if;
  select * into inv from public.invites where token = p_token for update;
  if not found or inv.used_at is not null or inv.expires_at < now() then raise exception 'invite invalid or expired'; end if;
  if (select count(*) from public.members where household_id = inv.household_id and role = 'member') >= 2 then raise exception 'household is full'; end if;
  if exists (select 1 from public.members where user_id = auth.uid()) then raise exception 'already in a household'; end if;
  insert into public.members (household_id, user_id, role, display_name) values (inv.household_id, auth.uid(), 'member', trim(p_display_name));
  update public.invites set used_by = auth.uid(), used_at = now() where token = p_token;
  return inv.household_id;
end $$;

create function public.set_display_name(p_name text) returns void
language plpgsql security definer set search_path = '' as $$
begin
  if not public.is_real_user() then raise exception 'sign in required'; end if;
  update public.members set display_name = trim(p_name) where user_id = auth.uid() and role = 'member';
end $$;

-- TV: get a short-lived code (alphabet has no 0/O/1/I/L). Must be an anonymous session.
create function public.start_pairing() returns text
language plpgsql security definer set search_path = '' as $$
declare alphabet constant text := 'ABCDEFGHJKMNPQRSTUVWXYZ23456789'; c text; b bytea; i int; tries int := 0;
begin
  if auth.uid() is null or public.is_real_user() then raise exception 'displays only'; end if;
  delete from public.display_pairings where tv_user_id = auth.uid() or expires_at < now();
  loop
    b := uuid_send(gen_random_uuid());
    c := '';
    for i in 0..5 loop c := c || substr(alphabet, (get_byte(b, i) % length(alphabet)) + 1, 1); end loop;
    begin
      insert into public.display_pairings (code, tv_user_id, expires_at) values (c, auth.uid(), now() + interval '10 minutes');
      return c;
    exception when unique_violation then
      tries := tries + 1;
      if tries > 5 then raise; end if;
    end;
  end loop;
end $$;

-- Member approves the code shown on the TV.
create function public.approve_pairing(p_code text, p_hh uuid) returns void
language plpgsql security definer set search_path = '' as $$
declare p public.display_pairings%rowtype;
begin
  if not public.is_real_user() or not public.is_member(p_hh) then raise exception 'not allowed'; end if;
  select * into p from public.display_pairings where code = upper(trim(p_code)) for update;
  if not found or p.approved_at is not null or p.expires_at < now() then raise exception 'code invalid or expired'; end if;
  if (select count(*) from public.members where household_id = p_hh and role = 'display') >= 5 then raise exception 'too many displays'; end if;
  if exists (select 1 from public.members where user_id = p.tv_user_id) then raise exception 'display already paired'; end if;
  insert into public.members (household_id, user_id, role, display_name) values (p_hh, p.tv_user_id, 'display', 'TV');
  update public.display_pairings set approved_at = now(), household_id = p_hh where code = p.code;
end $$;

-- TV polls this until approved; returns household id or null.
create function public.pairing_status() returns uuid
language sql stable security definer set search_path = '' as $$
  select m.household_id from public.members m where m.user_id = auth.uid() and m.role = 'display'
$$;

create function public.revoke_display(p_hh uuid, p_tv uuid) returns void
language plpgsql security definer set search_path = '' as $$
begin
  if not public.is_real_user() or not public.is_member(p_hh) then raise exception 'not allowed'; end if;
  delete from public.members where household_id = p_hh and user_id = p_tv and role = 'display';
end $$;

-- TV's only writes. Row must be shared and approved for TV.
create function public.tv_complete_task(p_id uuid) returns void
language plpgsql security definer set search_path = '' as $$
begin
  update public.tasks t set done = true
   where t.id = p_id and t.visibility = 'shared' and t.show_on_tv and public.is_display(t.household_id);
  if not found then raise exception 'not allowed'; end if;
end $$;
create function public.tv_mark_watched(p_id uuid) returns void
language plpgsql security definer set search_path = '' as $$
begin
  update public.watch_entries w set watched = true
   where w.id = p_id and w.visibility = 'shared' and w.show_on_tv and public.is_display(w.household_id);
  if not found then raise exception 'not allowed'; end if;
end $$;

do $$
declare f text;
begin
  foreach f in array array[
    'create_household(text,text)', 'create_invite(uuid)', 'accept_invite(uuid,text)', 'set_display_name(text)',
    'start_pairing()', 'approve_pairing(text,uuid)', 'pairing_status()', 'revoke_display(uuid,uuid)',
    'tv_complete_task(uuid)', 'tv_mark_watched(uuid)']
  loop
    execute format('revoke all on function public.%s from public, anon', f);
    execute format('grant execute on function public.%s to authenticated', f);
  end loop;
end $$;
