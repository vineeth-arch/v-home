-- Run in the GST Invoice Studio project (SQL editor, as postgres). Returns totals only, never client names.
-- Unpaid = FINAL (issued, not PAID/CANCELLED/DRAFT), not test, not a credit note or proforma; due = grandTotal minus cleared base and GST.
create or replace function public.di_studio_summary() returns jsonb
language sql stable security definer set search_path = public as $$
  with inv as (
    select coalesce((full_data->'totals'->>'grandTotal')::numeric, 0)
             - coalesce((full_data->>'baseClearedAmount')::numeric, 0)
             - coalesce((full_data->>'gstRecoveredAmount')::numeric, 0) as due,
           nullif(full_data->>'dueDate', '')::date as due_date
    from public.invoices
    where status = 'FINAL'
      and coalesce((full_data->>'isTest')::boolean, false) = false
      and coalesce(full_data->>'documentType', 'tax_invoice') not in ('credit_note', 'proforma')
  ), open as (select * from inv where due > 0.5)
  select jsonb_build_array(
    jsonb_build_object('key', 'invoices_open_count', 'label', 'Unpaid invoices', 'value', (select count(*) from open)),
    jsonb_build_object('key', 'invoices_open_total', 'label', 'Waiting to be paid', 'value', (select coalesce(round(sum(due)), 0) from open), 'detail', jsonb_build_object('unit', 'INR')),
    jsonb_build_object('key', 'invoices_overdue', 'label', 'Past their due date', 'value',
      (select count(*) from open where due_date < (now() at time zone 'Asia/Kolkata')::date), 'detail', jsonb_build_object('attention', true))
  )
$$;
revoke all on function public.di_studio_summary() from public, anon, authenticated;
