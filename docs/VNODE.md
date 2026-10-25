# V/HOME VNode: the always-on Raspberry Pi

This is the owner guide. Status: written 2026-10-25. The code is tested on a desktop. Hardware results are filled in as they are measured; every row in the checklist at the end says "not run yet" until someone runs it.

## What it is

A small Raspberry Pi Zero W sits at home, always powered, and does the job the Mac watcher and the phone watcher did. It watches which app is in front on the LG TV. When LG Home comes up, it asks the TV to open V/HOME. Because the Pi never sleeps and never leaves the house, this works with the Mac asleep and with your phone away.

Your phone becomes a remote. It shows what the node sees, pauses and resumes it, opens V/HOME on the TV, and controls the Pi. The phone does not watch the TV itself in this mode.

V/TV Sleep stays the only sleep timer. The node has no timer. Everything local works without internet: the phone talks to the Pi over your home Wi-Fi, and nothing goes to any cloud. The only time the Pi needs internet is the install, when it downloads a few Debian packages.

## What you need

A Raspberry Pi Zero W with its own 5 V power supply (a phone charger and a good cable are fine; a weak supply causes under-voltage and LED shut-offs). The Pimoroni pHAT BEAT is optional. It adds the Wi-Fi signal LEDs. Without it, add `--no-leds` at install time.

A microSD card. Yours is 3.9 GB. That is enough for Raspberry Pi OS Lite plus the node, but tight: the baseline had 856 MB free before the install, and the installer wants at least 200 MB free. A 16 GB card is recommended (about ₹400) and removes the worry.

On the Mac: this repository, an SSH key (`~/.ssh/id_ed25519.pub`), and `adb` if you install the app from the Mac.

## The SD card: back it up first

If the card already holds anything you care about, back it up before you touch it. Never reflash without a backup. The simplest safe route is to use a separate, new card and keep the old one untouched.

To image an existing card on the Mac, put it in a reader and find its disk number.

```bash
diskutil list
```

Read the output carefully and pick the disk that matches your card's size. Writing to the wrong disk destroys your data. If you are not sure which disk it is, stop and ask. Then copy it (replace `N` with the number, for example `disk4`; the `r` before the name is intentional).

```bash
sudo dd if=/dev/rdiskN of=~/pi-backup.img bs=4m
```

This reads from the card and writes only to the file `~/pi-backup.img`. Do not swap `if=` and `of=`. A 3.9 GB card makes a file of about 3.9 GB, so check you have the space.

## Flash the card

1. Open Raspberry Pi Imager.
2. Device: Raspberry Pi Zero (this covers the Zero W).
3. Operating system: Raspberry Pi OS Lite (32-bit).
4. Choose your card.
5. In the settings, set: hostname `vnode`; username `vnode` with a password of your own; your 2.4 GHz Wi-Fi name and password (the Zero W cannot use 5 GHz); Wi-Fi country `IN`; enable SSH with public-key authentication only, and paste the contents of `~/.ssh/id_ed25519.pub`.
6. Write the card, put it in the Pi, and power it on. The first boot takes a few minutes.

## First boot and finding it

From the Mac, connect.

```bash
ssh vnode@vnode.local
```

Accept the host key when asked. If `vnode.local` does not resolve, open your router's list of connected devices, find `vnode`, and use its IP address instead. On the Pi, check the CPU type.

```bash
uname -m
```

It should print `armv6l`. Then leave the Pi with `exit`.

## Find the TV

You need the TV's IP address: TV settings, Network, or your router's device list. The TV must have LG Connect Apps turned on (in the network settings; the name can vary slightly by firmware). Turn on Quick Start+ if your model has it, so the TV answers while it is off. The TV in the earlier tests was at 192.168.29.225.

In the router, give both the TV and the Pi a DHCP reservation so their addresses stay the same. This makes things steadier, but it is not what keeps you safe. Trust comes from the pinned certificate fingerprint, never from an IP address or a name.

## Install from the Mac

From the repository root.

```bash
./vnode/deploy.sh --stop-mac-watcher install
```

What it does: it builds a bundle, copies it to `vnode@vnode.local`, and runs the installer there with `sudo`. The Pi asks for the `vnode` user's sudo password once, in your terminal. `--stop-mac-watcher` stops the Mac's V/HOME watcher (the LaunchAgent) first, because two watchers would both open V/HOME on one Home press. It does not delete any Mac files. To use another host or user, put `--host NAME` or `--user NAME` before the command. Options for the installer go after the word `install`: `--keep-wifi-powersave` leaves Wi-Fi power save as it is, and `--no-leds` skips the LED service.

