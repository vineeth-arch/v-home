# V/HOME Phone Watcher — Implementation Plan

> **For agentic workers:** Planned on Opus 5.5. Executed by Sonnet 5.5 subagents in waves (superpowers:dispatching-parallel-agents). Each agent owns a disjoint file set and works in its own worktree; nobody edits a file another agent owns. Steps use `- [ ]`. At execution start, copy this file to `docs/superpowers/plans/2026-10-21-android-watcher.md`.

**Goal:** A small Android app on the owner's daily phone (unplugged) that does the Mac companion's job, redirecting LG Home to V/HOME. It runs only while the phone is on home Wi-Fi.

**Architecture:** A Wi-Fi network callback starts a foreground service. The service finds the TV and proves it is the home TV by its pinned certificate. It then holds one push-driven `wss://TV:3001` SSAP socket with no wake lock and feeds foreground-app events into a Kotlin port of `companion/vhome_companion/watcher.py`. The service stops when Wi-Fi is lost.

**Tech stack:** Kotlin, minSdk 26 / targetSdk 35, OkHttp 4.12 (WebSocket), kotlinx-coroutines, `org.json`, plain Views (no Compose). Tests use JUnit4, `mockwebserver` and `okhttp-tls`, plus `org.json:json` for the JVM.

**Spec:** this plan's Context and Decisions sections; `docs/ANDROID.md` (fragility facts); `docs/OPEN-SOURCE-INTEGRATION-MATRIX.md` §5 (3001 only, power-state gating, boot retry).

## Context
- The Mac companion only redirects Home while the Mac is awake.
- The owner wants the watcher on their daily phone, unplugged most of the day, running only at home, with low battery cost.
- The Termux route needs a CPU wake lock all day plus Tasker. Rejected.

## Decisions (first pass, plus fixes from the failure review)
| # | Decision | Failure it prevents |
|---|---|---|
| D1 | `registerNetworkCallback(request, PendingIntent)` → `NetworkReceiver` starts the service. Inside the service, a normal in-process `NetworkCallback.onLost` stops it. | The PendingIntent form only reports "available", never "lost". |
| D2 | `BootReceiver` (BOOT_COMPLETED, MY_PACKAGE_REPLACED) re-registers D1. | Callback registrations are lost on reboot or app update. |
| D3 | "Home" = TV reachable **and** its leaf certificate SHA-256 equals the stored pin. No SSID, no location permission. | Reading the SSID needs background location. |
| D4 | Try the saved host first. On failure, send an SSDP M-SEARCH for `urn:lge-com:service:webos-second-screen:1` (multicast lock held ≤3 s), then pin-check each responder and save the new host. | The TV's IP already changed once (.224→.225). |
| D5 | Every socket is opened with `network.socketFactory` of the Wi-Fi `Network`. | VPN active, or Wi-Fi "no internet" routing traffic over mobile data. |
| D6 | Trust-on-first-use happens **only** in the Pair flow (user taps Pair; the TV shows a prompt). The service never trusts a new cert. A mismatch means "not home": stop quietly and log. | Silently trusting someone else's TV or network. |
| D7 | Foreground service type `connectedDevice`. Permissions: `FOREGROUND_SERVICE`, `FOREGROUND_SERVICE_CONNECTED_DEVICE`, `CHANGE_NETWORK_STATE`, `ACCESS_NETWORK_STATE`, `ACCESS_WIFI_STATE`, `CHANGE_WIFI_MULTICAST_STATE`, `INTERNET`, `POST_NOTIFICATIONS`, `RECEIVE_BOOT_COMPLETED`, `REQUEST_IGNORE_BATTERY_OPTIMIZATIONS`. | Android 14+ type requirement. `dataSync` would be capped at 6 h/day on 15+. |
| D8 | The app asks for the battery-optimisation exemption. On Android 12+ this also allows starting the FGS from the background receiver. If the exemption is missing, the app posts a notification "Tap to start watching" instead of crashing. | Background FGS start restriction (`ForegroundServiceStartNotAllowedException`). |
| D9 | No wake lock. SSAP ping every 90 s (the Mac uses 10 s). | The 10 s ping is the main battery drain on an unplugged phone. |
| D10 | TV unreachable → backoff 5 s ×2 up to a 300 s cap with ±20 % jitter, forever while on Wi-Fi. | Busy-looping while the TV is off. |
| D11 | Subscribe to `ssap://com.webos.service.tvpower/power/getPowerState`. Home events are ignored unless the state is `Active`. On a transition to Active, call `watcher.onPowerActive(now)`, which clears the failure window. | A redirect waking the TV from Active Standby. The breaker tripping while the TV's app manager is still booting. |
| D12 | After a failed launch, the service retries the same launch every 2 s for up to 20 s before reporting `ok=false`. | The first Home press after power-on failing while webOS boots. |
| D13 | Owner turns on the TV's Quick Start+, so 3001 stays up in standby and the socket survives. Power-on then arrives as a pushed event, even while the phone is in deep Doze. | Deep Doze delays reconnect timers by up to ~9 min. |
| D14 | Clock = `SystemClock.elapsedRealtime()/1000.0`. | `uptimeMillis` stops during deep sleep and breaks the time windows. |
| D15 | The pause state persists in Prefs. The notification has a Pause/Resume action. | Losing the breaker's pause across a service restart, which could cause a crash loop. |
| D16 | Unload the Mac launchd agent once the phone passes Wave 3. | Two watchers both redirecting trip the breaker. |

