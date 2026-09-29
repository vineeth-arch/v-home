begin;
select plan(51);

-- identities -------------------------------------------------------------
insert into auth.users (id, aud, role, email, is_anonymous) values
  ('00000000-0000-0000-0000-00000000a11c', 'authenticated', 'authenticated', 'alice@test.local', false),
  ('00000000-0000-0000-0000-0000000000b0', 'authenticated', 'authenticated', 'bob@test.local', false),
  ('00000000-0000-0000-0000-00000000ca01', 'authenticated', 'authenticated', 'carol@test.local', false),
  ('00000000-0000-0000-0000-0000000000d4', 'authenticated', 'authenticated', 'dave@test.local', false),
  ('00000000-0000-0000-0000-000000007001', 'authenticated', 'authenticated', null, true),
  ('00000000-0000-0000-0000-000000007002', 'authenticated', 'authenticated', null, true);

create function pg_temp.act_as(uid uuid, anon boolean default false) returns void language plpgsql as $$
begin
  perform set_config('request.jwt.claims', json_build_object('sub', uid, 'role', 'authenticated', 'is_anonymous', anon)::text, true);
  perform set_config('role', 'authenticated', true);
end $$;
create function pg_temp.n(q text) returns int language plpgsql as $$
declare c int; begin execute q; get diagnostics c = row_count; return c; end $$;
create function pg_temp.g(k text) returns uuid language sql as $$ select current_setting('t.' || k)::uuid $$;

-- household 1: alice + bob, TV tv1. household 2: carol. ------------------
select pg_temp.act_as('00000000-0000-0000-0000-00000000a11c');
do $$ begin perform set_config('t.hh1', public.create_household('Home', 'Alice')::text, true); end $$;
do $$ begin perform set_config('t.inv1', public.create_invite(current_setting('t.hh1')::uuid)::text, true); end $$;

select pg_temp.act_as('00000000-0000-0000-0000-0000000000b0');
select lives_ok(format($$select public.accept_invite(%L, 'Bob')$$, current_setting('t.inv1')), 'bob joins via invite');

select pg_temp.act_as('00000000-0000-0000-0000-00000000ca01');
do $$ begin perform set_config('t.hh2', public.create_household('Other', 'Carol')::text, true); end $$;
select throws_ok(format($$select public.accept_invite(%L, 'Carol')$$, current_setting('t.inv1')), 'P0001', 'invite invalid or expired', 'used invite cannot be reused');

select pg_temp.act_as('00000000-0000-0000-0000-0000000000d4');
select throws_ok(format($$select public.create_invite(%L)$$, current_setting('t.hh1')), 'P0001', 'not allowed', 'non-member cannot create invite');

-- TV pairing -------------------------------------------------------------
select pg_temp.act_as('00000000-0000-0000-0000-000000007001', true);
do $$ begin perform set_config('t.code', public.start_pairing(), true); end $$;
select is(length(current_setting('t.code')), 6, 'pairing code is 6 chars');
select is(public.pairing_status(), null::uuid, 'unapproved TV has no household');
select throws_ok($$select public.accept_invite(gen_random_uuid(), 'x')$$, 'P0001', 'sign in required', 'anonymous TV cannot accept invites');
select throws_ok(format($$select public.create_invite(%L)$$, current_setting('t.hh1')), 'P0001', 'not allowed', 'anonymous TV cannot create invites');
select throws_ok($$select public.create_household('x', 'y')$$, 'P0001', 'sign in required', 'anonymous TV cannot create a household');

select pg_temp.act_as('00000000-0000-0000-0000-00000000ca01');
select throws_ok(format($$select public.approve_pairing(%L, %L)$$, current_setting('t.code'), current_setting('t.hh1')), 'P0001', 'not allowed', 'other household member cannot approve into hh1');

select pg_temp.act_as('00000000-0000-0000-0000-00000000a11c');
select lives_ok(format($$select public.approve_pairing(%L, %L)$$, current_setting('t.code'), current_setting('t.hh1')), 'alice approves the code');
select throws_ok(format($$select public.approve_pairing(%L, %L)$$, current_setting('t.code'), current_setting('t.hh1')), 'P0001', 'code invalid or expired', 'code cannot be reused');

reset role;
insert into public.display_pairings (code, tv_user_id, expires_at) values ('EXPIRD', '00000000-0000-0000-0000-000000007002', now() - interval '1 minute');
select pg_temp.act_as('00000000-0000-0000-0000-00000000a11c');
select throws_ok(format($$select public.approve_pairing('EXPIRD', %L)$$, current_setting('t.hh1')), 'P0001', 'code invalid or expired', 'expired code denied');

select pg_temp.act_as('00000000-0000-0000-0000-000000007001', true);
select is(public.pairing_status(), pg_temp.g('hh1'), 'approved TV sees its household');