If the health check fails at the end, the installer rolls back to the previous release by itself, prints the last log lines, and exits with an error.

What the installer changes on the Pi:

1. It checks it is a Pi, that Python is 3.11 or newer, that Debian is version 12 or newer, and that 200 MB are free.
2. It installs packages if missing: python3-aiohttp, python3-websockets, polkitd, avahi-daemon, openssl, and python3-libgpiod for the LEDs.
3. It creates a system user `vhome` with no login, and adds it to the `gpio` group for the LEDs.
4. It installs the program under `/opt/vhome-vnode` (the last two releases are kept) and creates the state folder `/var/lib/vhome-vnode`, readable only by `vhome`. This holds the node's certificate and private key, the TV's client key, and the paired phones. The certificate is created once and kept on later installs.
5. It installs two systemd services: `vhome-vnode` (the controller and API on port 8443) and `vhome-leds` (the LEDs). They do not depend on each other.
6. It adds a polkit rule that lets only the `vhome` user restart those two services and restart or power off the Pi. Nothing else.
7. It adds an Avahi record so phones can find the node on the Wi-Fi.
8. It makes the journal persistent with a 16 MB cap, so logs survive a restart without filling the card.
9. It turns off Wi-Fi power save, which on the Zero W delays replies. This takes effect at the next Wi-Fi reconnect or reboot. It does not restart the network, so your SSH session is safe.
10. It installs the `vnode` command in `/usr/local/bin`.

At the end it prints the node id and the version.

## Install the app and pair the phone

Install the app. With USB debugging on and the phone connected:

```bash
adb install -r android/V-HOME-Watcher-v0.9.apk
```

Use `-r` to update; it keeps the app's data. You can also copy the file to the phone and open it, but opening an APK has once wiped a pairing, so `adb` is safer.

In the app choose "Use the V/HOME node instead". Be on your home Wi-Fi. The app lists nodes it finds, or you can type `vnode.local` or the Pi's IP. Tap Connect. The app shows the node's fingerprint in six groups of four characters. On the Pi, run:

```bash
ssh -t vnode@vnode.local vnode pair-phone
```

It prints the same six groups and a pairing code. Compare the groups on the Pi with the groups on the phone. If they match, tap "They match", type the code, and tap Pair. If they do not match, stop: it may be another device. The code works once and lasts 5 minutes. Five wrong tries burn it, and you ask for a new one.

When pairing finishes, the phone switches itself to VNode mode and turns its own watcher off.

## Pair the TV through the Pi

The phone must be paired with the node first (previous step). Turn the TV on. In the V/HOME app, open the node screen and find "Pair the TV through the node". Enter the TV's IP address and tap Pair TV. Accept the prompt on the TV within 60 seconds. The Pi stores the TV's client key and the certificate fingerprint of the TV.

## Turn off the other watchers

Only one watcher should be active. With the node installed, that is the node.

The Mac watcher is stopped by `--stop-mac-watcher`. To do it by hand:

```bash
launchctl bootout gui/$(id -u)/com.designinnsaeit.vhome-companion
```

The phone turns its own watcher off when it pairs with the node. Why this matters: two watchers both react to one Home press and open V/HOME twice. The node has a lock, but it only stops a second program on the Pi itself. It cannot see your Mac or your phone, so you are the one who keeps those off.

## Everyday use

The app's node screen opens with a large status line. In words:

- Watching your TV: all good. Home on the TV opens V/HOME.
- TV in standby: the TV reported standby. The node keeps watching.
- Can't reach the TV: the node cannot talk to the TV. It may be off.
- TV not paired, TV certificate changed, TV said no, V/HOME not on the TV: see "When the TV needs attention" below.
- Paused by you / Paused for safety: see below.
- Last seen HH:MM: the phone has not heard from the node for 20 seconds or more, so what it shows may be out of date. It never says "Watching" for stale data.
- Can't reach the node, Not on Wi-Fi, Not your node, Not paired any more, Versions differ: see "Away from home" and the recovery guide.

Buttons: Pause 1 hour and Resume; Open V/HOME on TV (waits up to about 11 seconds and says whether V/HOME was seen in front, only accepted, or failed; if it says no answer, check the status before trying again). Three failed redirects in 60 seconds, or more than five redirects in 120 seconds, pause the node for safety. Find the cause, then Resume.

### The LEDs

The pHAT BEAT shows the Pi's Wi-Fi signal by lighting the first LEDs of its strip, from the left.

