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

## VNode (2026-10-25)

VNode is the Raspberry Pi Zero W that watches the TV so V/HOME works with the Mac asleep and the phone away. Guide: [VNODE.md](VNODE.md). API: [contracts/vnode-api-v1.md](contracts/vnode-api-v1.md).

### Automated evidence (desktop and CI)

These ran on the Mac, not on the Pi or the TV. They prove the logic, not the hardware.

| Check | Result | What it proves |
|---|---|---|
| Python tests, 217 tests, Python 3.13 with aiohttp 3.11.16 and websockets 15.0.1 (the versions Debian ships for the Pi) | pass | TV controller state machine and breakers against a fake TV; API auth, nonces, pairing-code limits, device controls limited to a fixed list of commands; LED signal bars and thermal guard; installer and archive-safety rules |
| Android JVM tests, 117 tests | pass | NodeClient against a TLS mock server (pin match and mismatch, 401, 409, 410, 426); stale-data label; the rule for switching back to standalone; the gating that keeps the phone's own watcher off in VNode mode; user-facing messages |
| `npm run check` | pass | The repository's check script (typecheck, tests, web build, TV build) passes; the VNode work does not touch the TV app |
| End-to-end TLS smoke test of `serve` on the Mac | pass | Real HTTPS on a self-signed certificate: pairing with a one-time code; 401 for a bad or missing token; 409 for a reused nonce; 410 for an expired nonce; 413 for a body over 4096 bytes; 422 for unknown fields and a missing reboot confirmation; 426 for a wrong API version; a phone revoking itself and then getting 401 |

### Hardware evidence (Pi Zero W)

Only what was measured before the install, 2026-10-25 07:06 UTC, with no V/HOME software on the Pi and the LEDs untouched.

| Item | Result |
|---|---|
| Board and OS | Pi Zero W Rev 1.1, armv6l, Raspbian 13.6 trixie, kernel 6.18.50+rpt-rpi-v6, Python 3.13.5, systemd 257.9 |
| Temperature | 42.7 to 43.8 C over 60 s (6 samples); load 0.01 to 0.08 |
| Power | `vcgencmd` throttled 0x0; hwmon `rpi_volt` under-voltage alarm 0. The kernel has no `get_throttled` file, so the node reads the hwmon alarm |
| Memory and disk | 102 of 426 MB used; 2100 of 3121 MB of `/` used, 856 MB free |
| Wi-Fi and time | wlan0 -67 to -69 dBm; NTP synchronized |
| Packages | python3-aiohttp 3.11.16 and python3-websockets 15.0.1 available from apt; python3-libgpiod 2.2.1, polkitd 126, curl 8.14 already installed |

After install, 2026-10-25 (release 0.1.0-f7baa2f, measured on the Pi):

| Item | Result |
|---|---|
| Installer on the Pi | Works. apt pulled python3-aiohttp 3.11.16, python3-websockets 15.0.1 and their 7 dependencies (765 kB download, 3.8 MB on disk); the apt step took about 15 minutes on the single core. Health check passed in 1 s. Update to a new release kept the node certificate (same node id). |
| Test suite on ARMv6 | All 222 Python tests pass on the Pi in 53 s (same suite as the Mac). |
| Services | vhome-vnode and vhome-leds active, 0 restarts. Reached from the Mac at `https://vnode.local:8443/v1/info`. |
| Phone discovery and pairing | The Samsung SM-A556E (Android 14, app 0.9.0) found "V/HOME node on vnode" by NSD at 192.168.29.9. Fingerprint shown on the phone matched `vnode pair-phone` (eb8d dd63 eeee 978c 6820 c558); paired with the code; the phone switched to VNode mode and its own watcher stopped (no service running). |
| TV paired through the Pi | Paired with the LG TV at 192.168.29.225 from the phone (the Pi found the TV by SSDP); owner accepted the prompt; status shows Connected and the app in front live. |
| TV power state | Not available on this TV: `getPowerState` answers "401 insufficient permissions" even with READ_POWER_STATE requested and after a fresh pairing. The phone's own watcher logged the same before this work. So standby cannot be detected on this model; the node keeps watching and its 10 s heartbeat falls back to a foreground read. |
| Memory and CPU, TV connected | vhome-vnode RSS 44.7 MB (peak 44.8 MB), CPU 0.60 % over 5 minutes; vhome-leds RSS 11.7 MB, CPU 0.17 %. Whole Pi 145 of 426 MB used. Idle before the TV was paired: 29.7 MB and under 0.01 % CPU. |
| Disk | Release 432 KB; packages 3.8 MB; 848 MB free on `/` after install. |
| Memory limit | Raspberry Pi OS boots with `cgroup_disable=memory`, so `MemoryMax=` in the units is not enforced on this kernel. Measured use is far below it. |
| LED heat test | 30 min LEDs off then 30 min on (brightness 2/31, Wi-Fi bars lit), TV connected, sample every 30 s: off mean 43.48 C (min 42.2, max 48.7 during the first minutes after the update), on mean 43.31 C (min 42.8, max 44.4); last 5 minutes 43.04 C off vs 43.26 C on. No throttling or under-voltage in either phase. The LEDs add no heat that this sensor can measure (under 0.3 C), so they stay on by default. The 70 C thermal guard never came close to triggering. |
| Home redirect from the Pi (20 trials) | pending (owner at the TV) |
| Mac asleep and phone away | pending |
| Pi restart, router restart, TV cold boot | pending |
| Multi-day run | pending |
| Backup and restore | pending |

### Capability values the node reports

`GET /v1/info` returns these. The app uses them to hide or explain controls.

| Capability | Value now | Meaning |
|---|---|---|
| launch, pause, tv_pair, diagnostics, device_controls | supported | The node does this. |
| leds | supported or unavailable | Supported when the LED service is running. Unavailable without the pHAT BEAT or with `--no-leds`. |
| timer | unavailable | V/TV Sleep stays the only timer. The node has no confirmed way to set it. Use the TV's own controls or V/TV Sleep. |
| catalog_sync | unavailable | App builds and the TV app list refresh stay on the Mac (`scripts/refresh-tv.sh`). |
| power_on_launch | disabled | Opening V/HOME at TV power-on is off by default. `unverified` would mean it is switched on but not proven on this TV. |

Unavailable means the node cannot do it and does not try. Disabled means it could be switched on but is off. Unverified means it is on but has not been shown to work on the real TV.
