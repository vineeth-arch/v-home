# Open-source integration matrix (V/HOME 2.0)

Research date: 2026-10-21. Method: GitHub API (metadata, trees, source files, issues). Nothing was installed or run, and nothing here was tested on the TV. "Head" is the first 10 characters of the default-branch head SHA at inspection time.

Target stack: webOS TV 43NU885BPLA, firmware 43.04.26, Developer Mode, no root. Web app on Chromium 108 (build target `chrome108`, one IIFE), React 19, plain CSS. Mac companion in Python 3.11 with `websockets` only.

Model/firmware caveat: public reports tie the SSAP pairing change to firmware numbers from 43.00.92 upward (LGTVCompanion issue 351), and 43.04.26 is above that number. But "43NU885B" reads like an older LG model name, and the reports all concern 2022-2026 models. I could not resolve this from the repos. The first companion run should log `hello` and `system/getSystemInfo` output (`deviceOSVersion`, `deviceOSReleaseVersion`) so the docs can record the real platform.

## 1. What V/HOME already has (from the audit and code)

- Spatial focus and Back stack: `src/tv/focus.ts` (`pickNext`: primary-axis distance plus 2x cross-axis offset, `BackStack`), `src/tv/FocusProvider.tsx` (key handling for 37-40, 13, 461/27/8; focus restore on `visibilitychange`; scopes for overlays). Tested.
- Luna bridge with unknown-result timeouts (`src/adapters/platform.ts`), `parseLaunchPoints` / `allApps` / `isValidAppId` in `src/shared/apps.ts`, curated `CANDIDATE_APPS`, paged app list, plain CSS transitions, `target: 'chrome108'` IIFE build (`vite.tv.config.ts`), `disableBackHistoryAPI: true`.
- Not yet verified on the TV (docs/AUDIT-2.0.md, docs/CAPABILITIES.md): every SSAP call, the LG Home app ID on this firmware, app and HDMI launch IDs, `listLaunchPoints` from the web app.

## 2. Per-repository assessment

Format per repo: facts first, then the verdict. "Root" lines are flagged because V/HOME must never require root.

### 1. NoriginMedia/Norigin-Spatial-Navigation
- Head f34e75f850 (2026-09-25). Releases: core 4.1.2 (2026-09-25), react 3.3.0 (2026-07-30). Active, 490 stars, 8 open issues. License MIT (verified, `LICENSE`).
- Compatibility: React peer range `>=16.8.0` (packages/react/package.json), so React 19 is allowed; its dev/test setup uses React 18. Pure DOM and `getBoundingClientRect`, no new browser APIs I could find, so Chromium 108 is plausible. Not tested by me.
- Useful: focus tree with parents/containers, remembered child focus (`preferredChildFocusKey`), `measureChildrenLayout` option (2026-07-30) to skip child measuring, visual debugger (`packages/core/src/VisualDebugger.ts`), RTL support, focus on pointer. Core logic is one 58 KB file, `packages/core/src/SpatialNavigation.ts`.
- Root-dependent: none.
- Complexity: M-L (replace `FocusProvider`, re-map every `useFocusable` call and the layer/scope model, re-test).
- Performance: measures layout on key press with a throttle, plus per-node layout bookkeeping. Heavier than V/HOME's single `getBoundingClientRect` sweep of the active scope. Not measured on the TV.
- Overlap: high. V/HOME's 130 lines already do nearest-neighbour focus, Back layers, and focus restore.
- Recommendation: **reject for now.** Existing focus works on the TV (VERIFIED in CAPABILITIES). Revisit only with a measured failure (see section 5A for the failure modes that would justify it).

### 2. chros73/bscpylgtv
- Head 191e8957a1 (2026-09-30). v0.5.5 (2026-09-30). Active, 366 stars. License MIT (`LICENSE.txt`).
- Compatibility: Python >=3.8. Depends on more than `websockets` (sqlite key store `storage_sqlitedict.py`, optional numpy). Not "stdlib + websockets".
- Useful: the original source of the manifest and permission list (`bscpylgtv/manifest.py`, includes the shared signed block, which is the blacklisted one), endpoint names (`endpoints.py`), button list (`buttons.py`), `get_apps_all`, `set_input`, `toggle_screen`, `get_current_system_settings`. Picture calibration is out of scope.
- Root-dependent: none for what V/HOME needs. Several settings writes are blocked by permission tier on new firmware (see 3.B).
- Complexity: L as a dependency (does far more than needed); S as a reference.
- Overlap: SSAP session code V/HOME's companion will have anyway.
- Recommendation: **reference only.** Its stock manifest is the one that webOS 26-era firmware rejects, so do not copy it.

