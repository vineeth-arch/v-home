# Developer Mode: expiry, extending, reinstalling V/HOME

V/HOME is a developer-mode app, like V/TV Sleep. The TV keeps such apps only while its Developer Mode session has time left. Verified on LG 43NU885BPLA, firmware 43.04.26, webOS SDK 11.0.1. The details match `LGTV/docs/dev-mode.md`.

## Check the time left
Open the **Developer Mode** app on the TV. It shows the Login Session (for example `999h:59m` right after an extend), the IP address and the passphrase.

## Extend
In the Developer Mode app press **Extend** well before 0 h. There is no Mac-side command for this with `@webos-tools/cli` 3.2.6.

## What happens at 0 h
The TV removes developer-mode apps: V/HOME, V/TV Sleep and its service. Your household data is safe in the cloud. The Mac and phones are unaffected.

## Reinstall after expiry
1. On the TV turn Developer Mode back on. Note the IP and whether Key Server is on.
2. On the Mac, from the `v-home` folder:
   ```
   ./scripts/build-tv.sh      # only if there is no build/*.ipk
   ./scripts/install-tv.sh
   ```
   If the IP or key changed, run LGTV's `scripts/connect-tv.sh <TV_IP>` first (it asks for the passphrase shown on the TV).
3. Reinstall V/TV Sleep too if it was removed (see `LGTV/docs/dev-mode.md`).
4. Pair again from the phone (Displays). A reinstall after expiry may have cleared the TV's stored session.

## Upgrading in place (the normal case)
`./scripts/install-tv.sh` upgrades V/HOME without removing it. On 2026-09-29 an in-place upgrade **kept** the TV's pairing (no new anonymous session was created in the cloud). Never use `ares-install --remove` for an upgrade: that would clear the TV's stored session.
