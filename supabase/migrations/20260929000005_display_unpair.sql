-- A TV can unpair itself (Settings > Unpair). Members still revoke via revoke_display().
create function public.display_unpair() returns void
language plpgsql security definer set search_path = '' as $$
begin
  if auth.uid() is null or public.is_real_user() then raise exception 'displays only'; end if;
  delete from public.members where user_id = auth.uid() and role = 'display';
end $$;
revoke all on function public.display_unpair() from public, anon;
grant execute on function public.display_unpair() to authenticated;
