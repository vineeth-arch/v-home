# V/HOME — plan rev 3: remaining V1 features

> Rev 2 history and progress live in `v-home/docs/PLAN.md`. This file covers only what is left. Executor: Sonnet. Commit after each task with the attribution line, push to `main` when a phase is green.

## Context

- **Built and deployed:**
  - Phone app on Vercel (`v-home-psi.vercel.app`)
  - Cloud Supabase `kqmiuhnaeoshjynsttwa`: 5 migrations, 41 pgTAP tests
  - TV app with pairing and sync
  - IPK: `build/com.designinnsaeit.vhome_0.1.0_all.ipk`
- **Verified by Vineeth:** signed up, created a household, made an invite link, and added content on the phone.
- **TV not reachable right now.** 2026-09-29: ping to 192.168.29.224 gets no reply, and ports 9922/3001 are closed. The Mac is on the same subnet (.216). His photo shows "The device will be restarted", so the TV is most likely rebooting after a Developer Mode change.
- **Five items left in V1:** photos, TMDB + weather, fonts, three missing phone screens, and four docs.

## Review pass: what would have failed in rev 3 draft, and the fix now in this plan

| # | Would fail | Fix |
|---|---|---|
| 1 | TV pairing code regenerates every 3 s (stale `code` in `live.ts` closure). The code can never be entered. | Task 0a: loop-local variable, plus a unit test. |
| 2 | TV never recovers if it boots before Wi-Fi is up. | Task 0b: boot retry with backoff. |
| 3 | The QR opens `/pair`, which is a 404 on Vercel's static hosting. | Task 0c: use `/?code=`. |
| 4 | Fontsource CSS imported from JS breaks `url()` paths in the file:// IIFE build. | Task 1: vendor 4 woff2 files, with `@font-face` inline in each HTML file using document-relative URLs. |
| 5 | Gateway `verify_jwt` rejects valid tokens with the new signing keys. | Task 3: `--no-verify-jwt`, checked in code through `/auth/v1/user`, with anonymous callers getting 403. |
| 6 | The Edge Function can't import `src/shared/*`. | Task 3: helpers in `supabase/functions/_shared/tmdb.ts`, shared by the phone and tested. |
| 7 | A cached offline snapshot holds expired signed photo URLs. | Task 4: URLs kept in memory only, `onError` falls back to the IndexedDB blob and then to `DreamArt`. |
| 8 | Deleting a dream or idea orphans its photo. | Task 4: a `beforeDelete` hook in `Crud`. |
| 9 | Both partners saving the week at once hit the unique index. | Task 5: catch 23505, reload, retry once. |
| 10 | The TV can't show the weekly dream step (it doesn't read `dream_steps`). | Task 5: step title stored in the payload. |
| 11 | Creating test accounts on the cloud project isn't allowed. | E2E runs on the local stack only (ports 553xx), with `edge-runtime` **not** excluded, so `supabase functions serve` works. |

## Executor rules (Sonnet)

- One task at a time. `npm run check` must be green before each commit. Push to `main` at the end of each task, and Vercel deploys on push.
- Never write the DB password or TMDB token to a file or log. The linked project already stores its connection details.
- Commands that talk to the cloud (`db push`, `functions deploy`, `config push`) are approved.
  - Always run `supabase config push` as a dry diff first, and apply it only if the diff contains nothing but intended keys. Last time it silently changed MFA and email settings.
- UI isn't done until it's rendered with chrome-devtools at 1920×1080 (TV) and 390 px (phone) and the screenshots have been read.
- Hardware results are recorded only from what actually happened on the TV. Anything not run is reported as untested.

## Task 0: fix pairing bugs, then install on the TV (do this first)

**TV status (2026-09-29, later):** reachable. Ping answers, SSH 9922 is open, and `ares-install --list` shows `com.designinnsaeit.vtvsleep` still installed.

Fix these before installing. Both would break pairing on the real TV.

- **0a. Pairing code churn** (`src/tv/live.ts:45-90`).
  - **Problem:** `boot` is a `useCallback` with a stale `code` (always `null`), so `if (!code || …)` calls `start_pairing` every 3 s. `start_pairing` deletes the previous code, so the code on screen changes every 3 s and can never be entered.
  - **Fix:** keep a loop-local `let current: string | null = null`, call `start_pairing` only when `!current || Date.now() - issued > 9 min`, and remove `code` from the deps (`[]`).
  - **Test:** extract `shouldIssueCode(current, issuedAt, now)` into `src/shared/pairing.ts` and cover it with a unit test.
