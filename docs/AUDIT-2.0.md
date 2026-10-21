# V/HOME 2.0 audit (2026-10-21)

Baseline: `main` @ 81e33b0, clean, in sync with origin. `npm run check`: typecheck pass, 22 test files / 85 tests pass, phone + TV builds pass.

**Exists, reused:** spatial focus + Back stack (`src/tv/focus.ts`, `FocusProvider.tsx`, focus restored on `visibilitychange`); Luna bridge with unknown-result timeouts (`src/adapters/platform.ts`); timer adapters + `TimerController` unknown-guard (`src/adapters/timer.ts`); `launchFailure`; `parseLaunchPoints` / `allApps` / `isValidAppId`; curated `CANDIDATE_APPS`; 1920×1080 Stage; self-hosted fonts; IPK scripts.

**Modified for 2.0:** whole UI was gated behind household pairing (`App.tsx`) → gate only on household screens; Studio could take the start screen on boot (`state.tsx`) → removed, Studio stays in nav; new launcher start screen; Back at root called `window.close()` (with the companion running that bounces straight back) → exit dialog; scheduled mode changes only applied on Our Home → also on launcher; crash Boundary wipes `vhome.*` keys → launcher layout uses `vhomeLauncher.v1`.

**Needs the real TV:** every SSAP call; LG Home app ID on firmware 43.04.26; Home redirect; app and HDMI launch IDs; `listLaunchPoints` from the web app; timer direct call vs handoff; layout + pairing surviving `install-tv.sh`. Existing docs are history, not proof of current behaviour.
