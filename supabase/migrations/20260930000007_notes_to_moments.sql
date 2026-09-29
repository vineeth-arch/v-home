-- A note can be addressed to one partner (from = author_id). Moments: standalone photos with an optional date and caption.
alter table public.notes add column to_user uuid;
alter table public.media add column taken_on date, add column caption text;