- **0b. No retry after a boot failure.**
  - **Problem:** `boot().catch(() => setOffline(true))` never retries, so a TV that boots before Wi-Fi is up stays on "Retrying…" forever.
  - **Fix:** in `useLive`, retry `boot` with backoff (5 s, 15 s, 30 s, then every 60 s) until it succeeds. Cancel through the existing `epoch` guard.
- **0c. QR link 404.**
  - **Problem:** the QR points to `${phoneUrl}/pair?code=`. Vercel serves a static SPA with no rewrites, so `/pair` returns 404.
  - **Fix:** use `${phoneUrl}/?code=XXXX`. `src/phone/App.tsx` already opens Displays when `code` is present, and fills the code field from `qs.get('code')`.
- **0d. Phone favicon 404.** Add `<link rel="icon" href="/icons/icon-192.png">` to `index.html` (the console error on Vercel).
- **Then:**
  1. Run `npm run check` and `./scripts/build-tv.sh`, which bakes in the cloud URL and runs the secret scan.
  2. Commit and push.
  3. Run `./scripts/install-tv.sh` (installs and launches `com.designinnsaeit.vhome`).
  4. Check that `ares-install --list` still shows `vtvsleep`. Do not call its service yet.
  5. Vineeth reads the 6-character code off the TV and enters it on the phone under Displays, or scans the QR.
  6. Confirm the code does not change while he types.
  7. Report which content appears on the TV. Report remote arrows, OK and Back, whether pairing survives relaunching the app, and whether it survives a TV restart.
  8. Record each result as verified or failed in `docs/CAPABILITIES.md`.
- **If the install fails:** capture `ares-install` stderr and stop. Don't retry with other flags.

## Task 1: Self-hosted fonts (about 30 min)

- **Fonts:** Newsreader (warm editorial serif, headings and quotes) and Atkinson Hyperlegible (body; built for legibility, which suits a TV at 3 m). Both are OFL and both are on npm at `@fontsource/*` 5.3.0.
- **Don't import fontsource CSS from JS.**
  - **Why:** the TV build inlines CSS into one IIFE and injects it at runtime. `url()` paths inside injected CSS are fragile under `base: './'` on file://.
  - **Instead:** vendor static files.
    1. Run `npm pack @fontsource/newsreader @fontsource/atkinson-hyperlegible` in the scratchpad, then extract.
    2. Copy exactly four files into `public/fonts/`: `newsreader-latin-400-normal.woff2`, `newsreader-latin-500-normal.woff2`, `atkinson-hyperlegible-latin-400-normal.woff2` and `atkinson-hyperlegible-latin-700-normal.woff2`.
    3. Copy the two package `LICENSE` files as `public/fonts/LICENSE-*.txt`. Commit them all.
    4. Define the four `@font-face` rules (`font-display: swap`) in an inline `<style>` block in **both** `index.html` and `tv.html`, using document-relative URLs: `url('fonts/newsreader-latin-500-normal.woff2')`. Don't put them in a CSS file. A CSS file lives in `assets/`, so relative paths would break, and the TV build injects its CSS from JS. Document-relative URLs resolve correctly for the phone (`/`) and for the IPK (file://).
- **Tokens:** `--serif: 'Newsreader', Georgia, serif; --font: 'Atkinson Hyperlegible', system-ui, sans-serif`. Update `.claude/docs/design-system.md`.
- **Check:**
  - The built `dist-tv/index.html` and `dist/index.html` both contain `fonts/newsreader`.
  - On the file:// build and on `npm run dev`, `await document.fonts.load("500 40px Newsreader")` returns a non-empty list, and the network log shows the woff2 loading with no 404.
  - The IPK stays under 400 KB.

## Task 2: Live weather (about 1.5 h)

- **`src/adapters/weather.ts`:**
  - `fetchWeather(lat, lon, tz, fetchFn = fetch)` calls Open-Meteo `forecast` with:
    - `current=temperature_2m,weather_code`
    - `daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max`
    - `forecast_days=2` and `timezone=<tz>`
  - It returns `{ tempC, label, hiC, loC, rainPct, tomorrow: {hiC, loC, rainPct}, fetchedAt }`.
  - A `WMO_LABEL` map turns weather codes into short labels (Clear, Partly cloudy, Rain, Thunderstorm, and so on).
- **`weatherView(w, now)` (pure):**
  - Returns `null` when no data exists.
  - Returns `stale: true` after a failed refresh.
  - After 6 h, drops the current temperature and shows only the forecast.
- **`useWeather(lat, lon, tz)` in `src/tv/state.tsx`:**
  - Caches the result in localStorage under `vhome.weather.v1`.
  - Refreshes every 15 min while the app is visible, and again when it becomes visible.