### 3. home-assistant-libs/aiowebostv
- Head 7ffa34f615 (2026-10-19). v0.10.0 (2026-08-28). Active, bot-maintained plus a code owner. 56 stars, 6 open issues. License Apache-2.0 (verified).
- Compatibility: Python >=3.11, uses `aiohttp` (not `websockets`). Good fit on version, wrong on dependency.
- Useful, with paths: `aiowebostv/handshake.py` (registration payload with no `signed` or `signatures` block, one flat permission list, `pairingType: PROMPT`, `appVersion` 1.1), `aiowebostv/endpoints.py` (URIs: `getForegroundAppInfo`, `listLaunchPoints`, `listApps`, `system.launcher/launch`, `tv/getExternalInputList`, `tv/switchInput`, `getPowerState`), `webos_client.py` (`connect()` tries `ws://:3000` then falls back to `wss://:3001`; power state mapping where "Active Standby", "Suspend", "Power Off" count as off; hello and system-info calls before registration "for newer webOS"), `examples/reconnect.py` (silent reconnect loop).
- Issues worth reading before writing the companion: #718 (403 "blacklisted certificate" on 43.21.71, existing keys die too), #720 (error frame hidden by generic message), #728 (dropping the signed block loses `WRITE_SETTINGS`), #744 (port 3000 hangs and never falls back to 3001), #707 (a subscription callback doing blocking I/O stalls the connect).
- Root-dependent: none.
- Complexity: S as reference, M-L as dependency.
- Recommendation: **reference only (primary protocol reference).** Port the registration shape and the 403 handling; do not add aiohttp.

