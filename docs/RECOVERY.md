# Recovering V/HOME

Your shared content lives in the cloud (Supabase project `kqmiuhnaeoshjynsttwa`). The TV only caches a copy.

## The TV shows "Pair this TV"
1. Read the 6-character code on the TV (it stays the same for 10 minutes, then refreshes).
2. On the phone open V/HOME, then **Displays**, and enter the code (or scan the QR).
3. Your content returns within a few seconds. Nothing is lost.

## The TV was reset or Developer Mode expired
See `docs/DEV-MODE.md`, then pair again as above.

## Roll back the TV app
Keep the previous `.ipk` from `build/` and run `node_modules/.bin/ares-install --device tv <file.ipk>` (upgrade in place).

## Export and import
Phone, **Settings**, **Backup**: Export household downloads one JSON file. Import adds those items to the current household with new IDs. Photos are not included yet.

## Change or rotate the database password
Supabase dashboard, Project Settings, Database, Reset database password. Then run `supabase link --project-ref kqmiuhnaeoshjynsttwa` again on the Mac when it asks.

## The free Supabase project paused (about 7 days of no use)
Open the Supabase dashboard and press **Restore project**. The TV keeps showing its last saved content while paused, with a "Showing saved content" note.

## A partner lost their phone or password
Sign in on a new phone. If the password is lost, use Supabase dashboard, Authentication, Users, and send a password reset.