- **Header** shows "Updated 3:40 PM" when the data is stale.
- **"Set up weather on your phone"** appears only when the household has no lat/lon. The city is never guessed.
- **Settings** adds a row: "Weather by Open-Meteo".
- **Simulation** keeps using `fixtureWeather`.
- **Tests** (`weather.test.ts`, with a mocked fetch):
  - A fresh result maps correctly.
  - A failed refresh keeps the cached data and sets `stale`.
  - After 6 h there is no current temperature.
  - No coordinates gives `null`.

## Task 3: TMDB via Edge Function (about 3 h)

**Stop point:** Vineeth creates a free TMDB account and API **Read Access Token**, then runs `supabase secrets set TMDB_TOKEN=…` himself. The token never goes in chat or in the repo.

- **Shared pure helpers live in `supabase/functions/_shared/tmdb.ts`.** They are plain TypeScript with no Deno or browser APIs.
  - **Why:** the Edge Function bundler can't reliably import files outside `supabase/functions/`.
  - The phone imports them by relative path, and they get Vitest tests.
  - Add `"supabase/functions/_shared"` to `tsconfig.json` `include`. Do **not** include `supabase/functions/tmdb`, whose Deno globals would break `tsc`.
- **`supabase/functions/tmdb/index.ts` (Deno):**
  - **Deploy with `--no-verify-jwt` and verify inside the function.**
    - **Why:** gateway `verify_jwt` is unreliable with the new publishable and asymmetric signing keys this project uses.
    - The function reads `Authorization`, then calls `fetch(`${SUPABASE_URL}/auth/v1/user`, { headers: { apikey, Authorization } })`. `SUPABASE_URL` is auto-injected. `apikey` is `Deno.env.get('SUPABASE_ANON_KEY')`, falling back to the first key in `SUPABASE_PUBLISHABLE_KEYS`.
    - Status codes:
      - no user → 401
      - `user.is_anonymous` → 403 (TVs)
      - missing `TMDB_TOKEN` → 503 `{error: 'tmdb_not_configured'}`, so the phone shows "Search unavailable, add manually"
  - **CORS:** answer `OPTIONS` with `Access-Control-Allow-Origin: *` and `Access-Control-Allow-Headers: authorization, apikey, content-type, x-client-info`. Auth is by token, so a wildcard origin is safe.
  - **Phone calls it with** `getClient().functions.invoke('tmdb', { body: { op, q, id, type, region } })`. Use a POST body, not a query string.
  - Routes (using `?op=`):
    - `search&q&type` → `/search/multi`, filtered to movie and tv
    - `details&id&type` → `/movie/{id}` or `/tv/{id}`
    - `providers&id&type&region` → `/{type}/{id}/watch/providers`, returning only `results[region]` as `{flatrate, rent, buy}` lists of provider names
  - Bearer token comes from `Deno.env.get('TMDB_TOKEN')`. Response times out after 8 s. CORS headers allow the Vercel origin and localhost.
- **Deploy:** `supabase functions deploy tmdb`. Pushing to Supabase is already approved.
- **Phone watch form** (`src/phone/App.tsx` Watch, plus a new `src/phone/TmdbSearch.tsx`):
  - A search box shows results with a poster thumbnail (`image.tmdb.org/t/p/w154`).
  - Picking a result pre-fills:
    - title, type, summary, `tmdb_id`, `poster_path`, and `metadata` (year)
    - runtime: `runtime` for movies; `episode_run_time[0]`, else `last_episode_to_air.runtime`, else null for series
  - It then fetches providers for `settings.region` (default `IN`, editable in Settings next to the city) and saves `providers` and `providers_updated_at`.
  - `service` pre-fills with the first subscription (flatrate) provider.
  - A **Refresh availability** button re-fetches providers.
  - If the function fails, show "Search unavailable, add manually". Manual entry still works.
  - Credits line: "This product uses the TMDB API but is not endorsed or certified by TMDB. Streaming data from JustWatch."
- **TV detail** (`src/tv/screens.tsx` Detail):
  - Shows the poster, with no fallback art if there isn't one.
  - Groups providers as Subscription, Rent and Buy, with "Availability as of <date>".
  - The existing credits line stays.
  - `snapshot.ts` adds `poster_path` and `providers` to the select and the mapper.
- **Tests** (Vitest, on `supabase/functions/_shared/tmdb.ts`):
  - `splitProviders(raw, region)`: a missing region gives empty lists.
  - `seriesRuntime(details)`: `episode_run_time[0]`, then `last_episode_to_air.runtime`, then null.
  - `toEntry(result)`: maps a search result to `watch_entries` fields, with year into `metadata`.
