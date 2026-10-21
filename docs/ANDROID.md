# V/HOME watcher on an Android phone

## What it does

The app on your daily phone replaces the Mac watcher. While the phone is on your home Wi-Fi it keeps a connection to the LG TV, and when the TV's Home button brings up the LG launcher it launches V/HOME instead, the same as the Python companion does. A foreground-service notification ("Watching TV") shows while it runs, with a Pause/Resume button. The app stops by itself if the phone leaves the Wi-Fi it was using, and starts again when the phone rejoins home Wi-Fi.

It is pinned to your TV: pairing records the TV's certificate fingerprint, and the app only talks to a device that presents the same certificate.

## Install

1. Build or receive `app-debug.apk` (from `android/`: `./gradlew assembleDebug`, output in `app/build/outputs/apk/debug/`).
2. Copy it to the phone and open it. Android will ask to allow installs from that source (your file manager or browser); allow it for this install.
3. Open the app, enter the TV's IP address, and tap Pair. Accept the prompt that appears on the TV. The app stores the TV's client key and certificate fingerprint.

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

Two watchers would both launch V/HOME on one Home press. Stop the Mac agent before using the phone:

```
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.designinnsaeit.vhome-companion.plist
```

## Behaviour worth knowing

- If the TV is in standby (power state Active Standby, Suspend, or Power Off), a Home event is not redirected. After the TV reports Active, earlier failures while it was booting are not counted.
- Three failed redirects within 60 seconds, or more than five redirects within 120 seconds, pause the app automatically (it is probably crashing or looping). Resume from the notification or the app.
- Reconnect delays start at 5 seconds, double up to 5 minutes, with some jitter.

## Appendix: Termux alternative (not used)

An earlier assessment (research date 2026-10-21, never run) considered running the Python companion in Termux on a spare phone. It would work only with F-Droid or GitHub Termux (the Play build is experimental), a pinned `websockets`, `termux-wake-lock`, battery optimisation disabled for Termux and Termux:Boot, and a boot script. Known fragile points: Doze if the phone is not on a charger, Android 12+ phantom-process killing, vendor background killers (see dontkillmyapp.com), Wi-Fi sleep, and Termux:Boot possibly not running until first unlock after a reboot. An iPad or iPhone cannot be an always-on watcher because iOS suspends background sockets. The proposed acceptance test was an overnight screen-off run with logs: heartbeats with no gap over 3 minutes, first morning Home redirected within 5 seconds, automatic reconnect within 60 seconds after TV standby, no unexplained restarts, and a reboot test. A native app was built instead because a foreground service, the Wi-Fi network callback and pinned TLS are first-class there. Sources: github.com/termux/termux-app, github.com/termux/termux-boot, developer.android.com/training/monitoring-device-state/doze-standby.