| LEDs lit | Signal (dBm) | Colour |
|---|---|---|
| 4 | -55 or stronger | green |
| 3 | -65 to -56 | green |
| 2 | -75 to -66 | amber |
| 1 | -85 to -76 | red |
| 0 | weaker than -85, or no reading | off |

The baseline Pi read about -67 to -69 dBm, which is 2 LEDs. The brightness is capped low on purpose (1 to 4, default 2). In the app, the LED switch and brightness buttons apply within about 10 seconds. The LEDs switch off by themselves at 70 °C or above, or when the Pi reports under-voltage, throttling or a temperature limit. They come back on their own once it is below 60 °C and nothing is flagged. The app shows "Off while the Pi is hot".

### Raspberry Pi controls

In the Raspberry Pi card the app shows temperature, memory, disk free, Wi-Fi signal, and a power-supply check. It has three actions. Restart V/HOME service restarts only the node program. Restart Pi reboots; the node is gone for about a minute and returns by itself. Shut down Pi powers it off; it comes back only when you unplug and replug its power, so use it only if you will be there. Restart and shut down ask for confirmation, and only one such action is allowed per minute.

## When the node is unreachable, and going back to standalone

If you are away from home, on a guest Wi-Fi that keeps devices apart, or on a VPN, the phone cannot reach the node. The app says so and does not guess. See "Away from home" below.

To make the phone watch the TV itself again, tap "Use this phone instead". The app first asks the node to stop watching and waits for it to confirm. If the node cannot be reached, the app asks you to confirm that it is unplugged or disconnected. Do this only if that is true. The reason is simple: if both watch, Home opens V/HOME twice. Nothing switches by itself, ever. "Forget this node" only makes the phone stop talking to the node; it does not turn the phone's own watcher back on.

## Away from home, guest Wi-Fi and VPN

The node is reachable only from your home Wi-Fi. Away from home the app shows Not on Wi-Fi or Can't reach the node. That is expected: the node still works for the TV; you just cannot control it. Guest Wi-Fi often isolates devices from each other, and a VPN sends traffic elsewhere, so the app names those as likely causes. If automatic discovery does not find the node, type its name or IP by hand.

## Diagnostics

From the Mac, a summary of the services and releases:

```bash
./vnode/deploy.sh status
```

A fuller report (model, OS, memory, disk, node process size and CPU, throttling, journal size, last log lines):

```bash
./vnode/deploy.sh diag
```

On the Pi (after `ssh vnode@vnode.local`). The `vnode` command may ask for the sudo password.

```bash
vnode status
```

```bash
vnode diag
```

```bash
journalctl -u vhome-vnode -n 100 --no-pager
```

```bash
systemctl status vhome-vnode vhome-leds
```

`vnode pause`, `vnode pause --minutes 60`, `vnode resume` and `vnode leds on|off [--brightness 1-4]` also work on the Pi. The app has the same diagnostics, with a Copy button.

## Updates, rollback, uninstall

To update after pulling new code, run it again (`update` and `install` do the same thing and keep the certificate and pairings).

```bash
./vnode/deploy.sh update
```

If the new version fails its health check it rolls back automatically. To go back by hand to the previous release:

```bash
./vnode/deploy.sh rollback
```

To remove the node but keep its certificate, TV key, and phone list (so a reinstall needs no re-pairing):

```bash
./vnode/deploy.sh uninstall
```

To remove everything it created, including those secrets and the `vhome` user:

```bash
./vnode/deploy.sh uninstall --purge
```

Packages stay installed. After a plain uninstall the journal setting and Wi-Fi power save return to their defaults on the next restart or reconnect.

## Backup and restore

The backup holds the node's private key, the TV client key, and the phone token hashes. Keep it private, like a password. Do not email it or put it in a shared folder.

```bash
./vnode/deploy.sh backup
```

This copies the archive to `vnode-backups/vnode-backup-DATE-TIME.tar.gz` in the repo on the Mac (that folder is git-ignored) and deletes the copy on the Pi. It holds credentials: the TV key, the node's private key and the phone token hashes. Keep it private.

To restore, for example onto a fresh card after `./vnode/deploy.sh install`, pass the file from the Mac:

```bash
./vnode/deploy.sh restore vnode-backups/vnode-backup-DATE-TIME.tar.gz
```

The restore refuses an unsafe archive, backs up the current state first, replaces the state (it does not merge), restarts the services and runs the health check. Restoring the backup keeps the same node id, so paired phones keep working.

## Revoking a phone

In the app, in the phones list, tap Revoke next to the phone. Or on the Pi:

```bash
vnode phones list
```

```bash
vnode phones revoke ID
```

A revoked phone gets "Not paired any more" on its next call and must pair again.

## When the TV needs attention

The TV state shown by the app is one of these.

launcher_missing ("V/HOME not on the TV"): the TV has no V/HOME installed, usually because the Developer Mode session ran out or the TV was reset. Reinstall V/HOME from the Mac, never from the Pi. The Mac is where app builds happen.

```bash
./scripts/refresh-tv.sh
```

For the Developer Mode session (renewing it before it expires) see [DEV-MODE.md](DEV-MODE.md).

certificate_mismatch ("TV certificate changed"): the thing at the saved address does not present the certificate that was pinned. The node does not trust it and retries slowly (about every 5 minutes) so the TV is not prompted again and again. If the TV was really reset or its firmware changed, pair again with "TV was reset (re-pin)" ticked. Re-pin only after a real TV reset. If you did not reset the TV, find out what else is at that address first.

pairing_required ("TV not paired"): the node has no valid TV key. Use "Pair the TV through the node" and accept the prompt on the TV within 60 seconds.

permission_denied ("TV said no"): pair the TV again and accept the prompt.

## Future add-ons

Two other services (personal-brain-os, handshake-os) may one day run on the same Pi. Nothing is built for them. The rule when they come: each one is its own systemd unit with no `Requires=` or `BindsTo=` on `vhome-vnode`, and each can be restarted on its own. `vhome-leds` already follows this rule.

## Hardware checklist

Results are blank on purpose. The orchestrator or the owner fills them in after running each test on the real Pi and TV.

| Test | How to run it | Expected | Result |
|---|---|---|---|
| Mac asleep, phone away | Put the Mac to sleep, take the phone off Wi-Fi, press Home on the TV from three apps | V/HOME opens each time | not run yet |
| Internet down, LAN up | Unplug the router's internet cable, keep Wi-Fi on, press Home; use the app on Wi-Fi | Still works, no cloud needed | not run yet |
| Router restart | Restart the router, wait for Wi-Fi | Node reconnects by itself, Home works again, no TV prompt | not run yet |
| Pi restart | Use Restart Pi in the app, or unplug and replug | Back in about 3 minutes, Watching, no re-pairing | Passed 2026-10-25 (power cut): API back at 165 s, TV reconnected, no prompts |
| TV standby | Put the TV in standby, wake it, press Home | Redirect works after wake. This TV does not report its power state, so standby itself is not detected | not run yet |
| TV cold boot | Switch the TV off at the wall, on again, press Home | Node reconnects, redirect works | not run yet |
| 20 Home presses | 5 each from Netflix, YouTube, Prime Video, an HDMI input; record latency from `journalctl` | At least 19 of 20 redirected, none while inside an app or input | not run yet |
| No takeover after a Wi-Fi blip | Turn the Pi's Wi-Fi off and on (or move the router) while watching | After reconnect it only acts if LG Home is in front | not run yet |
| Pause and resume | Pause 1 hour in the app, press Home, then Resume | No redirect while paused, redirect after Resume | not run yet |
| Phone revocation | Revoke a phone, use it | Not paired any more; other phone unaffected | not run yet |
| Multi-day run | Leave it running 3 days; check `vnode diag` | No restarts, no throttling, memory steady | not run yet |
| Backup restore | Back up, wipe or use a spare card, install, restore | Same node id, phones still paired | not run yet |
| LED heat test | On the Pi: `sudo bash /opt/vhome-vnode/current/vnode/heat-test.sh 30 30 ~/heat.csv` | CSV shows temperature with LEDs off then on; stays below 60 C | Passed 2026-10-25: 43.5 C off vs 43.3 C on, no throttling |

## Measured resource use

To be filled from `./vnode/deploy.sh diag` on the real Pi. The baseline before install was 102 of 426 MB memory used, 2100 of 3121 MB disk used, 42.7 to 43.8 C, load 0.01 to 0.08.

| Measure | Value |
|---|---|
| Node process memory (RSS) | 44.7 MB with the TV connected (29.7 MB before pairing); LED service 11.7 MB |
| CPU, idle | 0.60 % node + 0.17 % LEDs, 5-minute average with the TV connected |
| Disk used after install | 432 KB release + 3.8 MB packages; 848 MB still free |
| Temperature, idle, LEDs off | 43.5 C mean over 30 min (TV connected) |
| Temperature, idle, LEDs on | 43.3 C mean over 30 min: no measurable difference |