Accepted limit: when the phone is away or dead, nobody at home gets a redirect (LG Home shows).

## Global Constraints
- Package `com.designinnsaeit.vhome.watch`, project dir `android/` at the repo root.
- SSAP register payload: copy it exactly from `ssap.py:_register`, with `pairingType: "PROMPT"`, `forcePairing: false` and the unsigned manifest `{"manifestVersion":1,"appVersion":"1.1","permissions":[...]}`. Copy the `PERMISSIONS` list from `ssap.py` into `app/src/main/assets/manifest.json`. Never send a `signed` block, because the TV answers "403 blacklisted certificate".
- Port 3001 only. Never use 3000.
- URIs: `ssap://com.webos.applicationManager/getForegroundAppInfo`, `ssap://system.launcher/launch` (payload `{"id": vhomeId}`), and the power-state URI from D11.
- Watcher constants are copied verbatim: `CONFIRM_S=10`, `FAIL_WINDOW_S=60`, `FAIL_LIMIT=3`, `REDIRECT_WINDOW_S=120`, `REDIRECT_LIMIT=5`, `DOUBLE_HOME_S=3`.
- Defaults: `homeIds=["com.webos.app.home"]`; `vhomeId` = the `id` field of `webos/appinfo.json`. Both are editable in Settings.
- Log the client key only redacted, as `ssap.py:redact` does.
- Ponytail: no DI framework, no Compose, no Room. One Activity.

## Review Focus (each line has a pinning test in its owning task)
1. TV gets a new DHCP IP → SSDP rediscovers it and the pin is checked (Task B2 `findsTvAtNewIpByPin`).
2. First Home after TV power-on → no pause from boot-time failures (Task B1 `powerActiveClearsFailures`, Task C `launchRetriedWhileBooting`).
3. Phone on a café Wi-Fi with a host at the same IP → pin mismatch, no connect, no trust (Task B3 `mismatchedPinRejected`, Task B2 `noTrustOutsidePairing`).
4. Home pressed while the TV is in Active Standby → no launch (Task C `homeIgnoredUnlessActive`).
5. V/HOME crashing in a loop → pause after 5 redirects in 120 s, and the pause survives a service restart (Task B1 `redirectBreakerPauses`, Task C `pausePersists`).

---

## Wave 0 — Opus, sequential (contracts and scaffold; blocks everything)

### Task A: Toolchain, scaffold, contracts
**Files (Opus owns these; no later agent edits them):** `android/settings.gradle.kts`, `android/build.gradle.kts`, `android/app/build.gradle.kts`, `android/gradle/wrapper/*`, `android/gradlew`, `android/app/src/main/AndroidManifest.xml`, `android/app/src/main/assets/manifest.json`, `.../watch/Contracts.kt`, `.../watch/Prefs.kt`, `android/.gitignore`.

