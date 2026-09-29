-- Run in the form engine project (SQL editor, as postgres). Counts only.
create or replace function public.di_studio_summary() returns jsonb
language sql stable security definer set search_path = public as $$
  select jsonb_build_array(
    jsonb_build_object('key', 'forms_with_clients', 'label', 'Questionnaires with clients', 'value',
      (select count(*) from public.assignments where status in ('draft', 'changes_requested'))),
    jsonb_build_object('key', 'forms_late', 'label', 'Questionnaires past due', 'value',
      (select count(*) from public.assignments where status in ('draft', 'changes_requested') and due_at < (now() at time zone 'Asia/Kolkata')::date),
      'detail', jsonb_build_object('attention', true)),
    jsonb_build_object('key', 'forms_to_review', 'label', 'Answers to review', 'value',
      (select count(*) from public.assignments where status = 'submitted'), 'detail', jsonb_build_object('attention', true))
  )
$$;
revoke all on function public.di_studio_summary() from public, anon, authenticated;
