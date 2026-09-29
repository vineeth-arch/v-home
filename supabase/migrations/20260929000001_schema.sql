-- V/HOME schema. Every content row is household-scoped, attributed, revisioned.

create table public.households (
  id uuid primary key default gen_random_uuid(),
  name text not null default 'Our Home',
  timezone text not null default 'Asia/Kolkata',
  settings jsonb not null default '{}',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  revision int not null default 1
);

-- role 'member' = a person (real account); 'display' = a paired TV (anonymous auth user)
create table public.members (
  household_id uuid not null references public.households(id) on delete cascade,
  user_id uuid not null unique references auth.users(id) on delete cascade,
  role text not null check (role in ('member', 'display')),
  display_name text not null default '',
  created_at timestamptz not null default now(),
  primary key (household_id, user_id)
);

create table public.invites (
  token uuid primary key default gen_random_uuid(),
  household_id uuid not null references public.households(id) on delete cascade,
  created_by uuid not null,
  expires_at timestamptz not null default now() + interval '7 days',
  used_by uuid,
  used_at timestamptz
);

create table public.display_pairings (
  code text primary key,
  tv_user_id uuid not null references auth.users(id) on delete cascade,
  household_id uuid references public.households(id) on delete cascade,
  expires_at timestamptz not null,
  approved_at timestamptz
);

-- One row per household. Bumped on EVERY content write so the TV can detect hides/deletes
-- (realtime row events are filtered by RLS and cannot report a row becoming invisible).
create table public.household_versions (
  household_id uuid primary key references public.households(id) on delete cascade,
  version bigint not null default 1
);

-- Shared content tables. show_on_tv defaults false for personal content (notes, dreams).
do $$
declare t record;
begin
  for t in select * from (values
    ('events', 'title text not null, starts_at timestamptz not null, all_day boolean not null default false', true),
    ('tasks', 'title text not null, owner text not null default ''both'', kind text not null default ''task'' check (kind in (''task'',''grocery'')), done boolean not null default false', true),
    ('notes', 'body text not null', false),
    ('dreams', 'title text not null, why text not null default '''', affirmation text not null default '''', next_step text not null default '''', target_date date, art text not null default ''sun'', image_path text', false),
    ('dream_steps', 'dream_id uuid not null references public.dreams(id) on delete cascade, title text not null, done boolean not null default false', true),
    ('ideas', 'title text not null, note text not null default '''', status text not null default ''new'' check (status in (''new'',''discuss'',''planned'',''archived'')), link text, image_path text, pinned boolean not null default false', true),
    ('watch_entries', 'tmdb_id bigint, type text not null check (type in (''movie'',''series'')), title text not null, summary text, runtime_min int, mood text, service text, watched boolean not null default false, metadata jsonb not null default ''{}'', providers jsonb not null default ''{}'', providers_updated_at timestamptz, poster_path text', true),
    ('quotes', 'slot text not null check (slot in (''morning'',''evening'')), body text not null, author text, source text, favorite boolean not null default false, hidden boolean not null default false', true),
    ('ritual_selections', 'day date not null, slot text not null, payload jsonb not null default ''{}''', true)
  ) as v(name, cols, tv_default)
  loop
    execute format($f$create table public.%I (
      id uuid primary key default gen_random_uuid(),
      household_id uuid not null references public.households(id) on delete cascade,
      author_id uuid not null default auth.uid(),
      created_at timestamptz not null default now(),
      updated_at timestamptz not null default now(),
      revision int not null default 1,
      visibility text not null default 'shared' check (visibility in ('draft', 'shared')),
      show_on_tv boolean not null default %s,
      %s)$f$, t.name, t.tv_default::text, t.cols);
    execute format('create index on public.%I (household_id)', t.name);
  end loop;
end $$;

-- Each member's independent vote. TVs can never write here.
create table public.watch_prefs (
  entry_id uuid not null references public.watch_entries(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  household_id uuid not null references public.households(id) on delete cascade,
  pref text not null check (pref in ('want', 'maybe', 'pass')),
  updated_at timestamptz not null default now(),
  primary key (entry_id, user_id)
);

-- Image metadata. Storage policy joins this table so the TV only fetches approved images.
create table public.media (
  path text primary key,
  household_id uuid not null references public.households(id) on delete cascade,
  author_id uuid not null default auth.uid(),
  show_on_tv boolean not null default false,
  created_at timestamptz not null default now()
);
create index on public.media (household_id);