- **Deploy and check:**
  - Run `supabase functions deploy tmdb --no-verify-jwt`. Docker is available for bundling.
  - Before the token exists, `curl` with no token must return 401, and with an anonymous TV token must return 403. Both are checkable without TMDB.
  - A member token returns 503 `tmdb_not_configured` until Vineeth sets the secret. After that, `op=search&q=inception` returns results.
- **The secret can be set two ways:**
  - `supabase secrets set TMDB_TOKEN=…` from the v-home folder.
  - Supabase dashboard → Edge Functions → Secrets.

## Task 4: Photos (about 3 h)

- **`src/shared/image.ts`:**
  - `fitWithin(w, h, max = 1920)` is pure and tested.
  - `resizeToJpeg(file)` uses `createImageBitmap` and a canvas, then `toBlob('image/jpeg', 0.82)`.
- **Photo picker:** `<input type="file" accept="image/*">`. iOS converts HEIC to JPEG on pick. `createImageBitmap(file, { imageOrientation: 'from-image' })` keeps EXIF rotation. If decoding fails, show "This photo format is not supported" and don't upload.
- **Phone upload flow** (`src/phone/media.ts`), for dreams and ideas:
  1. Resize the photo.
  2. `path = ${hh}/${uuid}.jpg`.
  3. Insert the `media` row, with `show_on_tv` equal to the parent row's `show_on_tv`.
  4. Upload to storage.
  5. If the upload fails, delete the media row and show an error.
  6. On success, save `image_path` on the dream or idea through the revision-checked `saveRow`.
- **Replacing or removing a photo:** delete the old object and its media row.
- **Deleting a dream or idea:** first delete its object and media row, otherwise they are orphaned forever. Add an optional `beforeDelete(row)` hook to `Crud`.
- **Show on TV toggle:** when it changes on a dream or note, also update that photo's `media.show_on_tv`.
- **Phone display:** thumbnails in the Crud list via signed URLs (`createSignedUrls`, 1 h).
- **TV:**
  - `snapshot.ts` selects `image_path` for dreams and ideas.
  - `live.ts` batches `createSignedUrls` after each snapshot refresh.
  - The storage policy only lets a TV sign files whose media row has `show_on_tv`. That is already tested in SQL; add a pgTAP case for it.
- **TV image cache** (`src/shared/imageCache.ts`):
  - An IndexedDB `img` store keyed by path, holding up to 40 blobs, least-recently-used evicted.
  - Offline, the TV renders from the cached blob via `URL.createObjectURL`.
  - If IndexedDB is unavailable, no image cache (plain URLs only).
- **Signed URLs expire after 1 h, and a cached snapshot used offline holds dead URLs.**
  - Never store signed URLs in the snapshot cache. Keep them in memory only (`Map<path, url>`), re-signed on every refresh.
  - `<img onError>` falls back to the IndexedDB blob, then to `DreamArt`.
  - Fetching a blob from file:// may fail CORS. If `fetch(url)` throws, skip caching for that image. The `<img>` still works.
- **Rendering:** the dream hero, Us > Our Dreams and ritual art use `<img>` when a URL exists, otherwise `DreamArt`. The hero keeps a solid scrim under the text, per the critique.
- **Export/import:** `exportImport.ts` embeds images as base64 `media:[{path, base64, showOnTv}]`. On import, re-upload each image under the new household and rewrite `image_path`. Remove the "Photos are not part of exports yet" note.
- **Tests:**
  - `fitWithin`.
  - The export → import round trip rewrites image paths.
  - pgTAP: a TV can't select a `storage.objects` row whose media is hidden, and can select one once `show_on_tv` is true.

## Task 5: Missing phone screens (about 2.5 h)

- **Migration `20260929000006`:** unique index on `ritual_selections (household_id, day, slot)` so weekly check-ins can be upserted. pgTAP adds a test for it.
- **Custom reflections:**
  - Add `ENTITIES.quotes`: body, slot (morning/evening), author, source, favorite, hidden. Tab label: "Reflections".
  - Same screen, a list of the 40 bundled reflections with a Hide toggle. Hidden IDs are stored in `households.settings.hiddenReflections` through `saveHousehold`.
  - **TV:**
    - The snapshot gains `household.id` (update `fixtureSnapshot` and `emptySnapshot` too), `quotes` (`.eq('hidden', false)`) and `hiddenReflections`.
    - `pickDaily(householdId, …)` switches from the household name to the household ID, and passes both hidden and custom reflections.
    - Favorites are counted twice in the pool, so they come up more often.
    - A **Next** button on the hero advances an in-session offset. It is not saved, which keeps the choice stable across a session.
  - Test: favorites are weighted, and "Next" advances.
