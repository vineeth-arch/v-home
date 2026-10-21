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
