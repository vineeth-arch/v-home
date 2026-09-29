insert into storage.buckets (id, name, public) values ('household-media', 'household-media', false) on conflict (id) do nothing;

-- path = {household_id}/{uuid}.jpg. Folder guard uses a regex so a malformed path denies instead of erroring.
create policy media_obj_member_select on storage.objects for select to authenticated
  using (bucket_id = 'household-media' and (storage.foldername(name))[1] ~ '^[0-9a-f-]{36}$' and public.is_member(((storage.foldername(name))[1])::uuid));
create policy media_obj_member_insert on storage.objects for insert to authenticated
  with check (bucket_id = 'household-media' and (storage.foldername(name))[1] ~ '^[0-9a-f-]{36}$' and public.is_member(((storage.foldername(name))[1])::uuid));
create policy media_obj_member_delete on storage.objects for delete to authenticated
  using (bucket_id = 'household-media' and (storage.foldername(name))[1] ~ '^[0-9a-f-]{36}$' and public.is_member(((storage.foldername(name))[1])::uuid));
-- TV: only files whose media row is approved for TV
create policy media_obj_display_select on storage.objects for select to authenticated
  using (bucket_id = 'household-media' and exists (
    select 1 from public.media m where m.path = storage.objects.name and m.show_on_tv and public.is_display(m.household_id)));
