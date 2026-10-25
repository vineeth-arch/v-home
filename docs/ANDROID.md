# V/HOME watcher on an Android phone

## What it does

The app on your daily phone replaces the Mac watcher. While the phone is on your home Wi-Fi it keeps a connection to the LG TV, and when the TV's Home button brings up the LG launcher it launches V/HOME instead, the same as the Python companion does. A foreground-service notification ("Watching TV") shows while it runs, with a Pause/Resume button. The app stops by itself if the phone leaves the Wi-Fi it was using, and starts again when the phone rejoins home Wi-Fi.

Tested on the owner's Samsung SM-A556E (Android 14) and LG TV, 2026-10-21:
- **Home redirect:** 5 of 5 redirects from YouTube, Prime Video and Live TV, 2.3–6.7 s each. With the screen off, 2 of 2 worked in light Doze. Deep Doze could not be forced while the phone was on USB, so that case is untested.
- **Wi-Fi off and on:** after Wi-Fi turned off and on twice, watching restarted on its own within 4–14 s with the app closed.

What we learned on the real hardware:
- **Starting on Wi-Fi.** A network-callback PendingIntent is dropped on this Samsung as soon as the app leaves the screen. The durable trigger is therefore a persisted JobScheduler job that requires the Wi-Fi network (`WifiJob`). The watcher re-arms the job every time it stops because Wi-Fi went away. After "pairing lost" or a settings error it doesn't re-arm, because that would just loop. Opening the app, or tapping Pair, also starts watching directly.
- **Stuck V/HOME.** Sometimes the TV answers `launch` with success while V/HOME stays hidden in the background. The Mac watcher has the same problem. If V/HOME isn't in front 3 s after a successful launch, the phone closes it and launches it again, all inside the 10 s confirm window.
- **Logs.** Every step appears in the app's Event log. With a receiver running on the Mac (`python3 android/tools/logsink.py`, default port 8765, writing to `~/Library/Logs/vhome-watch-phone.log`), the phone pushes each event live, and **Send full log to Mac** adds the history and the app's own logcat. Leave the address field empty to turn this off.
- **Installing updates.** Installing an update by opening the APK on the phone has, at least once, replaced the app and wiped the pairing. `adb install -r` keeps it.

It is pinned to your TV: pairing records the TV's certificate fingerprint, and the app only talks to a device that presents the same certificate.

## Install

1. Build or receive `app-debug.apk` (from `android/`: `./gradlew assembleDebug`, output in `app/build/outputs/apk/debug/`).
2. Copy it to the phone and open it. Android will ask to allow installs from that source (your file manager or browser); allow it for this install.
3. Open the app, enter the TV's IP address, and tap Pair. Accept the prompt that appears on the TV. The app stores the TV's client key and certificate fingerprint.

## Always on (since 2026-10-22)

Once paired, the watcher runs all the time as a foreground service with a silent "V/HOME Watcher" notification. You never need to open the app.

**What the notification shows.** It reads Watching your TV, Waiting for home Wi-Fi, Not on home Wi-Fi, TV is off, or Paused until a set time. It has a **Pause 1 h** button (or **Resume**), and tapping it opens the app.

**Off home Wi-Fi it idles.** There are no sockets or timers. It resumes when the phone rejoins Wi-Fi; on the owner's phone that took 6 s.

**Recognising home Wi-Fi.** It recognises home by the router's address and subnet, which needs no location permission. On another network it tries once, then idles as "Not on home Wi-Fi". Before home has been seen once, any Wi-Fi counts as home.