**Produces (`Contracts.kt`):**
```kotlin
enum class Level { DEBUG, INFO, WARNING, ERROR }
sealed interface Action {
  data class Log(val text: String, val level: Level = Level.INFO) : Action
  data class Launch(val token: Int, val appId: String) : Action
  data class Pause(val reason: String) : Action
}
data class Snapshot(val paused: Boolean, val lastApp: String?, val pending: Boolean,
  val redirects: Int, val ok: Int, val failed: Int, val escapes: Int,
  val lastLatencyS: Double?, val lastFailure: String?)
class ConfigError(msg: String) : IllegalArgumentException(msg)
data class Config(val host: String?, val clientKey: String?, val pin: String?,
  val vhomeId: String, val homeIds: List<String>, val doubleHomeEscape: Boolean, val paused: Boolean)
class NotPaired(msg: String) : Exception(msg)
class PinMismatch(msg: String) : Exception(msg)
interface TvSession {                      // implemented by SsapClient (B3)
  val certSha256: String?
  suspend fun open(onPrompt: () -> Unit = {}): String          // returns the client key
  suspend fun request(uri: String, payload: JSONObject = JSONObject(), timeoutMs: Long = 10_000): JSONObject
  fun subscribe(uri: String, payload: JSONObject = JSONObject()): Flow<JSONObject>
  fun close()
}
```
`Prefs.kt`: `object Prefs { fun load(ctx: Context): Config; fun save(ctx: Context, c: Config) }`, backed by SharedPreferences in private mode.

- [ ] Owner installs the toolchain (MY STEPS 1). Verify with `java -version` (17+) and `sdkmanager --list_installed` (shows `platforms;android-35` and `build-tools;35.0.0`).
- [ ] Generate the Gradle wrapper (`gradle wrapper --gradle-version 8.10`). Write the build files with all deps from the Tech stack line, including `testImplementation("org.json:json:20240303")` because the Android stub `org.json` throws on the JVM.
- [ ] Write the manifest with every D7 permission, the service declaration with `foregroundServiceType="connectedDevice"`, and both receivers.
- [ ] Write `Contracts.kt`, `Prefs.kt` and `assets/manifest.json`. Add empty `object`/`class` stubs for B1–B4 and C so the project compiles; each agent replaces its own stub file.
- [ ] `cd android && ./gradlew assembleDebug testDebugUnitTest` → BUILD SUCCESSFUL.
- [ ] Commit `feat(android): scaffold phone watcher + contracts`.

---

## Wave 1 — 4 Sonnet agents in parallel, one worktree each, disjoint files
Each agent prompt contains: this plan's Global Constraints, Contracts.kt, its own task, and these rules. Use ponytail (least code that works). Use caveman for the final report. Don't touch files outside your list. Run only your own test class: `./gradlew testDebugUnitTest --tests '<class>'`.

### Task B1: Watcher state machine (port)
**Files:** `.../watch/Watcher.kt`, `app/src/test/.../WatcherTest.kt`
**Consumes:** `Action`, `Level`, `Snapshot`, `ConfigError`.
**Produces:** `class Watcher(vhomeId: String, homeIds: List<String>, doubleHomeEscape: Boolean = false)` with `onConnected(now: Double)`, `onForeground(appId: String?, now: Double)`, `onLaunchResult(token: Int, ok: Boolean, now: Double, error: String = "")`, `onTick(now: Double)`, `onPowerActive(now: Double)`, `pause(reason: String = "paused")`, and `resume()`, each returning `List<Action>`. Also `nextDeadline(): Double?`, `snapshot(): Snapshot`, and `var paused: Boolean`.
- [ ] Port every test in `companion/tests/test_watcher.py` to JUnit, one-to-one, keeping the names in camelCase. Add `powerActiveClearsFailures`: two failures, then `onPowerActive`, then one failure → no Pause. Also add `redirectBreakerPauses`.
- [ ] Run → FAIL (stub).
- [ ] Port `watcher.py` line for line. `onPowerActive` clears `failures` only.
- [ ] Run → PASS. Commit.

