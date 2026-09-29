# Studio: Design Innsaeit numbers on the TV

Studio is a TV screen with a few business numbers. It shows only on work days during work hours (default Mon to Fri, 09:00 to 18:00). It never shows in guest view.

## How it stays safe

- The TV and phone never hold business credentials.
- The `business-sync` Edge Function in the V/HOME project connects to each business project as `studio_reader`. That role can do one thing only: call `public.di_studio_summary()`. It can't read, change or delete any table.
- The summary functions return totals and counts. The outreach summary also returns the brand names of the next 3 follow-ups. V/HOME drops those names unless "Show brand names" is on in the phone's Studio settings.
- Connection strings live only in Supabase secrets. Never paste them in chat or commit them.
- Only the household named in `STUDIO_HOUSEHOLD_ID` gets Studio.
- Numbers refresh while Studio is on screen: at most every 15 min from the TV, and at most once a minute from the phone's "Refresh now".

## Setup (about 15 minutes)

### 1. In each business project (Supabase dashboard → SQL editor)

| Source | Project | Summary file |
|---|---|---|
| Invoices | GST Invoice Studio (`wdjnhtpzlqmsuoqlzypm`) | `supabase/studio/invoices.sql` |
| Outreach | di-outreach-cockpit | `supabase/studio/outreach.sql` |
| Questionnaires | di-form-engine (`chhmyvcmwgtuybqmemzr`) | `supabase/studio/forms.sql` |

For each project:

1. Paste and run that project's summary file from the table.
2. Create the read-only role. Use a new long password for each project:

   ```sql
   create role studio_reader with login password 'PICK-A-LONG-RANDOM-PASSWORD';
   grant usage on schema public to studio_reader;
   grant execute on function public.di_studio_summary() to studio_reader;
   ```

3. Check it works:

   ```sql
   select public.di_studio_summary();
   ```

   The numbers should look right.

4. Copy the connection string from **Connect → Transaction pooler**. Change the user from `postgres.<ref>` to `studio_reader.<ref>` and put in the password from step 2.

### 2. In the V/HOME folder, set the secrets

First find your household ID: in the V/HOME project SQL editor, run `select id, name from households;`.

```bash
supabase secrets set STUDIO_HOUSEHOLD_ID=<your household id>
supabase secrets set STUDIO_INVOICES_DB='<invoices connection string>'
supabase secrets set STUDIO_OUTREACH_DB='<outreach connection string>'
supabase secrets set STUDIO_FORMS_DB='<forms connection string>'
```

You can skip any source. Studio then shows the others and marks the skipped one "not connected".

### 3. On the phone

Go to Settings → Studio (business on the TV). Then:

1. Tick "Show Studio on the TV".
2. Check the work days and hours.
3. Press Save Studio.
4. Press Refresh now.

## What the numbers mean

| Tile | Rule |
|---|---|
| **Waiting to be paid / Unpaid invoices** | Issued invoices (status FINAL) minus what's been cleared (base plus GST). Leaves out drafts, paid, cancelled, test invoices, credit notes and proformas. |
| **Past their due date** | Unpaid invoices whose due date is before today (IST). |
| **Totals caveat** | Invoice Studio saves in the browser first. Only invoices that have synced to its Supabase are counted. |
| **Follow-ups due now / this week** | Pending follow-ups due today or earlier, or by this Sunday. |
| **Leads in play** | Prospects not Won or Passed. |
| **Questionnaires with clients** | Assignments in draft or changes requested. |
| **Answers to review** | Assignments with status submitted. |

Amber means "needs you". Nothing is ever red, and there are no charts or streaks.

## Turn it off

- **Hide it for now:** untick "Show Studio on the TV" on the phone.
- **Revoke access:** in the business project, run:

  ```sql
  drop owned by studio_reader;
  drop role studio_reader;
  ```

  Then remove the secret, for example `supabase secrets unset STUDIO_FORMS_DB`.
