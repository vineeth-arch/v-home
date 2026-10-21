# V/HOME Mac companion

Status: written and unit-tested against fakes (including a local TLS fake TV). Nothing here has been run against the real TV. Every behaviour about the TV is UNVERIFIED until the hardware checklists at the end are run. The TV model is LG 43NU885BPLA, firmware 43.04.26.

## What it does and does not do

LG's Home button cannot be overridden without root, and we never root the TV. So a small Python program on the Mac watches which app is in front on the TV, over LG's remote-control websocket (the one LG's phone app uses). When LG Home comes to the front it asks the TV to launch V/HOME. It also writes the TV's app and input list to `tv-catalog/` so the launcher can show real apps.

What you will see: LG Home appears briefly (a fraction of a second to a couple of seconds, UNVERIFIED) and then V/HOME replaces it. This is a redirect, not a launcher replacement. It only works while the Mac is awake, on the same network, and the TV is on. The webOS Developer Mode session still expires and still has to be renewed as before. The companion never powers on or wakes the TV, never sends anything to other apps or HDMI inputs, and never changes Mac sleep settings.

Safety rules built in: the TV's certificate is pinned at pairing and checked before the client key is sent; only four permissions are requested (LAUNCH, READ_RUNNING_APPS, READ_INSTALLED_APPS, READ_INPUT_DEVICE_LIST); an unknown or empty foreground app is never treated as Home; one launch per Home transition; a launch only counts as success if the TV accepted it and V/HOME came to the front within 10 seconds, with no automatic retry; three failed redirects in 60 seconds, or more than five redirects of any kind in 120 seconds, pause the watcher until you resume it.

The registration is unsigned. LG's shared "signed" manifest is rejected by affected firmware with "403 Pairing rejected: blacklisted certificate detected" before any prompt appears, so it is not sent. An unsigned key may lack some elevated permissions; the foreground, app list, input list and launch calls are reported to still work (UNVERIFIED on this TV, `diag` tells you).

## Setup

Python 3.11 or newer is needed. From the repo root:

1. Turn the TV on. The first pairing needs the TV awake so you can accept the prompt on screen.
2. Run `companion/install.sh install`. It copies the package and a virtualenv with the single pinned dependency (websockets 15.0.1) into `~/Library/Application Support/vhome-companion/`, and installs a user LaunchAgent. It does not use sudo. Re-run it as `update` after pulling new code.
3. For the commands below use the installed interpreter, for example `PY="$HOME/Library/Application Support/vhome-companion/venv/bin/python"` and then `"$PY" -m vhome_companion <command>`. From a checkout without installing you can use `cd companion && python3 -m vhome_companion ...` (with websockets installed, for example in `companion/.venv`).
4. Local Network permission (gate H0): macOS asks whether Terminal (or the Python you run) may find devices on your local network. Allow it in System Settings > Privacy & Security > Local Network. If you see "no route to the TV" while the TV is on, this is the first thing to check. A TV that is off can produce the same message.
5. Pair: `"$PY" -m vhome_companion pair --host <TV IP>`. A prompt appears on the TV; accept it within 60 seconds. This stores the client key (`client-key`) and the SHA-256 of the TV's certificate (`cert.sha256`), both mode 0600 in a 0700 directory. Use a fixed IP or DHCP reservation for the TV.
6. Calibrate the Home id: `"$PY" -m vhome_companion diag --observe 20`, press the Home button on the remote during the 20 seconds, and read the app ids printed. The id that appears when you press Home from, say, Netflix is LG Home (it is probably `com.webos.app.home`, UNVERIFIED). Save it with `"$PY" -m vhome_companion diag --save-home <id>`. The watcher refuses to start until at least one Home id is configured. `diag` also prints the `hello` payload and `system/getSystemInfo` so we learn the real platform, whether V/HOME is installed, and each capability as supported, denied, unavailable or unverified (LAUNCH stays unverified in `diag` because exercising it would interrupt whatever is on screen). If `diag` reports a 401 or 403, pairing was declined or the key is no longer valid; pair again.
7. Run `companion/install.sh update` once more (or `launchctl kickstart -k gui/$(id -u)/com.designinnsaeit.vhome-companion`) so the agent starts with the pairing and Home id in place. To watch in a terminal instead: `"$PY" -m vhome_companion watch`.

Settings live in `config.json` in the state directory: `host`, `vhome_id` (default `com.designinnsaeit.vhome`), `home_ids`, and `double_home_escape` (default false; when true, two distinct Home presses within 3 seconds skip the second redirect, so a quick double press stays on LG Home).

## Everyday commands

`status` shows pairing, the pause flag, whether the watcher is running and connected, and redirect counters. `pause` creates the pause flag, after which the watcher only observes; it is checked on every event. `resume` removes it, and also clears a breaker pause. `stop` runs `launchctl bootout` for the agent (it comes back at next login or after `install.sh update`). Logs are in `companion.log` (1 MB, three rotations; the client key is never logged).

The reliable escape to LG's real home screen: run `pause`, then press the native Home button. With double-Home enabled a quick double press also works, but pause is the one to trust.

## Catalog refresh

`"$PY" -m vhome_companion sync-catalog && ./scripts/build-tv.sh && ./scripts/install-tv.sh` (run from the repo root; pass `--out` to write elsewhere). It writes `tv-catalog/catalog.json` and `tv-catalog/icons/` per `docs/contracts/catalog-v1.md`. Icons are only downloaded from the TV's own address, at most 256 KB, and must be real PNG or JPEG; an icon that fails leaves the entry with `icon: null`. Entries marked `system: true` are internal helpers: anything the TV hides, anything under `com.webos.app.` other than browser, photo/video, music and screen share, and V/HOME itself. The write is atomic; if anything fails the previous catalog is left untouched and the command says so. Ids are de-duplicated case-insensitively and capped at 200.

## Mac sleep

While the Mac sleeps the watcher stops, so Home on the TV shows LG Home with no redirect. When the Mac wakes it reconnects by itself. The companion does not change sleep settings and does not hold the Mac awake. After any reconnect it only reconciles: it looks at what is in front and acts only if that is a configured Home id, never interrupting another app or an HDMI input. The circuit breakers stop any wake-time launch loop.

## Uninstall and rollback

`companion/install.sh uninstall` removes the agent, the virtualenv and the package copy and keeps pairing, config and logs. `companion/install.sh uninstall --purge` also deletes the pairing key, pinned certificate, config, state and logs (only its own files), then the folder if it is empty. To roll back to plain LG behaviour at any time, run `pause` (instant, reversible) or `uninstall`. The TV side needs nothing: V/HOME stays installed as a normal app. You may also revoke the pairing from the TV's settings if you wish.

## Troubleshooting

| Symptom | Likely cause and fix |
|---|---|
| "no route to the TV" | Local Network permission not granted for Terminal/Python, or the TV is off or on another network. |
| Pairing: "blacklisted certificate" | The signed manifest is not sent by this tool; if you still see it, save the `diag` output and report it. |
| Pairing times out | TV was off or the prompt was missed. Turn the TV on and run `pair` again. |
| "different certificate than the one pinned" | TV was reset or updated, or something is intercepting. If you are sure, `pair --host <IP> --repin`. |
| `diag` shows 401/403 or "denied" | Pairing declined or key invalid; pair again. |
| Watcher will not start | No Home id (calibrate), not paired, or another watcher already holds the lock. See `companion.log`. |
| Paused by itself | A breaker tripped (see log). Find the cause (V/HOME crashing, launch denied), then `resume`. |
| LG Home stays | Paused, Mac asleep, or the Home id is wrong; run `status` and `diag --observe`. |
| Redirect lands on V/HOME then LG Home again | V/HOME exiting or crashing on the TV; check the 5-redirect breaker in the log. |

## Hardware checklists (all UNVERIFIED until run)

H0, Local Network, pair, observe:
1. With the TV on, allow Local Network; run `pair`; accept the prompt.
2. Run `diag --observe 20`, press Home from three different apps; record LG Home's id and any other ids seen.
3. Save the id; confirm `diag` shows the four capabilities and whether V/HOME is installed; keep the `hello` and `getSystemInfo` output.

H1, twenty Home-return trials: for each of Netflix, YouTube, Prime Video and an HDMI input (five trials each), press Home and record, in a table with columns trial, source, redirected yes/no, latency seconds (from the log's "redirect ok in" line), unintended redirects.
1. Success rate is at least 19 of 20, with latency recorded.
2. Zero unintended redirects (no launch while in an app or HDMI input).
3. `pause` then native Home shows LG Home and stays there; `resume` restores the redirect.

H2, in-place upgrade: reinstall the V/HOME IPK over the existing one; pairing, `config.json` and the launcher layout survive and the redirect still works.

H3, launcher without the companion: with Wi-Fi off on the Mac, or unpaired, V/HOME still opens and works from the launcher list (curated fallback).

H4, timer: schedule, check status and cancel a timer from V/HOME while the companion runs; no interference.

H5, disruptions: Mac sleep and wake; Mac Wi-Fi loss and return; TV standby and power on; TV restart. After each, the watcher reconnects quietly, does not redirect unless the TV is actually on LG Home, and never turns the TV on.

H6, stability: leave it running for several hours of normal use; the log shows no growth beyond rotation, no unexpected pauses, memory and CPU stay negligible, and `status` is still connected.