### Task B2: Discovery
**Files:** `.../watch/Discovery.kt`, `.../DiscoveryTest.kt`
**Produces:** `object Discovery { fun parseSsdpLocation(response: String): String?` (returns the host from the `LOCATION:` header when `ST`/`USN` contains `webos-second-screen`); `suspend fun findTv(savedHost: String?, pin: String, probe: suspend (String) -> String?, ssdp: suspend () -> List<String>): String? }`. `probe(host)` returns the cert SHA-256 or null. The function tries `savedHost` first, then each SSDP host, and returns the first host whose probe equals the pin. Also `fun ssdpSearch(ctx: Context, network: Network): List<String>`: a multicast lock held ≤3 s, an M-SEARCH to 239.255.255.250:1900 over a socket bound to `network`, collecting responses for 3 s.
- [ ] Tests: `parsesLgResponse`, `ignoresNonLg`, `savedHostWinsWhenPinMatches`, `findsTvAtNewIpByPin`, `noTrustOutsidePairing` (every probe mismatches → null, and `findTv` never returns a host whose pin differs). Then FAIL → implement → PASS → commit.

### Task B3: SSAP client + pinning
**Files:** `.../watch/PinTrust.kt`, `.../watch/SsapClient.kt`, `.../SsapClientTest.kt`
**Produces:** `object PinTrust { fun sha256Hex(der: ByteArray): String; fun client(pin: String?, trustNew: Boolean, socketFactory: SocketFactory, onCert: (String) -> Unit, pingSeconds: Long = 90): OkHttpClient }`. The client uses a custom `X509TrustManager` that accepts only when the leaf SHA-256 equals `pin`, or when `trustNew` is set and `pin == null`, plus a hostname verifier that accepts all, because the pin is the identity. Also `class SsapClient(host: String, clientKey: String?, pin: String?, trustNew: Boolean, socketFactory: SocketFactory, http: OkHttpClient? = null) : TvSession`, and `suspend fun probePin(host: String, socketFactory: SocketFactory): String?` (TLS handshake only, timeout 3 s).
Behaviour mirrors `ssap.py`: request ids, subscribe ids, the error-frame surfacing, the blacklist message, a 15 s register wait when a key exists, and a pair timeout of 60 s.
- [ ] Tests use `MockWebServer` + `HeldCertificate`: `matchingPinConnects`, `mismatchedPinRejected` (throws `PinMismatch`), `registerReturnsClientKey`, `registerErrorBlacklistMessage`, `subscribeDeliversPayloads`, `requestTimesOut`, `redactsClientKey`. Then FAIL → implement → PASS → commit.

### Task B4: Settings UI + pairing + network/boot receivers
**Files:** `.../watch/MainActivity.kt`, `res/layout/activity_main.xml`, `res/values/strings.xml`, `.../watch/NetworkReceiver.kt`, `.../watch/BootReceiver.kt`, `.../watch/HomeNetwork.kt`, `.../HomeNetworkTest.kt`
**Consumes:** `Prefs`, `Config`, `SsapClient`/`probePin` (B3 signatures; compile against the stubs), `Discovery.findTv`.
**Produces:** `object HomeNetwork { fun register(ctx: Context); fun wifiRequest(): NetworkRequest }` (the D1 PendingIntent registration, idempotent). `NetworkReceiver` starts `WatcherService` with `startForegroundService`; on `ForegroundServiceStartNotAllowedException` it posts the D8 "Tap to start" notification. `BootReceiver` calls `HomeNetwork.register`.
UI, a single screen using the impeccable skill for copy and layout clarity:
- TV IP field and a Pair button. Pairing runs SsapClient with `trustNew=true`, shows "Accept the prompt on your TV", then saves the key and pin.
- V/HOME id and LG Home id fields.
- A battery-exemption row with a button that opens `ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS`.
- A notification-permission row.
- A status line: last redirect latency, paused or watching.
- A Pause/Resume button.
- A "Watching starts automatically on home Wi-Fi" line.

Call `HomeNetwork.register` in `onCreate`.
- [ ] Tests (Robolectric is not allowed, so use a pure function): `wifiRequestHasWifiTransport`, and a `pairingSavesKeyAndPin` test on an extracted `fun applyPairing(c: Config, host: String, key: String, pin: String): Config`. Then FAIL → implement → PASS → `assembleDebug` → commit.

