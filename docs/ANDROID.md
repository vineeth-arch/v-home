# Running the V/HOME companion on an old Android phone (Termux)

Status: assessment only. Nothing here has been run. No reliability claim is made; the overnight test at the end is how it gets earned. Research date 2026-10-21.

## Why consider it

The companion (Python 3.11-ish, `websockets` only) needs a device that is on all the time, on the same Wi-Fi as the TV. A Mac that sleeps does not redirect Home while asleep (the vibehack README says the same). A spare Android phone on a charger is the cheapest always-on option, and Termux can run Python. The honest summary: it can work, it is fragile because Android is built to stop background apps, and every fragile point below must be passed by the test before it is trusted.

## Setup outline

1. Install **Termux from F-Droid** (or the GitHub build), not Google Play. The Termux README says the Play Store build is experimental, with missing functionality and bugs, and recommends F-Droid or GitHub. Install Termux and every add-on from the same source; mixing sources fails because the APKs are signed with different keys (README, Installation). The README says full support is for Android 7 and newer; Android 5 and 6 get the app only, with no package updates.
2. In Termux: `pkg update`, `pkg install python`, then create a venv and `pip install` a **pinned** `websockets` version (pin the version the Mac companion is tested with, so the two do not drift). Python on Termux is a Termux build, not the Mac's. Test the same companion file on both.
3. Copy the companion and its key file. The TV pairing key is tied to the manifest, not the device, so the phone can reuse the Mac's key file, but pair separately if a second prompt is acceptable; that avoids copying a secret around. Keep the key file readable only by Termux.
4. Run `termux-wake-lock`. In Termux's source (`TermuxService.java`, `actionAcquireWakeLock`) this acquires a partial CPU wake lock and a Wi-Fi lock (`WIFI_MODE_FULL_HIGH_PERF`), and prompts for battery-optimisation exemption if not already granted. It is also available as the notification action "Acquire wakelock".
5. Disable battery optimisation for Termux (and Termux:Boot) in Android settings (Settings > Battery > Battery optimisation, or the vendor's equivalent). The Termux README itself tells F-Droid users to do this and points to dontkillmyapp.com.
6. Install **Termux:Boot** (F-Droid), open it once so it is allowed to run at boot, then put a script in `~/.termux/boot/`. The Termux:Boot README example starts with `termux-wake-lock`. The script should start the companion in a loop with logging.
7. Keep the phone on a charger, fully charged, with the screen off. Give it a static DHCP lease or a reservation, and note the TV's IP (also reserved).

## What is known to break

Facts first, with their sources; then the risk for us.

- **Doze.** Android docs: after the device is unplugged, stationary, and screen-off for a while, network access is suspended, wake locks are ignored, standard alarms are deferred, and Wi-Fi scans stop; the system opens periodic maintenance windows that get less frequent over time. Plugging in or moving the device exits Doze. Apps on the battery-optimisation allowlist can use the network and hold partial wake locks during Doze and App Standby (same page). Risk: a phone on a charger is not subject to the unplugged condition, which helps, but a phone that is unplugged will have its socket starved. **Keep it plugged in.** If the charger is a smart plug or the phone is cycled off the charger, Doze applies.
- **App Standby.** Idle apps get background network deferred; apps with a foreground service are not treated as idle (same page). Termux runs a foreground service with a notification while a session or wake lock is held, which is the main thing keeping it alive.
- **Android 12+ phantom process killer.** Termux README warns that Android may kill processes beyond a 32 (all apps combined) limit and processes with excessive CPU use; the symptom is `[Process completed (signal 9)]` while the shell appears alive. The README links the issue and the disabling instructions. For a single small Python process the count should stay low, but a long-running `sshd`, extra shells, and background jobs add up. Mitigation is a documented developer-option/adb setting; follow the linked Termux issue, and record the Android version.
- **Vendor killers.** dontkillmyapp.com rates some vendors (Huawei, Xiaomi, Samsung, OnePlus and others) as aggressive about killing background apps, with per-vendor instructions. An old phone is often one of those. Extra steps (auto-start permission, "lock in recents", power-saving whitelists) vary by vendor and are not in Termux's docs.
- **Wi-Fi sleep.** The wake lock above includes a high-performance Wi-Fi lock, which stops the radio from power-saving while held. Some phones still drop Wi-Fi when the screen is off or after a captive-portal check; whether this phone does is only learnable by test. Check Settings for any "keep Wi-Fi on during sleep" or "Wi-Fi power saving" toggle (names vary and some versions removed the old option). I could not verify the current Android setting names.
- **Reboots.** Termux:Boot runs scripts at boot, but only after the first unlock on some versions/devices (Android's direct-boot rules); a phone that reboots at night and waits at a lock screen may not start the script until someone unlocks it. This is plausible, not verified here; the test below should include one deliberate reboot. After a reboot there is no wake lock until the boot script takes it.
- **Updates.** Android and Termux updates change behaviour. Pin Termux's F-Droid build and turn off automatic app updates for it during the test; the Termux README notes F-Droid updates arrive days after GitHub ones.
- **TV side.** The watcher still has to survive the TV's own power states, pairing key loss, and the 3001 vs 3000 behaviour covered in OPEN-SOURCE-INTEGRATION-MATRIX.md section 5. A phone that stays connected perfectly cannot fix those.

## iPad / iPhone

Use as a control screen only (the V/HOME phone companion), not as the always-on watcher. iOS suspends apps that are not in the foreground; Apple's Background Tasks framework (`BGTaskScheduler`) lets the system run short refresh or processing tasks at times it chooses, not on a schedule the app controls, so a persistent websocket to the TV cannot be kept alive reliably. I could not retrieve the text of Apple's documentation page at https://developer.apple.com/documentation/backgroundtasks; the summary above is from general knowledge of that API and should be checked against the page before anyone relies on the wording. The conclusion that an iPad cannot be the watcher does not depend on fine detail.

## Overnight screen-off test protocol

Goal: find out whether the phone watcher is as reliable as the Mac watcher, using evidence and not impressions. Do the Mac-only run first as a baseline if the Mac companion exists.

Setup (record all of it):
- Phone model, Android version, Termux version and source, Termux:Boot version, Python and `websockets` versions, battery-optimisation state for Termux and Termux:Boot, vendor power-saving settings.
- TV model, firmware, whether Quick Start+/standby options are on, TV and phone IPs.
- The companion must log one line per event with a monotonic and wall-clock timestamp: connect, disconnect (with reason), each foreground app change, each redirect with result, each reconnect attempt, and a heartbeat line every 60 s. Log to a file in Termux's home. Also log the TV power state when it changes.
- A second observer: the Mac companion stopped for the night (to avoid double redirects), but a quick script on the Mac that connects once per 10 minutes and logs whether the TV is reachable and the foreground app. This separates "TV unreachable" from "phone dead".

Procedure:
1. Phone on charger, screen off, charged to 100%, Wi-Fi on, mobile data off (to avoid failover hiding Wi-Fi problems). Start the watcher from the boot script path (reboot the phone first, unlock once if needed, and record whether the script started on its own).
2. Evening: with the phone watcher running, press Home on the TV 3 times at 5-minute spacing and confirm V/HOME returns each time. Note latency by stopwatch or video.
3. Put the TV to standby (remote power) and leave it 20 minutes; power it on with the remote; note whether the watcher reconnects and redirects without intervention, and how long it takes.
4. Leave the TV on V/HOME with the screen on for 30 minutes, then power off, then leave the whole system alone overnight (8 hours minimum). The phone screen stays off; do not touch it.
5. Morning, before touching the phone: read the log. Then power on the TV, press Home once, and record result and latency. Then deliberately reboot the phone, do not unlock it, wait 5 minutes, and record whether the watcher started (this is a separate result).

Pass criteria (all must hold; adjust thresholds only before the run, not after):
- Watcher process alive in the morning with a heartbeat within the last 2 minutes, and no gap between heartbeats larger than 3 minutes during the night (excluding the TV being off, which is logged separately).
- After the TV powers on in the morning, the first Home press is redirected within 5 seconds of the press, with no manual action on the phone.
- Evening Home presses: 3 of 3 redirected, each within 3 seconds of LG Home appearing (this is a bench figure; vibehack claims about 0.1-0.5 s, unverified).
- After TV standby for 20 minutes and power on, the watcher reconnects on its own within 60 seconds.
- Zero unexplained watcher restarts (a restart is a fail unless the log shows a TV power cycle caused it).
- Wi-Fi: no Wi-Fi disassociation on the phone logged overnight (check Android's Wi-Fi log if reachable, or the Mac observer's ping/ARP record for the phone's IP).
- Boot test: after a phone reboot with no unlock, the watcher starts without user action within 5 minutes. If it only starts after an unlock, record "needs unlock" and treat boot-resilience as failed for unattended power-outage recovery.

Fail handling: any single fail is a fail of that item. Fix one thing (for example the vendor power setting), then repeat the whole night, not just the failed step. Three consecutive clean nights are a reasonable bar before treating it as dependable. Keep the logs with the settings snapshot so a regression after an Android update is detectable.

## Sources

- Termux app README (installation sources, F-Droid vs Play, Android 12+ phantom process warning, battery optimisation advice): https://github.com/termux/termux-app
- Termux source, wake locks: `app/src/main/java/com/termux/app/TermuxService.java`, same repository.
- Termux:Boot README (boot scripts directory, open the app once, `termux-wake-lock`): https://github.com/termux/termux-boot
- Android Doze and App Standby: https://developer.android.com/training/monitoring-device-state/doze-standby
- Vendor background killing: https://dontkillmyapp.com/
- Apple Background Tasks (not retrievable in this session; verify before relying): https://developer.apple.com/documentation/backgroundtasks
- Watcher behaviour and reconnect design: docs/OPEN-SOURCE-INTEGRATION-MATRIX.md (sections 3.14 and 5.C, 5.F).