- **Idea → task or dream:**
  - In the Ideas Crud, a `decorate` slot adds "Make task" and "Make dream".
  - Each inserts the new row (title, and note → why/next_step) through `saveRow`, then updates the idea to `status: planned` with the revision check. A conflict shows the existing dialog.
  - A pure `ideaToTask` / `ideaToDream` mapper is tested.
- **Weekly check-in** (new phone tab "This week", `src/phone/Weekly.tsx`):
  - Pick one event from this week or add one, one open task, and one dream plus a step title (defaults to the dream's `next_step`).
  - **Saving:**
    - Creates a `dream_steps` row.
    - Loads this week's selection, if any, then saves it through `saveRow`, passing the existing row so the revision check applies. That saves `ritual_selections {day: mondayOf(localDate), slot: 'weekly', payload: {eventId, taskId, dreamId, stepTitle}}`.
    - The step **title** goes in the payload because the TV doesn't read `dream_steps`.
    - If both partners create the week at once, the unique index turns the second insert into an error. Catch unique violation `23505`, reload, and retry once as an update.
  - **TV:**
    - The snapshot adds this week's `ritual_selections` row.
    - Us > This Week shows a "This week we chose" card at the top. It resolves the event, task and dream by ID from the snapshot and skips any item the TV can't see.
  - `mondayOf(date)` is pure and tested, including the week that crosses a year boundary.

## Task 6: Docs (about 1 h)

Read `LGTV/docs/dev-mode.md` and `LGTV/docs/troubleshooting.md` (read-only) first, and match their commands.

- **`docs/RECOVERY.md`:**
  - Reinstall with `scripts/install-tv.sh`, then re-pair (content comes back from the cloud).
  - Export/import steps, and roll back to the previous IPK kept in `build/`.
  - Rotate the DB password.
  - What to do if Supabase paused after 7 idle days: open the dashboard and restore.
- **`docs/DEV-MODE.md`:**
  - How the session counter works (999h shown).
  - Renew via the Developer Mode app, or LGTV's `scripts/extend-dev-mode.sh`.
  - When the session expires, apps are removed, so reinstall V/TV Sleep and then V/HOME.
- **`docs/CAPABILITIES.md`:** a sanitized table (verified / not verified / not supported) for app launch IDs, inputs, the timer route (direct or handoff), cache backend, Back key and Quick Access. Everything is "not verified" until Task 0 and the TV gate run.
- **`docs/LIMITATIONS.md`:**
  - The handoff takes the foreground.
  - No overlay above other apps, and the Home button can't be replaced.
  - A revoked TV keeps its cached content until it reconnects.
  - The Supabase free tier pauses.
  - TMDB availability can be out of date.
  - No external calendars.
  - Photo exports get large.
- **README:** add links to these docs.

## Order

Task 0 now: the TV is reachable. Then Tasks 1 → 2 → 6 → 5 → 4 → 3. Task 3 goes last because it waits on the TMDB token. Tasks 1, 2 and 6 touch no shared files and may run as parallel subagents; Tasks 4 and 5 both edit `snapshot.ts` and `live.ts`, so run them one after the other.

## Verification

- `npm run check`, `supabase test db` (local stack on ports 553xx) and `scripts/check-secrets.sh` all stay green.
- **Push:** `supabase db push` for migration 006, `supabase functions deploy tmdb`, and `git push` so Vercel deploys.
- **End-to-end on the LOCAL stack only**, with test accounts. Never create accounts on the cloud project.
  - Run the phone at 390 px and the TV at 1920×1080 with `VITE_SUPABASE_URL=http://127.0.0.1:55321`.
  - Checks:
    - A photo uploads and appears on the TV only after Show on TV is set.
    - A hidden reflection never shows.
    - Converting an idea creates a task and marks the idea planned.
    - The weekly check-in appears on the TV.
    - Weather is blocked and then stale.
    - TMDB is mocked when the token is missing locally.
- **On the TV (Task 0 and after):** pairing, fonts rendering, photos showing, readable weather. Report anything not run as untested.

## Stop points

- TV physical steps in Task 0: Vineeth enters the code, and reports the remote, relaunch and restart results. One instruction at a time.
- TV unreachable again: ask Vineeth to check the Developer Mode app (Dev Mode ON, Key Server ON, IP unchanged).
- The TMDB Read Access Token, entered by Vineeth via `supabase secrets set`.
- V/TV Sleep missing after the Dev Mode restart: ask before reinstalling it.