---

## Wave 2 — 1 Sonnet agent (needs all of Wave 1 merged)

### Task C: WatcherService (wiring)
**Files:** `.../watch/WatcherService.kt`, `.../watch/Runner.kt`, `.../RunnerTest.kt`, `docs/ANDROID.md` (rewrite to the daily-phone design; keep the Termux text as an "Alternative" appendix).
**Runner** is the pure, testable core, ported from `cli.py` `Runner`: `class Runner(watcher: Watcher, session: TvSession, prefs: (Boolean)->Unit, clock: () -> Double)` with `suspend fun session()`. It subscribes to foreground and power state, applies Actions, and the launch retries per D12. Home is gated on power `Active` per D11. Pause is persisted through `prefs`.
**Service:**
1. `onStartCommand` → `startForeground` with a notification ("Watching TV" plus Pause/Resume actions).
2. Register `onLost` → `stopSelf`.
3. Loop: get the Wi-Fi `Network` → `Discovery.findTv`. On null, apply the backoff from D10, ported from `cli.backoff`.
4. Then `SsapClient` with `network.socketFactory` → `Runner.session()`.
5. On disconnect → backoff → retry.
- [ ] Tests with a fake `TvSession`: `homeIgnoredUnlessActive`, `launchRetriedWhileBooting` (first two launches error, third ok within 20 s → counted ok), `pausePersists`, `powerActiveCallsWatcher`, `backoffCapsAt300`. Then FAIL → implement → PASS.
- [ ] `./gradlew assembleDebug testDebugUnitTest` across the whole project → all green. Commit.

## Wave 3 — Opus review + device (owner present)
- [ ] Run `code-review` at high on the `android/` diff. Fix the findings.
- [ ] Copy `app/build/outputs/apk/debug/app-debug.apk` to `android/V-HOME-Watcher.apk` and send it to the owner with SendUserFile. The owner opens it on the phone, allows "Install unknown apps", installs it, grants the battery exemption and notifications, then taps Pair. Later updates are signed with the same debug key on this Mac, so they install over the old app and keep the settings. `adb` is only for the Doze test.
- [ ] Press Home ×5 → V/HOME each time. Read the latency in the status line.
- [ ] Wi-Fi off → the notification goes. Wi-Fi on → it returns within 10 s.
- [ ] Doze test: phone unplugged, screen off, and `adb shell dumpsys deviceidle force-idle`. Then TV standby → on → Home → the redirect works.
- [ ] Reboot the phone and unlock it → join Wi-Fi → watching resumes.
- [ ] After 24 h of normal use: Settings → Battery → record the app's share in `docs/ANDROID.md`.
- [ ] Any device failure → superpowers:systematic-debugging, not guess-fixing.
- [ ] Owner unloads the Mac agent (MY STEPS 5).

## Skills used
- brainstorming covered the alternatives: Termux, a native app, keeping the Mac.
- writing-plans shaped this plan, and dispatching-parallel-agents shaped the waves.
- ponytail and caveman apply to every agent. impeccable applies to B4. systematic-debugging applies to Wave 3.
- Skipped: graphify (the app is 6 files) and the web-only frontend/design skills.

## MY STEPS (owner, by hand)
1. Install the toolchain: `brew install --cask temurin@17 android-commandlinetools`. Then run `sdkmanager --licenses` (you accept the licences yourself), then `sdkmanager "platforms;android-35" "build-tools;35.0.0" "platform-tools"`.
2. Phone: install the APK I send (allow "Install unknown apps" for the app you open it with). USB debugging is needed only for the optional forced-Doze test. Recommended: in the router, reserve the TV's IP (DHCP reservation for the TV's MAC) so it never changes. The app copes without this, but rediscovery is slower than a fixed IP.
3. TV: Settings → General → Quick Start+ on.
4. Phone, after install: allow notifications, and set the battery mode to Unrestricted.
5. After the phone passes Wave 3: `launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.designinnsaeit.vhome-companion.plist`.

Estimate: Wave 0 about 30 min after the toolchain is in. Waves 1+2 about 1.5 h of wall clock in parallel. Wave 3 about 1 h with you and the TV, plus 24 h to measure battery.
