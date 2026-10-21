# V/HOME capabilities (sanitized; only what actually happened on the TV)

TV: LG 43NU885BPLA, firmware 43.04.26, webOS SDK 11.0.1. Installed as `com.designinnsaeit.vhome` via `scripts/install-tv.sh`.

| Capability | Status | Evidence |
|---|---|---|
| Install and launch from Mac (`ares-install`, `ares-launch`) | VERIFIED | 2026-09-29, V/TV Sleep still installed afterwards |
| App renders on the TV (cloud build, IIFE, file://) | VERIFIED | user confirmed the pairing screen and dashboard |
| Anonymous sign-in + pairing code (stable, 6 chars) | VERIFIED | cloud DB: code approved 85 s after issue; TV became a paired display |
| Household content appears on TV after pairing | VERIFIED | user confirmed |
| Remote arrows move focus; OK activates; Back returns | VERIFIED | user confirmed all three |
| Pairing survives an in-place app upgrade (`install-tv.sh`) | VERIFIED (2x) | cloud DB: no new TV session after either reinstall, one display row |
| Pairing survives closing and reopening the app | NOT VERIFIED | |
| Pairing survives a TV restart | NOT VERIFIED | |
| Live weather on TV (Mumbai) | NOT VERIFIED | built and installed 2026-09-29, needs a TV check |
| Launch-failure message on TV | NOT VERIFIED | |
| New icon in LG app bar | NOT VERIFIED | installed 2026-09-29 |
| Power-on into V/HOME (settings only), tests A/B/C | NOT VERIFIED | see docs/OPENING.md |
| JioHotstar launcher ID | NOT VERIFIED | ID not yet captured; not guessed |
| Timer: direct call to V/TV Sleep service | NOT VERIFIED | |
| Timer: launch handoff to V/TV Sleep | NOT VERIFIED | |
| Launching Netflix / YouTube / Prime / HDMI from the launch strip | NOT VERIFIED | app IDs unproven |
| Quick Access number-button shortcut | NOT VERIFIED | |
| Apps screen (plain text list) and launch of listed apps | NOT VERIFIED | built 2026-09-30; app IDs unproven except by test |
| Photos on TV (signed URL, offline cache) | VERIFIED in desktop preview only | not yet on the TV |
| TMDB search (needs TMDB token set by owner) | NOT VERIFIED with real TMDB | function deployed; auth paths tested (401/403/503) |
| Ambient photo frame on the TV (crossfade smoothness) | NOT VERIFIED | works in the local preview (2026-09-30): on-this-day photo first, crossfade to the next after 45 s |
| Screensaver veto while the photo frame is open (`registerScreenSaverRequest`) | NOT VERIFIED | best effort; needs a TV test |
| Installed-app list on the Apps screen (`listLaunchPoints` from the web app) | NOT VERIFIED | built 2026-09-30; falls back to the curated list if denied |
| Studio (business numbers) end to end | VERIFIED locally only | local fixtures 2026-09-30: sync, throttle, failed source kept as stale, names hidden until enabled, TV start screen; cloud needs Vineeth's read-only roles and secrets (docs/STUDIO.md) |
| Volume, mute, picture controls | NOT SUPPORTED in UI | hidden until verified |

## V/HOME 2.0 (2026-10-21) — desktop-tested vs TV-verified

Nothing below has been run on the TV yet (TV was off). "Desktop" = automated tests and the 1920x1080 desktop preview.

| Capability | Desktop | TV |
|---|---|---|
| Launcher opens first; works unpaired and offline | tested (shell tests, preview) | NOT VERIFIED (gate H3) |
| Remote focus on launcher grid, Settings scroll, Back → launcher, exit dialog | tested (preview + tests) | NOT VERIFIED |
| Layout editor: favorites, order, hide, folders, Save/Cancel | tested (preview + tests) | NOT VERIFIED |
| Layout + pairing survive `install-tv.sh` upgrade | n/a | NOT VERIFIED (gate H2) |
| Bundled catalog + icons from `tv-catalog/` | tested (build with sample catalog) | NOT VERIFIED |
| Companion pairing (wss:3001, unsigned manifest, cert pin) | tested with local fake TLS server | NOT VERIFIED (gate H0) |
| LG Home app id on firmware 43.04.26 | n/a | UNKNOWN until `diag --observe` |
| Home button → V/HOME redirect | state machine tested | NOT VERIFIED (gate H1: 20 trials) |
| Breakers, pause/resume, reconnect | tested | NOT VERIFIED (gates H5, H6) |
| `listLaunchPoints` from the web app | n/a | NOT VERIFIED (reported denied on some webOS versions) |
| App and HDMI launch ids | n/a | NOT VERIFIED |
| Timer schedule/status/cancel; handoff never shows a countdown | existing tests green | NOT VERIFIED (gate H4) |

Checklists H0–H6: [COMPANION.md](COMPANION.md).

## Hardware results, 2026-10-21 (LG 43NU885BPLA, TV 192.168.29.225)

First session with the TV on. Observed by the owner on screen, plus the companion log.

| Item | Result |
|---|---|
| IPK 0.2.0 installed with `ares-install`; V/TV Sleep still installed | VERIFIED |
| Companion pairing (wss:3001, unsigned manifest, certificate pinned) | VERIFIED: prompt accepted on the TV |
| `listLaunchPoints`, `getForegroundAppInfo`, `getExternalInputList` over SSAP | VERIFIED (supported). 25 apps and 3 HDMI inputs exported with icons |
| LG Home app id | VERIFIED: `com.webos.app.home` |
| Home button -> LG Home flashes -> V/HOME opens | VERIFIED: 11 of 11 redirects succeeded, 0 failed, in manual tests across Netflix and other apps. Latency from the log: 0.17 s to 5.7 s (mostly under 1 s). This is NOT the full 20-trial protocol (H1) and is not split by app/HDMI |
| Safety limit (more than 5 redirects in 2 minutes pauses the watcher) | VERIFIED: tripped when Home was pressed 6 times in 5 seconds; `resume` re-armed it |
| `pause` / `resume` | VERIFIED |
| Login item (launchd) connects to the TV without a Local Network block | VERIFIED once, after the helper had already connected from a terminal |
| JioHotstar launcher id | `hotstar` (from `listLaunchPoints`) |
| Netflix `netflix`, Prime `amazon`, YouTube `youtube.leanback.v4`, HDMI `com.webos.app.hdmi1..3` | ids confirmed present in the TV's own list; launching each from V/HOME not yet checked one by one |
| Launcher look (colour tiles, full scrolling list, inputs at the bottom) | Owner reviewed the first version on the TV and asked for bigger tiles, app-coloured backgrounds, the full list and HDMI below; reworked, not yet re-checked |
| Pairing survives in-place upgrade of 0.2.0 (H2) | NOT CHECKED |
| Launcher usable with Wi-Fi off (H3), timer (H4), Mac sleep/wake (H5), multi-hour run (H6) | NOT RUN |

## Sleep timer, 2026-10-21 (owner-observed on the TV)

| Item | Result |
|---|---|
| Direct service call from V/HOME to V/TV Sleep | DENIED by the TV: `denied method schedule for category "/"` |
| One-click timer: press a preset, V/TV Sleep confirms, V/HOME reopens with the confirmed time (V/TV Sleep 0.1.1, V/HOME 0.2.1) | VERIFIED working by the owner, including Cancel |
| 15 min preset | added |
| TV actually switches off at the set time | NOT CHECKED |
| Status stays correct if the timer is changed in the V/TV Sleep app or from an iPhone | NOT SUPPORTED: V/HOME only knows the last result V/TV Sleep sent back |
