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
| Volume, mute, picture controls | NOT SUPPORTED in UI | hidden until verified |