**If Android kills it.** It is restarted within a few seconds (sticky restart; about 2 s on the owner's phone). A 15-minute watchdog job and the boot or app-update receiver start it again if needed.

**Timed pause.** The app offers 30 min, 1 h, 2 h, or until you resume. It ends by itself at the set time, even after a restart.

**Samsung.** One UI leaves apps set to battery *Unrestricted* out of the sleeping lists, so the app may not appear in "Never sleeping apps". That's expected. Instead:
- set the app's battery to Unrestricted;
- turn **Put unused apps to sleep** off (Battery, Background usage limits);
- choose **Keep open** on the app in Recents.

The app's Setup list checks what it can detect (battery unrestricted, background restriction, activity level) and links to the rest.

Tested on the phone, 2026-10-22:
- Wi-Fi off kept the service and notification ("Waiting for home Wi-Fi").
- Wi-Fi on went back to Watching in 6 s.
- `kill -9` was restarted in about 2 s.
- Pause 1 h blocked the Home redirect, and Resume restored it.
- The layout holds at font scale 1.3.

## Phone settings that matter

Set battery use for the app to Unrestricted (the app shows its current state and has a button to the right setting). On many phones the default "optimised" mode will eventually stop a background app. Allow notifications, because the foreground service needs its notification to be visible; on Android 13 and newer that is a runtime permission. Without these two the watcher can be stopped silently, and the app's own status line is then the only clue.

## TV settings

Turn on Quick Start+ (or the equivalent "fast boot" option on your model) so the TV keeps its network stack available while it is off. Without it the TV does not answer when you power it on until it has fully booted; the app retries the launch for about 8 seconds, which covers a normal wake but not a cold boot.

## Router: reserve the TV's address

Give the TV a DHCP reservation in the router so its IP stays the same. It is a recommendation, not a requirement.

If the IP changes anyway, the app notices that the saved address no longer answers with the paired certificate, searches the network for the TV (SSDP), checks each candidate's certificate against the saved fingerprint, and saves the new address when one matches. You can also edit the IP in the app.

## When you must pair again

Pairing has to be redone if the TV is factory reset, if its firmware changes its certificate, or if you remove the app's authorisation on the TV. The app then reports "Pairing lost" and stops instead of repeatedly showing the TV's pairing prompt; open the app and tap Pair. A certificate mismatch alone (some other device at the saved address) is never trusted; the app keeps looking for the real TV.

## Accepted limit

The phone is the watcher. When it is away from home Wi-Fi, switched off, or the app is stopped by the system, Home goes to the LG launcher as usual and nothing redirects it. That is the trade-off for using a phone you carry.

## Only one watcher at a time

Two watchers would both launch V/HOME on one Home press. That counts the Mac agent, this phone, and the Raspberry Pi node. Stop the Mac agent before using the phone:

```
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.designinnsaeit.vhome-companion.plist
```

If you use a VNode, the node is the watcher and this phone's own watcher stays off. The node's lock only stops a second program on the Pi. It cannot see the Mac or the phone. Switching the phone back to its own watcher asks the node to stop first (see below).

## VNode mode (0.9.0)

Version 0.9.0 adds a second mode. In VNode mode the phone is a remote for the Raspberry Pi node ([VNODE.md](VNODE.md)). It shows status, pauses and resumes, opens V/HOME on the TV, pairs the TV through the node, and controls the Pi.

What changes: there is no foreground service and no "V/HOME Watcher" notification, the boot receiver and the Wi-Fi job do nothing, and the battery exemption and Samsung sleeping-app settings above are not needed. Status is fetched every 5 seconds only while the screen is visible. Data older than 20 seconds is shown as "Last seen HH:MM", never as "Watching".

Pairing a node switches the phone to VNode mode and turns its own watcher off. "Use this phone instead" switches back, but only after the node confirms it stopped watching. If the node cannot be reached you must confirm it is unplugged or disconnected. "Forget this node" never turns the phone's own watcher back on by itself. Standalone remains the default for a phone that was never paired with a node.

## Behaviour worth knowing

- If the TV is in standby (power state Active Standby, Suspend, or Power Off), a Home event is not redirected. After the TV reports Active, earlier failures while it was booting are not counted.
- Three failed redirects within 60 seconds, or more than five redirects within 120 seconds, pause the app automatically (it is probably crashing or looping). Resume from the notification or the app.
- Reconnect delays start at 5 seconds, double up to 5 minutes, with some jitter.

## Appendix: Termux alternative (not used)

An earlier assessment (research date 2026-10-21, never run) considered running the Python companion in Termux on a spare phone. It would work only with F-Droid or GitHub Termux (the Play build is experimental), a pinned `websockets`, `termux-wake-lock`, battery optimisation disabled for Termux and Termux:Boot, and a boot script. Known fragile points: Doze if the phone is not on a charger, Android 12+ phantom-process killing, vendor background killers (see dontkillmyapp.com), Wi-Fi sleep, and Termux:Boot possibly not running until first unlock after a reboot. An iPad or iPhone cannot be an always-on watcher because iOS suspends background sockets. The proposed acceptance test was an overnight screen-off run with logs: heartbeats with no gap over 3 minutes, first morning Home redirected within 5 seconds, automatic reconnect within 60 seconds after TV standby, no unexplained restarts, and a reboot test. A native app was built instead because a foreground service, the Wi-Fi network callback and pinned TLS are first-class there. Sources: github.com/termux/termux-app, github.com/termux/termux-boot, developer.android.com/training/monitoring-device-state/doze-standby.
