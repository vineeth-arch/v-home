# V/HOME — implementation plan (rev 2)

> Planned on Opus 5.5. **Executed on Sonnet.** Every task below includes the exact files, commands and a check that must pass. Where a choice exists, the plan makes it. Do not re-decide a choice that is already marked here.

## Progress (update as tasks finish)

- [x] Phase 0 setup (repo, configs, design system, file:// IIFE render verified)
- [x] Phase 1 TV shell, focus engine (overlay scopes), platform + timer adapters (all unverified on TV)
- [x] Phase 3 screens, rituals, Quick controls on fixtures; render-gated at 1920x1080; impeccable critique 26/40 (fixes applied); entry-only motion pass
- [~] Phase 4: DONE backend (schema, RLS, RPCs, storage policy, 39 pgTAP tests pass locally on ports 553xx; other local stack `di-form-engine` uses 543xx, do not stop it). DONE client data layer (snapshot mapper, sync engine, cache, TV live hook + pairing gate, display_unpair RPC; 41 pgTAP tests). Phone app WRITTEN (auth, onboarding, invite, CRUD for plans/tasks/dreams/notes/ideas/watch with votes, draft autosave, conflict dialog, displays, settings, export/import); only the sign-in screen was render-checked at 390px. UNTESTED: every signed-in flow, live TV sync, image upload (image.ts not written; TV image display and export of photos not done). TODO: live E2E (needs .env.local), image upload.
  - Local Supabase start command: `supabase start -x logflare,vector,imgproxy,mailpit,studio,postgres-meta,supavisor,edge-runtime` (full stack times out on this machine).
  - Finding: new Supabase needs explicit GRANTs to `authenticated` (added in 0002).
- [ ] Phase 5 TMDB + weather
- [ ] Phase 2/6 TV gate + packaging (blocked on LGTV step 10). Untested on hardware: everything.
- Known gaps: fonts are system stacks (self-hosted woff2 not added yet); phone viewport (390px) checks not applicable until Phase 4.

## Context

Vineeth and his wife want a warm, shared LG TV dashboard (V/HOME) with a phone companion. The full brief is locked.

- `v-home/` is empty and not a git repo.
- The sibling project `LGTV` (V/TV Sleep) is **not finished**. Step 10 of its test plan is partial, steps 11–14 are not started, and the "launch steals foreground" issue is still open. Its tree is clean on `main`.

**User decision (2026-09-29):** start now, building the phases that need no TV first. The on-TV gate and timer work wait until LGTV step 10 closes. **Never modify any file under `/Users/vineethnair/Vibe Code/LGTV`.**

Outcome for this run: both partners edit shared content from their phones. The TV app, running on desktop and as a file:// build, shows all screens and modes on live Supabase data. The timer path is built behind an adapter and stays marked **unverified** until the hardware phase.

## Environment (verified 2026-09-29)

- Tools: node v26.4.0, npm 11.17, docker 29.5, supabase CLI 2.111, vercel 59.20, git 2.54.
- `ares-*` is not on PATH. Install `@webos-tools/cli` as a devDependency and call it through `node_modules/.bin`, as LGTV does. The ares device named `tv` is already set up in `~/.webos/ares`, and it is shared with LGTV.
- TV: 43NU885BPLA, firmware 43.04.26, SDK 11.0.1, Node 20.12.2, IP 192.168.29.224.

## Facts from LGTV to reuse (read-only)

- Service `com.designinnsaeit.vtvsleep.service` (`LGTV/tv-service/lib/handlers.js:49-202`):
  - `status` returns one of:
    - `{scheduled:false}`
    - `{scheduled:false, stale:true, shutdownAt}`
    - `{scheduled:true, minutes, shutdownAt, shutdownAtIso, remainingMs}`
  - `schedule {minutes}` takes a whole number from 1 to 720.
  - `cancel {}`
  - `powerOff {}` returns `attempts[]`.
  - Errors have the shape `{returnValue:false, errorText}`.
- Launch modes the V/TV app accepts: `schedule` (needs `minutes`), `cancel`, `status`, `off`.
- Port these patterns, not the files as-is:
  - `LGTV/tv-app/bridge.js`: PalmServiceBridge wrapper with a desktop stub.
  - `LGTV/tv-app/app.js:54-95`: nearest-neighbour focus and pointer-hover sync.
  - `LGTV/tv-app/app.js:262-292`: key codes.
  - `LGTV/scripts/build-tv.sh` and `LGTV/scripts/install-tv.sh`.
  - `LGTV/tv-app/appinfo.json`: shape of the file.

## Review pass: things in rev 1 that would fail, and the fix now in the plan

| # | Problem in rev 1 | Fix in rev 2 |
|---|---|---|
| 1 | Vite emits `<script type="module" crossorigin>`. Chromium blocks module scripts loaded from **file://**, so the packaged IPK would open to a blank screen. | TV build is a separate Vite build: a single IIFE bundle, `modulePreload:false`, and a small plugin that strips `type="module"`/`crossorigin`. Verified on desktop by opening `dist-tv/index.html` via file:// before any TV work. |
| 2 | Multi-page Vite can't output an IIFE. The phone app needs `index.html` at the root for Vercel. | Two configs: `vite.tv.config.ts` builds to `dist-tv/`, and `vite.config.ts` (phone) builds `index.html` to `dist/`. |
| 3 | Supabase's built-in email sends only to project team members and allows about 2 emails per hour. His wife's magic link would never arrive. | Use **email + password** auth with "Confirm email" turned off. Household access is still gated by a single-use invite token. After both people have joined, turn signups off (documented). Magic links can come later with custom SMTP. |
| 4 | Realtime can't tell the TV that a row became hidden. When `show_on_tv` flips true→false, RLS drops the event, so the TV keeps showing stale content. DELETE events also bypass RLS filters. | Add a `household_versions(household_id, version)` table. A trigger bumps it on **every** content write. The TV subscribes to that one row and polls it every 30 s; whenever the version changes it refetches the whole snapshot. Row events are never used as the data source. |
| 5 | A generic `update_row(table, …)` RPC would need dynamic SQL, which opens an injection risk. Zero updated rows is ambiguous: it could be a conflict or an RLS denial. | A `BEFORE UPDATE` trigger bumps `revision`. The client runs `.update(patch).eq('id',id).eq('revision',n).select()`. If no rows come back, it re-selects the row: row present means conflict dialog, row missing means "no access". |
| 6 | Storage policies can't see `show_on_tv`, so the TV could read any image in the household. | Add a `media(path, household_id, show_on_tv, author_id)` table. The storage `SELECT` policy joins `media` on `name`. |
| 7 | "Inline SVG QR" would mean hand-writing a QR encoder (about 300 lines, easy to get wrong). | Add one small dependency, `qrcode-generator` (no transitive dependencies), and render its output as SVG. |
| 8 | `CompressionStream` produces gzip, not zip, so the export wasn't a real archive. | Export a single `.json` file with images base64-embedded. Images are already resized, so the file stays small. Import remaps IDs into the current household. |
| 9 | Phone photos are 4–12 MB. That burns through the free storage tier and TV memory. | Resize on the phone before upload: longest edge 1920 px, JPEG at 0.82, using `createImageBitmap` and a canvas. |
| 10 | Without `disableBackHistoryAPI`, webOS routes Back through browser history, so the app never sees key 461. | `appinfo.json` sets `"disableBackHistoryAPI": true`. Back at the root calls `window.close()`, to be verified at the TV gate. |
| 11 | A service worker for the PWA risks serving stale builds. Chrome no longer requires one to install. | No service worker. Use a manifest plus iOS meta tags. |
| 12 | Loading Google Fonts on a TV that's offline or on a slow network gives a flash of unstyled text or broken type. | Self-host two `.woff2` files in `public/fonts/`. |
| 13 | A fixed 1920×1080 layout overflows a desktop browser window, so preview screenshots would lie. | A `#stage` element is 1920×1080 and scaled with CSS `transform: scale()` to fit the window when not running on webOS. On the TV the scale is 1. |
| 14 | Direct service calls will probably be blocked because `com.designinnsaeit.vhome` doesn't share the `vtvsleep` prefix. | The TV gate tests three routes in order: (a) direct call from `vhome`; (b) the launch handoff; (c) **only with Vineeth's approval**, a test build with ID `com.designinnsaeit.vtvsleep.home`, since the brief fixes the app ID. |
| 15 | The handoff leaves V/TV Sleep in the foreground, so the user has to press Back. | This is a documented limitation because LGTV can't be changed. The UI says "Opened V/TV Sleep — press Back to return" and never shows a countdown. |
| 16 | An anonymous (TV) user could try to call `accept_invite`. | Every member-only RPC rejects callers where `(auth.jwt()->>'is_anonymous')::boolean` is true. All `SECURITY DEFINER` functions use `set search_path = ''` and schema-qualified names. |
| 17 | The pgTAP plan assumed a local database stack. | Docker and the supabase CLI are present, so use `supabase start` plus `supabase test db` locally. The same migrations are pushed to the cloud project with `supabase db push`. |
| 18 | Running agents in parallel on Phase 4/5 would edit `package.json`, `model.ts` and the migrations at the same time. | Run the phases one after another. The optional parallel split is limited to the Phase 5 Edge Function versus the weather adapter, which share no files. |
| 19 | IndexedDB and localStorage on a file:// origin on webOS are unproven. | `cache.ts` tries IndexedDB, falls back to localStorage for the snapshot only (no image cache), and then to memory. The chosen backend is shown in the Settings diagnostics and verified at the TV gate. |
| 20 | Launching apps through the platform may need a manifest permission. | `appinfo.json` gets `requiredPermissions: ["applications.operation"]`, to be confirmed or adjusted at the TV gate. Only IDs that pass verification go into the launch strip. |

## Stack (locked)

- **React 19 + TypeScript + Vite + plain CSS.** The brief overrides the global Next.js/Tailwind default; name this conflict once in the README.
- Runtime dependencies:
  - `react`, `react-dom`
  - `@supabase/supabase-js`
  - `qrcode-generator`
- Dev dependencies:
  - `vite`, `@vitejs/plugin-react`, `typescript`
  - `vitest`
  - `@webos-tools/cli`
- Nothing else without a written reason.
- TV build target is `chrome108`. Raise it after the TV gate records the user agent.
- Backend is Supabase only: Postgres + RLS, Auth (email/password plus anonymous sign-in for TVs), private Storage, Realtime, and one Edge Function `tmdb`.
- The phone app is a static site on Vercel.

## Layout

```
index.html (phone)  tv.html  vite.config.ts  vite.tv.config.ts  tsconfig.json  package.json
public/fonts/*.woff2  public/manifest.webmanifest  public/icons/*
webos/appinfo.json  webos/icon.png  webos/largeIcon.png
src/shared/  model.ts  modes.ts  reflections.ts  picker.ts  daily.ts  sync.ts  cache.ts  supabase.ts  image.ts  exportImport.ts
src/adapters/ timer.ts  platform.ts  weather.ts      # interface + real + mock, nothing more
src/tv/      main.tsx App.tsx stage.css focus.ts  screens/*.tsx  rituals/*.tsx  QuickControls.tsx  Pairing.tsx
src/phone/   main.tsx App.tsx  screens/*.tsx
src/styles/  tokens.css
supabase/migrations/0001_schema.sql 0002_rls.sql 0003_rpc.sql 0004_storage.sql
supabase/tests/*.test.sql    supabase/functions/tmdb/index.ts
scripts/build-tv.sh install-tv.sh launch-tv.sh check-secrets.sh
.claude/docs/design-system.md   docs/PLAN.md  docs/RECOVERY.md docs/DEV-MODE.md docs/CAPABILITIES.md docs/LIMITATIONS.md
```

## Executor rules (Sonnet)

1. Copy this plan to `v-home/docs/PLAN.md` in Phase 0. Tick the tasks there as they finish.
2. Work one task at a time. Commit after each task using a conventional message plus the attribution line. Never force-push, never merge, never touch LGTV.
3. After each task, run `npm run check`, which is typecheck, then test, then both builds. It must pass before the commit.
4. Skills, invoked by typing the command at the step named:
   - `superpowers:executing-plans`: at the start.
   - `frontend-design`: before Phase 3 UI work.
   - `superpowers:systematic-debugging`: on any failure that isn't obvious.
   - `superpowers:verification-before-completion`: before reporting any phase done.
   - `impeccable` (critique only) and then `emil-design-eng`: each in its own turn after Phase 3.
   - Not used: `design-taste-frontend` (this is app UI, not a marketing page) and `graphify` (the project is new, so there's nothing to map).
5. UI is not done until it has been rendered through chrome-devtools MCP and the screenshots have been read. If the MCP won't connect, say so and mark the work **unverified**.
6. Never write a TV or hardware result as passed without on-TV evidence. Hardware items stay listed as **untested** in reports.
7. Secrets never go in the repo or in logs. `.env.local` is git-ignored and holds only the Supabase URL and publishable key. The TMDB token goes in with `supabase secrets set` and is typed by Vineeth.
8. Stop and ask only at the stop points listed at the end. Ask one clear question or give one physical instruction at a time.

## Phase 0 — Setup (about 20 min)

- **0.1**
  - Run `git init -b main`, add `.gitignore` (node_modules, dist*, .env*, supabase/.temp) and make the first commit.
  - Run `git switch -c feat/v1`.
- **0.2**
  - Scaffold by hand, with no `create-vite` prompts.
  - `package.json` scripts: `dev`, `dev:tv`, `build`, `build:tv`, `typecheck` (`tsc --noEmit`), `test` (`vitest run`), and `check` (all of these in sequence).
- **0.3** `vite.tv.config.ts`:
  - Input is `tv.html`, renamed to `index.html` in the output.
  - `base:'./'`, `outDir:'dist-tv'`, `build.modulePreload:false`, `target:'chrome108'`.
  - `rollupOptions.output: {format:'iife', inlineDynamicImports:true}`.
  - A `transformIndexHtml` plugin removes `type="module"` and `crossorigin`, and moves the `<script>` to the end of `<body>`.
  - A copy step puts `webos/*` into `dist-tv/`.
- **0.4** Write `.claude/docs/design-system.md` from brief §2:
  - Colour tokens: warm charcoal, warm white, amber, sage, plus the evening palette.
  - 96 px safe margin, headings 56–72 px, body text 30–36 px.
  - Focus shown by both border and scale, never colour alone.
  - Reduced motion honoured. No gradients, no generic animated backgrounds, no auto-playing audio.
  - Put the same tokens in `src/styles/tokens.css`.
- **Check:**
  - `npm run check` is green.
  - `open dist-tv/index.html` (file://) in Chrome renders "V/HOME" with no console errors. Verify with chrome-devtools `navigate_page` to the file:// URL and `list_console_messages`.

## Phase 1 — TV shell and adapters (about 2 h)

- **1.1 `src/tv/focus.ts`: `useFocusable(id, {group})`**
  - Keeps a registry of element refs.
  - Arrow keys move to the nearest element in the pressed direction. The score is the primary-axis distance plus 2× the cross-axis distance, the same idea as LGTV `app.js:54-95` but computed from bounding boxes.
  - `mouseover` moves focus to the hovered element.
  - Maintains a stack of overlays and screens. Back (keyCodes 461, 27, 8) closes the top overlay, then goes back a screen, and at the root calls `window.close()`.
  - Saves the focused id on `visibilitychange` hidden and restores it when the app is shown again.
  - Test with Vitest using a mocked element tree: choosing the next element, and Back popping the stack in order.
- **1.2** `stage.css` plus `App.tsx`: a 1920×1080 `#stage` that scales to fit when `!window.PalmSystem`. Show a `SIMULATION` chip whenever any mock adapter is active.
- **1.3 `adapters/platform.ts`**
  - `callLuna(uri, params, timeoutMs=8000)` is a PalmServiceBridge port that resolves to `{ok, data} | {ok:false, error} | {unknown:true}` when it times out.
  - `launchApp(id, params?)` calls `luna://com.webos.applicationManager/launch`.
  - A mock implementation logs calls and returns success.
- **1.4 `adapters/timer.ts`**
  - The `TimerAdapter` interface: `status()`, `schedule(min)`, `cancel()` and `powerOff()`. Each returns `{kind:'confirmed', state}`, `{kind:'failed', error}` or `{kind:'unknown'}`.
  - Implementations:
    - `MockTimer`: in-memory, with `shutdownAt`.
    - `LunaTimer`: calls the vtvsleep service directly.
    - `HandoffTimer`: `launchApp('com.designinnsaeit.vtvsleep', {mode, minutes})`. It returns `{kind:'handoff'}`, and its `status()` returns `{kind:'unavailable'}`.
  - `LunaTimer` and `HandoffTimer` carry `verified:false`. The UI shows "Not yet verified on this TV" while it is false.
  - `minutes` is validated as a whole number from 1 to 720 before any call.
  - Tests:
    - Mapping every `status` shape: none, stale, active.
    - A timeout gives `unknown`.
    - After `unknown`, the UI state machine refreshes `status` before allowing a retry.
- **Check:** `npm run check` is green, and a desktop preview shows the shell with the SIMULATION chip.

## Phase 3 — Full local experience on fixtures (about 1 day)

Invoke `frontend-design` first. Everything follows `.claude/docs/design-system.md`. Fixtures live in `src/shared/fixtures.ts`, used only by the mock data source.

- **3.1 Pure logic, each with a Vitest file**
  - `modes.ts: resolveMode(now, tz, windows, manual)`
    - Windows wrap past midnight: Evening runs 18:00–05:00.
    - Pinned by tests: 04:59 is Evening, 05:00 is Morning, 11:00 is Home, 18:00 is Evening.
    - `shouldApplyScheduledMode(current, next, {screen, ritualActive, idleMs})` returns true only when the screen is Our Home, no ritual is running, and the app has been idle for at least 60 s.
  - `daily.ts: localDate(now, tz)` uses `Intl.DateTimeFormat('en-CA', {timeZone})`.
  - `reflections.ts`
    - 40 original reflections, 20 morning and 20 evening, labelled "Original reflection" with no author.
    - Include the brief's "We are building a life that feels peaceful, connected, and ours."
    - `pickDaily(householdId, date, slot, hidden[], custom[])` uses an FNV-1a hash, is stable for a given day, and skips hidden items.
    - Test: the choice is the same all day and changes the next day.
  - `picker.ts`
    - `eligible(entries, prefs, filters)`: drops any title either person marked Pass. Series use episode runtime. An unknown runtime passes the time filter only if "Include unknown" is on, which is the default, and is shown as "Runtime unknown".
    - `rank()`: titles both marked Want come first, then Want + Maybe, then the rest.
    - `pickForUs(rng)`: random choice from the eligible list.
    - `explainEmpty()`: returns the specific filters to relax.
- **3.2 TV screens**
  - Our Home: header, one dream hero, Today/Tomorrow (up to 3 items), a "For us" item, a launch strip (up to 6), navigation, and a timer status line.
  - The Morning ritual (Imagine, Intend, Act) and the Bedtime ritual (Appreciate, Connect, Imagine, Rest). Cards advance manually. No streaks and no required input.
  - Watch Together: type choice, filters, up to 3 matches, Pick for us, the detail screen, and Open app. TMDB and JustWatch credits appear on the detail screen.
  - Us: This Week, Home Tasks, Our Dreams, Notes. Completing a task is the only write.
  - Idea Wall: 6 cards per page with paging.
  - Settings: household info, timer path status, cache backend, last sync, the unsupported-controls explanation, and Unpair.
  - Quick Controls: a persistent on-screen button that opens a panel with 30/45/60/90, a custom stepper from 1 to 720, status, cancel, open V/TV Sleep, pinned apps, Guest view, and TV off now behind a confirm step.
  - Pairing: the code in large type and a QR (`qrcode-generator` rendered as SVG) pointing to `https://<vercel-host>/pair?code=XXXX`.
  - Empty household: clock, "Set up weather on your phone", the launch strip and a reflection.
- **3.3 Render gate**
  - Run `npm run dev:tv`.
  - Use chrome-devtools `resize_page` to 1920×1080 and 1440×900, and screenshot every screen and mode plus Guest view and the empty state.
  - Walk the screens with the keyboard only, using `press_key` arrows, Enter and Escape: no focus traps, and every action reachable.
  - Read the screenshots and fix clipping and contrast.
  - Then open `dist-tv/index.html` via file:// and confirm the same.
- **3.4** In separate turns: `impeccable` critique (report only, never rebuild), then an `emil-design-eng` motion pass. Durations 150–250 ms, `prefers-reduced-motion` turns motion off.

## Phase 4 — Supabase and the phone companion (about 1.5 days)

**Stop point A:** Vineeth creates the Supabase cloud project or approves creating it, and turns on anonymous sign-ins. Build locally first with `supabase init && supabase start`, which needs Docker running.

- **4.1 `0001_schema.sql`**
  - Membership and pairing:
    - `households(id, name, timezone default 'Asia/Kolkata', settings jsonb)`
    - `members(household_id, user_id, role check in ('member','display'), display_name, primary key(household_id, user_id))`
    - `invites(token uuid, household_id, expires_at, used_by)`
    - `display_pairings(code text unique, tv_user_id, household_id null, expires_at, approved_at)`
  - Content tables: `events(starts_at timestamptz, all_day)`, `tasks(owner check in ('a','b','both'), kind task|grocery, done)`, `notes`, `dreams`, `dream_steps`, `ideas(status new|discuss|planned|archived)`, `watch_entries(tmdb_id null, type movie|series, metadata jsonb, providers jsonb, providers_updated_at, runtime_min null, mood, service, watched)`, `watch_prefs(entry_id, user_id, pref want|maybe|pass, pk(entry_id,user_id))`, `quotes`, `ritual_selections`, `media`.
  - Every content table has `id uuid default gen_random_uuid()`, `household_id`, `author_id default auth.uid()`, `created_at`, `updated_at`, `revision int default 1`, `visibility text default 'shared'` (`draft|shared`) and `show_on_tv bool default true`. The `show_on_tv` default is **false** for dreams, notes and media, because those need an explicit "Show on TV".
  - `household_versions(household_id pk, version bigint)`.
  - Triggers:
    - `bump_revision` (BEFORE UPDATE): sets `revision = old.revision + 1` and `updated_at = now()`.
    - `bump_household_version` (AFTER INSERT/UPDATE/DELETE on every content table).
- **4.2 `0002_rls.sql`**
  - Enable RLS on every table.
  - Helper functions `is_member(hh)` and `is_display(hh)`: `security definer`, `stable`, `search_path=''`.
  - Content:
    - Members `SELECT` rows where the household matches and (`visibility='shared'` or `author_id=auth.uid()`).
    - Displays `SELECT` only rows where `visibility='shared' AND show_on_tv`.
    - Members may `INSERT/UPDATE/DELETE` only in their own household. A draft can be updated only by its author.
  - Displays have no direct write policies at all.
  - `watch_prefs`: household members and displays can read. Only a member can write, and only a row with `user_id = auth.uid()`.
  - `members`: readable by the same household, never writable directly (RPC only).
  - `household_versions`: members and displays of the household can `SELECT`.
- **4.3 `0003_rpc.sql`** (all `security definer`, `search_path=''`; member RPCs reject anonymous callers)
  - `create_household(name, display_name)`
  - `create_invite(hh)` returns a token valid for 7 days
  - `accept_invite(token, display_name)`: single use
  - `start_pairing()` (TV; must be anonymous): returns a 6-character code from an alphabet without 0/O/1/I, valid for 10 min
  - `approve_pairing(code, hh)` (member): inserts a `members` row with role `display` for `tv_user_id`
  - `pairing_status()` (TV): returns the household ID once the pairing is approved
  - `revoke_display(hh, tv_user_id)`
  - Display actions:
    - `tv_complete_task(id)`
    - `tv_mark_watched(id)`
- **4.4 `0004_storage.sql`**
  - Private bucket `household-media`, paths `{household_id}/{uuid}.jpg`.
  - Members may insert and select files in their household folder.
  - Displays may select a file only when `exists(select 1 from public.media m where m.path = name and m.show_on_tv and public.is_display(m.household_id))`.
- **4.5 RLS tests (`supabase/tests/*.test.sql`, pgTAP; run with `supabase test db`)** cover:
  - an unauthenticated user
  - a member of another household
  - a revoked display
  - an expired or reused pairing code
  - an anonymous user calling `accept_invite`
  - a display trying to insert into `members`, read a draft, read a hidden dream, or write `watch_prefs`
  - each member voting separately
  - a stale-revision update affecting 0 rows
  Simulate users by setting the role and `request.jwt.claims` inside each test transaction.
- **4.6 `shared/supabase.ts`, `sync.ts`, `cache.ts`**
  - Client with `persistSession:true` and `autoRefreshToken:true`.
  - The TV calls `signInAnonymously()` once and reuses that session after that.
  - `sync.ts`:
    - Subscribes to `household_versions` for the household and polls every 30 s.
    - Refetches the full TV snapshot whenever the version changes, on `visibilitychange` back to visible, and on `online`.
    - Refetches are debounced by 300 ms.
    - A permission failure or a missing `members` row counts as revoked: clear the cache and show Pairing.
  - `cache.ts`:
    - Snapshot and timestamp go in IndexedDB, falling back to localStorage and then to memory.
    - Images are kept as an LRU of 40 blobs in IndexedDB only. Signed URLs expire after 1 hour and are re-signed when the snapshot refreshes.
    - Offline banner: "Showing saved content from <time>".
- **4.7 Phone app (mobile-first, 390 px)**
  - Sign up and sign in with email and password.
  - Create a household or accept an invite (`/join?token=`).
  - Onboarding: names, confirm the timezone, city (Open-Meteo geocoding search, lat/lon saved to settings), streaming region, subscriptions, and pinned apps. Pinned apps start as "unverified" until the TV gate.
  - Editing screens for:
    - events, tasks and groceries
    - notes, dreams and steps
    - ideas, with convert-to-task and convert-to-dream
    - the watchlist and each person's preference
    - media uploads
    - displays, with `/pair?code=` approve and revoke
    - export and import
  - Every write uses the revision filter. On a conflict, a dialog shows theirs versus mine, with "Reload" or "Overwrite with mine" (re-applied at the new revision).
  - Unsent text is autosaved to localStorage with the label "Draft — not saved".
  - The draft/share toggle and the "Show on TV" toggle are explicit on dreams, notes and images.
- **4.8 `image.ts`**: resize to a longest edge of 1920 px, JPEG 0.82, then upload. Insert the `media` row first, and delete it if the upload fails.
- **4.9 `exportImport.ts`**
  - Export: JSON `{version:1, household, rows by table, media:[{path, base64}]}`.
  - Import: into the current household with new UUIDs and remapped foreign keys. Show a preview of counts before writing.
- **Check:**
  - `supabase test db` is green and `npm run check` is green.
  - Two chrome-devtools pages signed in as two users (fake emails on local Supabase), plus a third page running the TV preview:
    - An edit on phone A appears on the TV in under 5 s.
    - The same row edited on both phones triggers the conflict dialog.
    - A draft never appears on the TV.
    - Turning off Show on TV removes the item from the TV within 5 s.
    - Revoking the display returns the TV to Pairing.
    - Guest view hides personal content straight away.

## Phase 5 — TMDB and weather (about half a day)

Optional parallel split: 5.1 and 5.2 share no files.

- **5.1 `supabase/functions/tmdb/index.ts`**
  - Requires a member JWT: `verify_jwt` on, and it checks that the caller is not anonymous.
  - Routes:
    - `search?q&type`
    - `details?id&type`
    - `providers?id&type&region`
  - Uses the TMDB v4 read token from `Deno.env`.
  - The phone saves the results into `watch_entries` (metadata, runtime, and providers split into flatrate/rent/buy, with `providers_updated_at`).
  - A manual entry works without TMDB.
  - If TMDB is down, the phone shows "Search unavailable — add manually".
- **5.2 `adapters/weather.ts`**
  - Open-Meteo `forecast` with `current=temperature_2m,weather_code&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max&timezone=<tz>&forecast_days=2`.
  - Refreshes every 15 min while visible and caches the last result with a timestamp.
  - After a failed refresh it shows "Updated <time>". After 6 h it drops the word "current".
  - No city set means the setup prompt is shown. The city is never guessed.
  - Attribution "Weather by Open-Meteo".
  - Tests use a mocked fetch: fresh, stale, older than 6 h, and error.
- **Check:** in DevTools, block `api.open-meteo.com` and the function URL. Both screens degrade with a timestamp and nothing crashes.

## Deferred: Phase 2 (TV gate) and Phase 6 (packaging) — start only after LGTV step 10 is closed

**Stop point C:** each step below is one physical instruction to Vineeth.

1. **Package and install.**
   - `scripts/build-tv.sh` runs `npm run build:tv`, then `ares-package dist-tv -o build/`.
   - `install-tv.sh` runs `ares-install --device tv`.
   - Afterwards, check that V/TV Sleep still launches and that its `status` is unchanged.
2. **Engine and input.**
   - Record `navigator.userAgent` and raise `target` to match.
   - Test arrows, OK, Back (461), Back at the root, the pointer, IndexedDB versus localStorage, and whether the anonymous session survives a TV restart.
   - Test launching each candidate app and input ID, then mark the verified ones.
3. **Timer routes.**
   - Route (a): call `LunaTimer.status()` directly.
   - If (a) fails, use route (b), `HandoffTimer`, and ask Vineeth about route (c), the prefix ID build.
   - With a working route, run a supervised 2-min timer while Netflix/YouTube is open. Then test cancel, replace, a stale deadline, and the service being unavailable.
   - Record the response shapes and add Vitest integration tests against them.
   - Flip `verified:true` only for routes that pass.
4. **Brief acceptance.** Run the timer and navigation acceptance list, test Quick Access on the remote, and check readability on the 43-inch TV from the sofa.
5. **Capabilities.** Write a sanitized `docs/CAPABILITIES.md`. Only verified controls appear in Quick Controls.

## Phase 7 — Release (about half a day)

- **Stop point B:** get Vineeth's approval to link the Vercel project, then make a preview deploy.
- Set the Supabase Auth site URL and redirect URLs to the Vercel host and localhost.
- Production deploy needs explicit approval.
- Docs:
  - `RECOVERY.md`: reinstall the IPK, re-pair, and content comes back from the cloud; export/import.
  - `DEV-MODE.md`: renewing Developer Mode, and what happens when the session expires.
  - `LIMITATIONS.md`:
    - The handoff takes the foreground.
    - The Supabase free tier pauses after 7 days idle; the cached TV stays usable while paused.
    - Revoking a TV takes effect only when it reconnects.
    - There is no overlay above other apps.
    - The Home button can't be replaced.
- Keep the previous IPK in `build/` as the rollback.

## Hard limits

- No rooting, firmware or protected-file edits, boot hooks, or Home-button interception.
- No screensaver suppression and no fake activity.
- Don't run the upstream root deploy script.
- No `setTimeout`-based shutdown. V/TV is the only timer authority.
- No force-push, no merge without instruction, and no LGTV edits.

## Verification summary

- `npm run check` passes on every commit.
- `supabase test db` is green.
- `scripts/check-secrets.sh` greps `dist/` and `dist-tv/` for `service_role`, `sb_secret_`, TMDB token patterns and `eyJhbGciOi` beyond the publishable key, and fails if any appear.
- chrome-devtools screenshots at 1920×1080 and 1440 for the TV, and 390 for the phone. They are read before anything is reported done.
- The file:// build is checked on the desktop.
- Multi-session sync, conflict, draft, revoke and Guest checks from Phase 4.
- Outage checks from Phase 5.
- Final report lists passed, failed and **untested** items. All hardware items stay untested until Phase 2/6 runs.

## Stop points needing Vineeth

- **A.** Supabase cloud project (create or approve), turn on anonymous sign-in, turn off email confirmation, and enter the TMDB token himself with `supabase secrets set TMDB_TOKEN=…`.
- **B.** Vercel project link, preview deploy, then approval for the production deploy.
- **C.** Every physical TV step, only after LGTV step 10 closes. Route (c) needs separate approval.

## Cloud (project kqmiuhnaeoshjynsttwa) status
- 5 migrations applied. Auth: anonymous sign-in ON, email confirmation OFF, site URL https://v-home-psi.vercel.app. Public reads return 401.
- Vercel env set (URL, publishable key, phone URL). Rotate the DB password (it was shared in chat).
- `supabase config push` applies without prompting and also pushes local mfa/email defaults, so keep config.toml aligned with remote.

## Blocked / next action (superseded: a git-ignored .env.local now exists via `vercel link`, pointing at the cloud project)
- Live E2E needs `.env.local` (git-ignored) with `VITE_SUPABASE_URL=http://127.0.0.1:55321`, the local publishable key from `supabase status`, `VITE_PHONE_URL=http://localhost:5173`. The assistant's attempt to generate it was denied by the sandbox; the user must create it or approve.