### 4. spydey74/lg-webos-bsc
- Head 6e3cb345c7 (2026-10-05). Created 2026-08-21, 0 stars. **No license** (GitHub reports none; no LICENSE file in the tree).
- A Home Assistant custom component plus an "av-reconcile" pyscript for a soundbar. Contains probes (`tools/webos26_decision_gate_probe.py`) and claims about webOS 26 permissions (e.g. `setSystemSettings` 401 even with a good key, worked around via an alert bridge).
- Compatibility: Home Assistant only. Not our stack.
- Recommendation: **reject.** No license means no reuse. I read it only as unverified third-party evidence; the same claims appear independently in aiowebostv issues (#728) and the Home Assistant core issue, so I cite those instead.

### 5. belikh/ha-lg-webos-tv
- Head aa8b0fe687 (2026-10-19), default branch `bscpylgtv-integration`. Created 2025-12-05, 10 stars. License MIT.
- Home Assistant custom integration on bscpylgtv.
- Useful idea only: `custom_components/bscpylgtv/coordinator.py` has a liveness probe (`get_power_state` with a timeout) and a reconnect lock to catch "zombie" sockets that stay open after the TV sleeps. That pattern is directly relevant to F.
- Root-dependent: none. Complexity: S as reference.
- Recommendation: **reference only.**

### 6. foridpathan/smart-tv-starter
- Head ea8cecf8ff (2024-11-11). Stale, 7 stars. License MIT.
- A tutorial starter: Vite + React 18 + Norigin ^2.2.1 + Tailwind 3, with per-platform `appinfo.json` for webOS (`config/webos/appinfo.json`). Build target uses a browserslist, not an explicit Chromium floor.
- Nothing V/HOME lacks. Its appinfo shows optional keys (`requiredMemory`, `handlesRelaunch`, `supportTouchMode`, `bgColor`, splash fields) that V/HOME could consider, but their effect on this firmware is unverified.
- Recommendation: **reject** (stale, older stack, no new capability).

### 7. nitesh-k-sahu/tv-spatial-navigation-monorepo
- Head 5889a5ea40 (2026-07-24). 0 stars, very young. License MIT.
- Framework-agnostic core with a declared "region/row" model, React/Vue/Angular adapters.
- Overlap: V/HOME already has focus. A declared-region model does not match V/HOME's free-form screens, and it has no track record.
- Recommendation: **reject.**

### 8. jellyfin/jellyfin-webos
- Head ab47940464 (2025-11-04). Last release v1.2.2 (2024-04-10). Big project (874 stars) but this wrapper is quiet. License MPL-2.0 (verified; file-level copyleft).
- Useful: a shipping Store app showing webOS wrapper conventions: `disableBackHistoryAPI`, `frontend/js/webOS.js` (NativeShell host adapter, `screensaver` feature flag), `services/service.js` (a packaged Node service for UDP server discovery, so it needs the app + service package model).
- Root-dependent: none visible.
- Overlap: V/HOME already has the same appinfo flag.
- Recommendation: **reference only.** MPL would only bite on copied files; we copy nothing.

### 9. mariotaku/moonlight-tv
- Head cf96ecc72c (2026-09-17). v1.6.37 (2026-09-07). Active, 1504 stars. License GPL-3.0 (verified).
- Native C/SDL app (`type: native` in `deploy/webos/appinfo.json`), not a web app. Cannot be reused by a web launcher.
- One useful fact: `src/app/platform/webos/app_webos.c` launches LG Home with `luna://com.webos.applicationManager/launch` and `{"id":"com.webos.app.home","params":{"launchType":"homeKey"}}`. This confirms the app ID string `com.webos.app.home` for at least some firmware (a fact, not code to copy). Same ID appears in webos-launcher (17) constants.
- Recommendation: **reference only.** GPL, native, no reuse.

### 10. home-assistant/frontend
- Head a321b07bba (2026-10-20, branch `dev`). Huge (5.7k stars). License Apache-2.0 (verified).
- Lit web components, pnpm. Its `.browserslistrc` modern/legacy split is a good worked example of a deliberate browser floor. No webOS, kiosk, or spatial navigation code found by search.
- Recommendation: **reference only** for dashboard and tile design ideas (`src/panels/lovelace`, `src/panels/energy`). Nothing to integrate.

### 11. immich-app/immich
- Head 166e93559f (2026-10-20). 116k stars. License AGPL-3.0 (verified).
- Relevant concepts for the ambient photo frame: slideshow settings and state (`web/src/lib/stores/slideshow.store.ts`: shuffle/ordered, contain/cover/blurred-background look, delay, repeat, metadata overlay) and back/forward history (`web/src/lib/utils/slideshow-history.ts`, a tiny queue), "memories" (`server/src/dtos/memory.dto.ts`).
- Recommendation: **reference only, ideas not code.** AGPL: do not copy or adapt source. V/HOME already has on-this-day first.

### 12. motiondivision/motion
- Head 17141d348b (2026-10-20). v14.5.0 (2026-10-20). Very active. License MIT.
- React peer `^18 || ^19`. The package's own size budget (packages/framer-motion/package.json): `m` core about 5 kB, `m` + DOM animation about 28.7 kB, full `motion` about 42 kB (gzip figures per its tooling; unverified by me).
- Overlap: V/HOME uses CSS transitions that already work. Any JS-driven animation adds main-thread work on a TV CPU.
- Recommendation: **reject for now.** Revisit only if a specific animation cannot be done with CSS transform/opacity.

### 13. TanStack/virtual
- Head 887e971722 (2026-10-20). virtual-core 3.19.6, react-virtual 3.14.21. License MIT. React 16.8-19 peer.
- Uses `ResizeObserver`, scroll listeners, `scrollend` when present (`packages/virtual-core/src/index.ts`); Chromium 108 has all of these.
- Overlap: V/HOME's app list is paged; with tens to low hundreds of tiles there is nothing to virtualise. It also complicates spatial focus, since off-screen nodes are not in the DOM and `getBoundingClientRect` cannot see them.
- Recommendation: **reject for now.**

### 14. OmkarK97/webos-vibehack
- Head 31a518aef2 (2026-10-19). 113 stars, 2 open issues. Tested by the author on an OLED C6, firmware 43.21.79, webOS 26.
- **License: MIT.** GitHub's API reports NOASSERTION only because the LICENSE file also carries an OFL font notice after the MIT text. The MIT text is intact: "Copyright (c) 2026 Gathin" and "Copyright (c) 2026 OmkarK97". Outfit font is OFL 1.1 (separate; do not bundle it by accident).
- Files and what they do:
  - `lgtv.py`: opens `wss://TV:3001` with certificate checks off (LG's own CA), sends `register` with `pairingType: PROMPT`, `forcePairing: false`, an unsigned manifest of 28 permissions, stores the key per host in `.lgtv-key.json`. A comment states the signed manifest was rejected on new firmware with "403 blacklisted certificate" and unsigned still works.
  - `home-watch.py`: subscribes to `ssap://com.webos.applicationManager/getForegroundAppInfo`, and when `appId == com.webos.app.home` calls `ssap://system.launcher/launch`. Double Home within 3 s = stay on LG Home. Reconnect with 5 s doubling to 20 s. `ping_interval=10`.
  - `sync-apps.py`: `listLaunchPoints` and `tv/getExternalInputList`, writes `apps.js` and downloads icons, skips `hidden` points.
  - `home-watch-mac.sh`: LaunchAgent wrapper. Local Network permission for Python is needed on macOS.
- Defects I found by reading the code (not run):
  1. **Icon-drop bug (`sync-apps.py`):** when the icon fetch raises, the loop does `continue`, which drops the whole app from the list. Also `largeIcon` is used only when it starts with `http`; otherwise `icon` is fetched with `urllib`. A launch point whose icon is a local TV path (not http) will raise and the app vanishes. Likely cause of missing apps; unconfirmed on this TV.
  2. **Silent dead subscription (`home-watch.py`):** replies with `returnValue: false` or an error type are ignored (`appId` is simply `None`). A 401 on the subscription would leave the watcher "connected" and doing nothing.
  3. **Pairing exit (`lgtv.py`):** a pairing error calls `sys.exit`. `SystemExit` is not caught by the retry loop, so one 403 (for example after a firmware update invalidates the key) ends the watcher silently.
  4. **No gate on TV power state:** it will call launch on any foreground event; there is no check that the TV is awake.
  5. Key file written non-atomically with default permissions.
- Root-dependent: none. This is the only reference that does the Home-button job without root.
- Complexity: M (rewrite the watcher in about 150 lines, reusing the protocol shape).
- Performance: companion only; no TV-side cost. The launcher UI in the same repo is plain JS and not relevant.
- Recommendation: **adapt** (confirmed). Copy the session and sync shape under MIT with notice (see NOTICE.md), rewrite the watcher, fix defects 1-5.

### 15. Shantil-K/OpenLauncher
- Head 750398a761 (2026-09-22). 4 stars. `LICENSE` is GPL-3.0 (verified), but source files carry an `SPDX-License-Identifier: WTFNMFPL` header (e.g. `src/js/dpad.js`). The two conflict, so treat as GPL-3.0.
- `src/appinfo.json` requires `"requiredPermissions": ["all"]`. README says it needs `trustLevel: trusted` or Homebrew Channel root. Home replacement (`src/js/replacehome.js`) runs shell scripts as root (`src/access/replace/*.sh` patch system files).
- **Root-dependent: core features.** The Home replacement, wallpaper, and several others need root or trusted level.
- Non-root idea: edge-tolerant neighbour picking in `src/js/dpad.js` (a candidate must lie beyond the current item's edge; in-line items beat closer off-axis ones) and a mouse-vs-keyboard mode switch with a jitter threshold. V/HOME's `pickNext` could adopt the idea; write independently.
- Recommendation: **reference only (concept), no code.** GPL and root.

### 16. zzeppieri/webos-custom-home
- Head 41f8fc2cf3 (2026-07-23). 37 stars. License MIT, "Copyright (c) 2026 zzeppieri".
- Built on an LG OLED, webOS 24, Chromium 108 (same engine floor as V/HOME). Vite + React + Tailwind 4 + Framer Motion; Lightning CSS downlevels `oklch()` and `color-mix()` for Chromium 108.
- **Root-dependent (flag):** HOME takeover is an in-package Luna service (`service/service.js`) that reads `/dev/input/event*` (HOME key code 773) and relaunches the app; boot launch needs a Homebrew Channel init.d hook (`service/autostart.sh`); the eARC edition elevates the service. None of this works in plain Developer Mode.
- Non-root, reusable: `src/service/luna.ts` (`listLaunchPoints`, and a screensaver veto via `com.webos.service.tvpower/power/responseScreenSaverRequest` subscription), HDMI inputs are launched as apps (`com.webos.app.hdmiN`), the Lightning CSS/Chromium 108 note, tile layout ideas. `listLaunchPoints` being allowed from the web app is claimed here on webOS 24 (README "App IDs must match..."), but **17 says it is denied on webOS 6**; permission may vary by version and by whether the app is in a "trusted" tier. Test on the TV.
- Recommendation: **reference only.** Take the launch-point parsing idea (already credited in `src/shared/apps.ts`), not the root parts.

### 17. partridgeworks/webos-launcher
- Head 1e2c39b9a9 (2026-09-23). 38 stars, created the same day ("Initial release"), README says **no maintainer**. License MIT, "Copyright (c) 2026 webos-launcher contributors". Targets webOS 6 (Chrome 79).
- The most relevant non-root evidence for V/HOME's web-app side:
  - It records which Luna methods a sideloaded web app may call on webOS 6: allowed `applicationManager/launch`, `applicationManager/getAppLoadStatus` (`{appId}` -> `exist`), `com.webos.service.eim/getAllInputStatus`, `systemservice/getPreferences`. **Denied: `listLaunchPoints`, `listApps`, `getAppInfo`, `getForegroundAppInfo`** (README, "Luna calls used"). Also: web apps cannot read other apps' icons.
  - `src/lib/inputs.ts`: EIM returns `{id, appId, label, port, connected, icon}` per input; launching `appId` switches the input. `src/lib/launch.ts`: `launchLgHome()` = launch `com.webos.app.home`. `src/lib/pointer.ts`: `webOSSystem.setCursorHidden(true)` on launch and on `visibilitychange` / `webOSRelaunch`.
  - Does not take over Home; points to LG Input Hook (root) for that.
  - Optional live app list via the Homebrew Channel runs as root; off by default. Not for us.
  - `THIRD_PARTY_NOTICES.md` is a good model for our own notice file.
- Root-dependent: optional feature only.
- Recommendation: **reference only (high value).** Because the licence is MIT and the code is small, individual ideas can be adapted with a notice if used; at present nothing is copied.

## 3. Ranked table

Scores 1-5, higher is better. Stack compatibility = fit with Chromium 108, React 19, Python 3.11 + `websockets` only, no root. Complexity 5 = easy. Maintenance 5 = low burden. Security reflects the attack surface of using or adapting it. Total is a plain sum. The ranking shows reuse value; the last column is the actual decision.

| Rank | Repo | User value | Stack fit | Reliability | Complexity | Maint. | Security | Licence | Total | Decision |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 3 aiowebostv | 4 | 3 | 5 | 3 | 5 | 4 | 5 | 29 | reference only |
| 2 | 14 webos-vibehack | 5 | 4 | 3 | 4 | 3 | 3 | 5 | 27 | adapt |
| 2 | 17 webos-launcher | 4 | 5 | 3 | 4 | 2 | 4 | 5 | 27 | reference only |
| 4 | 12 motion | 2 | 4 | 3 | 3 | 4 | 5 | 5 | 26 | reject for now |
| 4 | 13 TanStack virtual | 1 | 4 | 4 | 3 | 4 | 5 | 5 | 26 | reject for now |
| 6 | 1 Norigin | 2 | 4 | 3 | 2 | 4 | 5 | 5 | 25 | reject for now |
| 7 | 2 bscpylgtv | 3 | 3 | 4 | 2 | 4 | 3 | 5 | 24 | reference only |
| 7 | 8 jellyfin-webos | 2 | 4 | 4 | 4 | 3 | 4 | 3 | 24 | reference only |
| 9 | 16 webos-custom-home | 3 | 3 | 3 | 3 | 3 | 2 | 5 | 22 | reference only |
| 9 | 10 HA frontend | 2 | 2 | 4 | 1 | 4 | 4 | 5 | 22 | reference only |
| 11 | 6 smart-tv-starter | 2 | 3 | 2 | 4 | 1 | 4 | 5 | 21 | reject |
| 12 | 7 tv-spatial-nav monorepo | 1 | 3 | 2 | 3 | 2 | 4 | 5 | 20 | reject |
| 13 | 5 ha-lg-webos-tv | 2 | 2 | 3 | 1 | 3 | 3 | 5 | 19 | reference only |
| 14 | 11 immich | 2 | 2 | 4 | 1 | 4 | 4 | 1 | 18 | reference only |
| 15 | 9 moonlight-tv | 1 | 1 | 4 | 1 | 4 | 3 | 1 | 15 | reference only |
| 16 | 4 lg-webos-bsc | 2 | 2 | 2 | 1 | 2 | 3 | 1 | 13 | reject |
| 17 | 15 OpenLauncher | 2 | 2 | 2 | 1 | 2 | 2 | 1 | 12 | reference only |

Ties share a rank. A high total means easy and safe to reuse, not that it should be adopted.

## 4. Confirm or challenge the preliminary decisions

- Adapt 14: **confirmed**, with the five defects above and the extra caution that its manifest has no signed tier (so no `getCurrentSWInformation`, direct `setSystemSettings` or similar; V/HOME does not need those).
- Reference 2/3 for pairing, manifest, inputs: **confirmed**, with a correction: bscpylgtv's own manifest is the blacklisted one. aiowebostv (>=0.9.2) is the right shape to follow. Do not depend on either.
- Reference 16/17: **confirmed, but 17 is more valuable than 16** for a no-root launcher, and 16's `listLaunchPoints`-from-web-app claim conflicts with 17's denied list.
- 15 reference only: **confirmed**, stronger: root/trusted plus GPL means treat as concept only.
- Reject 1/12/13: **confirmed.** Reasons are written in each entry. Add: do not virtualise, it breaks spatial focus.
- 8/9/10/11 reference only: **confirmed.** 9 is native C, 11 is AGPL.
- 4 reject: **confirmed** (no licence). One refinement: the claims it makes are corroborated elsewhere, so nothing is lost.
- Differs from the brief: repo 14's licence is MIT despite GitHub's NOASSERTION label; repo 15's licence is internally inconsistent (GPL-3.0 file, WTFNMFPL headers). Repo 6 and 7 get reject, not reference, because they add nothing.

## 5. Focus notes

### A. Remote focus quality
- Current design is sound for a paged grid: nearest neighbour with 2x cross-axis penalty, scoped overlays, Back stack, focus restore on `visibilitychange`.
- Weak points to check on the TV before changing anything: (1) a candidate behind the current item's edge is excluded only by `main <= 0` on centres, so wide and tall tiles beside each other can pick a neighbour that overlaps the current item; OpenLauncher's edge-based rule is the idea to compare. (2) Held keys fire repeated `keydown` events; `pickNext` runs `getBoundingClientRect` for every element in scope on each repeat, which is fine for dozens of tiles but untested at 150+. A cheap fix if needed: cache boxes per scope and invalidate on registration changes. (3) Only keyCode 13 is Enter; Magic Remote "wheel click" also sends 13 on webOS, so likely fine. (4) Coloured buttons (403-406) are free shortcuts, used by OpenLauncher. (5) Pointer: hide the cursor on foreground with `webOSSystem.setCursorHidden(true)` (webos-launcher `src/lib/pointer.ts`), or the Magic Remote cursor will sit over the grid. Mouse hover already syncs to focus in `useFocusable`.
- Trigger for revisiting Norigin: measured key-to-focus latency above a threshold the user can feel, or a layout where nearest-neighbour makes a wrong jump that cannot be fixed by tuning the score. Neither is observed.

### B. webOS 26 and newer firmware pairing compatibility
- Evidence chain (all third-party reports, none from this TV): Home Assistant core issue 172703 and aiowebostv #718/#720/#728; LGTVCompanion issue 351.
- Port 3001 TLS: current firmware serves SSAP at `wss://TV:3001` with LG's own certificate chain; clients disable verification. Port 3000 (`ws://`) may accept TCP but never answer the WebSocket handshake (aiowebostv #744; #718 also saw resets), so **connect to 3001 first and do not rely on 3000**. vibehack already does this.
- Signed manifest: the widely shared LG Remote App manifest (`appId com.lge.test` with `signed` and `signatures`) is rejected immediately on affected firmware with `403 Pairing rejected: blacklisted certificate detected`. No prompt is shown, and previously issued keys stop working too (aiowebostv #718: the TV did not even look at the key). An unsigned manifest (no `signed`, no `signatures`, a single flat `permissions` list, `appVersion` 1.1, `pairingType: PROMPT`) pairs and shows the prompt (confirmed by several reporters on G5 43.21.x, and by vibehack on C6 43.21.79).
- What the unsigned tier lacks: the elevated tier is enforced on the signature itself. Moving the signed permissions into the unsigned list does not help (reporter on aiowebostv issue thread). Measured on one G5: with an unsigned key every read/subscription V/HOME needs worked (`getForegroundAppInfo`, `listLaunchPoints`, `listApps`, `getExternalInputList`, `getPowerState`, pointer socket); only `getCurrentSWInformation` returned 401. A separate report says direct `settings/setSystemSettings` returns 401 on an unsigned key. V/HOME needs neither. Launch worked in those reports (`system.launcher/launch`, `media_player.select_source`), but that is not our TV.
- Mixed reports: another reporter's older G4 (33.31.68) still accepted the signed manifest, and one reporter's 43.11.73 accepted the old pairing before 43.21.60 broke it. So acceptance depends on firmware. Plan: try the unsigned manifest first; fall back to nothing else; if the TV returns an error frame at register, print its text verbatim.
- Permission prompts: the first registration shows a prompt on the TV. The user must have the TV on and press OK. vibehack's README also mentions a TV setting for connecting from mobile apps (on the C6 under General -> Devices -> External Devices, "LG Connect Apps" or similar); the name varies, so the first-run doc should say "if no prompt appears, check the TV's mobile-app connection setting".
- Key handling: the key is bound to the manifest/app identity. If the manifest changes, re-pair. Do not change the manifest between releases without a migration note.
- Error handling the companion must have: treat an `error` frame at register as authoritative (surface it), do not `sys.exit` inside the retry loop, and distinguish "TV off / unreachable" (retry) from "pairing rejected" (stop retrying, tell the user, since retrying on 403 does nothing).

### C. Home-button watcher reliability
- No app can intercept the Home key without root. The only non-root approach is observing the foreground app from outside and relaunching. Root-based approaches (webos-custom-home reading `/dev/input`, OpenLauncher patching key filters, LG Input Hook) are excluded.
- vibehack's reported latency (LG Home shows about half a second) is the author's claim on a C6, not measured here. Expect a visible flash of LG Home each time.
- Reliability risks: (1) subscription returns an error and the watcher never notices (check `returnValue` on every message and on the first one in particular, then reconnect); (2) half-open socket after the TV sleeps or the network drops (use ws ping, as vibehack does at 10 s, plus a liveness probe like belikh's coordinator); (3) LG Home ID differs on this firmware (the string `com.webos.app.home` is used by moonlight-tv and webos-launcher on their firmware; unverified on 43.04.26, so log every foreground `appId` for a session and configure the ID from observation); (4) the escape hatch (double Home within 3 s) should be visible and configurable, because without it LG's own settings are unreachable; (5) a launch loop if V/HOME itself ever reports an unexpected ID; add a minimum interval and a counter; (6) power state: only redirect when the power state is active.
- Keep the double-Home escape; add a quick way to pause the watcher from the phone.

### D. App discovery and launching
- Two discovery paths. From the companion over SSAP, `ssap://com.webos.applicationManager/listLaunchPoints` works with a paired key (reporters and vibehack) and returns `id`, `title`, `icon`/`largeIcon`, `hidden`, and colours. `listApps` returns all apps including hidden ones and also worked unsigned on one G5.
- From the web app via Luna, the evidence conflicts: webos-launcher says `listLaunchPoints`/`listApps` are denied to sideloaded apps on webOS 6; webos-custom-home calls `listLaunchPoints` from a web app on webOS 24. V/HOME's current "Apps screen lists installed apps, falls back to curated list if denied" is the right design. Recommended backing path: **the companion syncs the list over SSAP and writes it to Supabase (or to the phone), and the TV reads it**, with `getAppLoadStatus` as a per-ID existence check for the curated list.
- Launch: `ssap://system.launcher/launch {id}` (companion) or `luna://com.webos.applicationManager/launch {id, params}` (web app, allowed). Both are used by shipped projects. App IDs seen in the wild include `netflix`, `youtube.leanback.v4`, `amazon`, `com.disney.disneyplus-prod`, `com.webos.app.hdmi1`; these differ by region and model, so only trust IDs observed on this TV.
- Icons: a web app cannot read other apps' icon files (webos-custom-home and webos-launcher both state it), so icons must be fetched by the companion over the TV's HTTP URLs, stored, and then served to the TV from the household store or bundled. The fetch must not drop the app on failure (the vibehack bug): fall back to a monogram tile.
- Hidden launch points should be skipped by default but kept in the sync so the user can unhide.

### E. HDMI input handling
- `ssap://tv/getExternalInputList` returns `devices` with `id` (e.g. `HDMI_1`), `appId` (e.g. `com.webos.app.hdmi1`), `label`, `port`, `connected`, `icon` (vibehack `sync-apps.py`, webos-launcher `src/lib/inputs.ts` via the Luna EIM `getAllInputStatus`). Launching the input's `appId` switches the TV to it; `tv/switchInput {inputId}` also exists (aiowebostv).
- The `appId` per input should be captured from this TV, not guessed. Store `{id, appId, label, port}` and use `appId` for launch. Show `connected: false` as dimmed, not hidden. Labels come from the user's TV input naming, so no extra config.
- The web app can call EIM directly (allowed on webOS 6 per webos-launcher), which gives live connection state without the companion. Verify on the TV.

### F. Startup and reconnect behaviour
- TV standby: when the TV is off, port 3001 is not available and `connect` fails; vibehack backs off 5 s -> 20 s. Fine. Use jitter and keep retrying forever; do not exit.
- Quick Start+ / Active Standby: the TV may keep the network up in a reduced state. In that state sockets can connect, power state reports "Active Standby" (aiowebostv treats that as off), and a launch may wake the screen. Gate redirects on power state (subscribe `com.webos.service.tvpower/power/getPowerState`; needs READ_POWER_STATE, already in the manifest).
- After power-on, port 3000 can hang for minutes (#744); using 3001 only avoids it. After power-on the application manager may not be ready; webos-custom-home retries launch every 2 s for up to 60 s on boot (`bootLaunch`). Copy that retry idea for the first launch after wake.
- Zombie connections: ws ping (10 s) handles most; add an application-level probe (call `getPowerState` with a timeout) every minute.
- Wake-on-LAN: aiowebostv's `power_on` is an SSAP call; turning on a fully-off TV needs Wake-on-LAN and that requires the MAC and TV setting. Out of scope unless wanted.
- Developer Mode session timer: vibehack reports Developer Mode sessions expire and need "Extend Session Time". If V/HOME stops launching after a long period, check this first. (LG's own docs should be consulted; unverified here.)
- Keys survive TV restarts only if the firmware keeps them; a firmware update can invalidate them (aiowebostv #718). The companion must detect and report it.

### G. TV memory and rendering performance
- V/HOME is a single IIFE with plain CSS: low baseline. Every candidate library adds JS: Norigin (58 KB source for the core, plus per-node bookkeeping), Motion (about 5 to 42 kB depending on features), TanStack virtual (small, but removes off-screen nodes). None solves a measured problem today.
- Safer wins: animate only `transform` and `opacity`; avoid `box-shadow` and `filter: blur` on large areas (the ambient photo frame crossfade is the first thing to measure); limit decoded image sizes (a 4K photo decoded as a bitmap is large on a TV with a few hundred MB for web apps); `requiredMemory` in appinfo is an unverified lever (appears in smart-tv-starter's template).
- OLED protection and idle behaviour (OpenLauncher has pixel shift and dimming) are worth a later look for burn-in on static launcher screens, if the TV is an OLED. 43NU885B is not an OLED, so it is low priority.
- Measure with the Web Inspector on port 9998 (webos-launcher README, available in Developer Mode) before and after anything. Nothing in this document has been measured on the TV.

## 6. Prioritised implementation backlog

Now (unblocks everything, no new dependency):
1. Companion `pairing`: unsigned manifest, `wss://:3001` only, surface `error` frames, never `sys.exit` in the loop, key file written atomically with mode 0600. Log `hello` and `getSystemInfo` once.
2. Companion `watch`: foreground subscribe with `returnValue` checks, ping 10 s plus liveness probe, power-state gate, backoff with jitter, double-Home escape, minimum interval, log all foreground app IDs to learn the real LG Home ID.
3. Companion `sync`: `listLaunchPoints` and `getExternalInputList`; icon failure falls back to monogram (fixes vibehack defect 1); skip `hidden`, keep a flag; write to the store the TV reads.
4. NOTICE.md in the repo (done in this branch) and a header comment in adapted files.

Next:
5. Web app: Apps screen reads the synced list; `getAppLoadStatus` existence checks for curated IDs; `setCursorHidden` on foreground; EIM input status directly if allowed.
6. Focus: edge-based exclusion in `pickNext` if wrong jumps are seen; box cache if latency shows up on long lists.
7. Pause/resume watcher from the phone; surface "pairing rejected" in the phone UI.

Later:
8. Photo frame ideas from Immich slideshow settings (look, delay, history), as independent code.
9. Wake-on-LAN, Developer Mode session reminder.
10. Revisit Norigin, Motion or TanStack virtual only with a measured failure.

## 7. Not verified on the physical TV

Everything. Specifically: the real model and platform behind "43NU885BPLA / 43.04.26"; whether the unsigned manifest pairs and shows a prompt; whether the signed one is rejected; whether `com.webos.app.home` is LG Home here and what the foreground event looks like on Home press; Home redirect latency; `listLaunchPoints` and `listApps` from SSAP and from the web app; HDMI `appId`s and EIM from the web app; launch IDs for installed apps; icon URL formats and whether they are http or local; behaviour in Active Standby and Quick Start+; reconnect timings; Developer Mode session expiry; web-app memory and crossfade smoothness. Third-party reports above come from other TVs and other firmware.