-- content ----------------------------------------------------------------
select pg_temp.act_as('00000000-0000-0000-0000-00000000a11c');
do $$
declare hh uuid := current_setting('t.hh1')::uuid;
begin
  insert into public.events (household_id, title, starts_at) values (hh, 'Shared dinner', now() + interval '1 day');
  insert into public.notes (household_id, body, visibility) values (hh, 'alice private draft', 'draft');
  insert into public.dreams (household_id, title) values (hh, 'Hidden dream');             -- show_on_tv defaults false
  insert into public.tasks (household_id, title) values (hh, 'Visible task');
  insert into public.tasks (household_id, title, show_on_tv) values (hh, 'Hidden task', false);
  insert into public.watch_entries (household_id, type, title) values (hh, 'movie', 'A Film');
end $$;
select is((select count(*) from public.notes)::int, 1, 'alice sees her own draft');

select pg_temp.act_as('00000000-0000-0000-0000-0000000000b0');
select is((select count(*) from public.events)::int, 1, 'bob sees shared event');
select is((select count(*) from public.notes)::int, 0, 'bob does not see alice draft');
select is(pg_temp.n($$update public.notes set body = 'hacked'$$), 0, 'bob cannot edit alice draft');

select pg_temp.act_as('00000000-0000-0000-0000-00000000ca01');
select is((select count(*) from public.events)::int, 0, 'other household sees nothing');
select throws_ok(format($$insert into public.events (household_id, title, starts_at) values (%L, 'x', now())$$, current_setting('t.hh1')), '42501', null, 'other household cannot insert into hh1');
select throws_ok(format($$select public.revoke_display(%L, '00000000-0000-0000-0000-000000007001')$$, current_setting('t.hh1')), 'P0001', 'not allowed', 'other household cannot revoke our TV');

-- TV view ----------------------------------------------------------------
select pg_temp.act_as('00000000-0000-0000-0000-000000007001', true);
select is((select count(*) from public.events)::int, 1, 'TV sees shared event');
select is((select count(*) from public.notes)::int, 0, 'TV never sees drafts');
select is((select count(*) from public.dreams)::int, 0, 'TV does not see dream until Show on TV');
select is((select count(*) from public.tasks)::int, 1, 'TV sees only approved task');
select throws_ok(format($$insert into public.members (household_id, user_id, role) values (%L, '00000000-0000-0000-0000-000000007002', 'display')$$, current_setting('t.hh1')), '42501', null, 'TV cannot write members');
select is(pg_temp.n($$update public.tasks set done = true$$), 0, 'TV cannot update tasks directly');
select lives_ok($$select public.tv_complete_task((select id from public.tasks limit 1))$$, 'TV completes an approved task via RPC');
select throws_ok(format($$select public.tv_complete_task(%L)$$, (select 'a'::text)), '22P02', null, 'malformed id rejected');

-- alice approves the dream for TV, TV sees it, then hides again
select pg_temp.act_as('00000000-0000-0000-0000-00000000a11c');
update public.dreams set show_on_tv = true;
select pg_temp.act_as('00000000-0000-0000-0000-000000007001', true);
select is((select count(*) from public.dreams)::int, 1, 'TV sees dream after Show on TV');

-- votes are per member ---------------------------------------------------
select pg_temp.act_as('00000000-0000-0000-0000-00000000a11c');
insert into public.watch_prefs (entry_id, user_id, household_id, pref)
  select id, auth.uid(), household_id, 'want' from public.watch_entries;
select pg_temp.act_as('00000000-0000-0000-0000-0000000000b0');
select throws_ok($$insert into public.watch_prefs (entry_id, user_id, household_id, pref) select id, '00000000-0000-0000-0000-00000000a11c', household_id, 'pass' from public.watch_entries$$, '42501', null, 'bob cannot vote as alice');
insert into public.watch_prefs (entry_id, user_id, household_id, pref) select id, auth.uid(), household_id, 'maybe' from public.watch_entries;
select is((select count(distinct pref) from public.watch_prefs)::int, 2, 'each member has an independent vote');
select pg_temp.act_as('00000000-0000-0000-0000-000000007001', true);
select throws_ok($$insert into public.watch_prefs (entry_id, user_id, household_id, pref) select id, auth.uid(), household_id, 'want' from public.watch_entries$$, '42501', null, 'TV cannot vote');

-- revisions, immutability, version bump ---------------------------------
select pg_temp.act_as('00000000-0000-0000-0000-00000000a11c');
select is(pg_temp.n($$update public.events set title = 'stale' where revision = 99$$), 0, 'stale revision updates nothing');
update public.events set title = 'fresh' where revision = 1;
select is((select revision from public.events limit 1), 2, 'good update bumps revision');
update public.events set household_id = current_setting('t.hh2')::uuid;
select is((select household_id from public.events limit 1), pg_temp.g('hh1'), 'household_id is immutable');
reset role;
select ok((select version from public.household_versions where household_id = current_setting('t.hh1')::uuid) > 1, 'household version bumped by writes');

-- revoke ----------------------------------------------------------------
select pg_temp.act_as('00000000-0000-0000-0000-00000000a11c');
select lives_ok(format($$select public.revoke_display(%L, '00000000-0000-0000-0000-000000007001')$$, current_setting('t.hh1')), 'alice revokes the TV');
select pg_temp.act_as('00000000-0000-0000-0000-000000007001', true);
select is((select count(*) from public.events)::int, 0, 'revoked TV sees nothing');

-- weekly check-in: a second selection for the same household/day/slot is rejected
select pg_temp.act_as('00000000-0000-0000-0000-00000000a11c');
insert into public.ritual_selections (household_id, day, slot) values (current_setting('t.hh1')::uuid, '2026-09-28', 'weekly');
select throws_ok(format($$insert into public.ritual_selections (household_id, day, slot) values (%L, '2026-09-28', 'weekly')$$, current_setting('t.hh1')), '23505', null, 'duplicate weekly selection rejected');
select lives_ok(format($$insert into public.ritual_selections (household_id, day, slot) values (%L, '2026-09-29', 'weekly')$$, current_setting('t.hh1')), 'different day is fine');

-- photos: a TV can read a storage object only when its media row is approved for TV
reset role;
insert into public.media (path, household_id, author_id, show_on_tv) values
  (current_setting('t.hh1') || '/shown.jpg', current_setting('t.hh1')::uuid, '00000000-0000-0000-0000-00000000a11c', true),
  (current_setting('t.hh1') || '/hidden.jpg', current_setting('t.hh1')::uuid, '00000000-0000-0000-0000-00000000a11c', false);
insert into storage.objects (bucket_id, name, owner) values
  ('household-media', current_setting('t.hh1') || '/shown.jpg', '00000000-0000-0000-0000-00000000a11c'),
  ('household-media', current_setting('t.hh1') || '/hidden.jpg', '00000000-0000-0000-0000-00000000a11c');
insert into public.members (household_id, user_id, role, display_name) values (current_setting('t.hh1')::uuid, '00000000-0000-0000-0000-000000007002', 'display', 'TV3') on conflict do nothing;
select pg_temp.act_as('00000000-0000-0000-0000-000000007002', true);
select is((select count(*) from storage.objects where bucket_id = 'household-media')::int, 1, 'TV sees only the approved photo');
select is((select name from storage.objects where bucket_id = 'household-media'), current_setting('t.hh1') || '/shown.jpg', 'and it is the approved one');
select pg_temp.act_as('00000000-0000-0000-0000-00000000a11c');
select is((select count(*) from storage.objects where bucket_id = 'household-media')::int, 2, 'a member sees both photos');
select pg_temp.act_as('00000000-0000-0000-0000-00000000ca01');
select is((select count(*) from storage.objects where bucket_id = 'household-media')::int, 0, 'another household sees no photos');
reset role;
update public.media set show_on_tv = true where path like '%/hidden.jpg';
select pg_temp.act_as('00000000-0000-0000-0000-000000007002', true);
select is((select count(*) from storage.objects where bucket_id = 'household-media')::int, 2, 'TV sees the photo once Show on TV is on');
reset role;
delete from public.members where user_id = '00000000-0000-0000-0000-000000007002';

-- a TV can unpair itself (fresh pairing first)
reset role;
insert into public.members (household_id, user_id, role, display_name) values (current_setting('t.hh1')::uuid, '00000000-0000-0000-0000-000000007002', 'display', 'TV2');
select pg_temp.act_as('00000000-0000-0000-0000-000000007002', true);
select lives_ok($$select public.display_unpair()$$, 'TV unpairs itself');
select is(public.pairing_status(), null::uuid, 'unpaired TV has no household');

-- Studio metrics: household reads, nobody writes, other households see nothing ---------------
reset role;
insert into public.business_metrics (household_id, key, source, label, value) values (current_setting('t.hh1')::uuid, 'invoices_open_count', 'invoices', 'Unpaid invoices', 3);
select pg_temp.act_as('00000000-0000-0000-0000-00000000a11c');
select is((select count(*) from public.business_metrics)::int, 1, 'a member reads Studio metrics');
select throws_ok($$insert into public.business_metrics (household_id, key, source, label, value) values (current_setting('t.hh1')::uuid, 'x', 'x', 'x', 1)$$, '42501', null, 'a member cannot write Studio metrics');
select pg_temp.act_as('00000000-0000-0000-0000-00000000ca01');
select is((select count(*) from public.business_metrics)::int, 0, 'another household sees no Studio metrics');
reset role;

-- anon role (no login) ----------------------------------------------------
reset role;
set local role anon;
select throws_ok('select * from public.events', '42501', null, 'unauthenticated role denied');

select * from finish();
rollback;
