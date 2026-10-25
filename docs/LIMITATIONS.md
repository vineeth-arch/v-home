# Known limitations

- **Home button and power-on:** V/HOME cannot replace the Home button or open automatically at power-on. See `docs/OPENING.md` for the supported setup.
- **Sleep timer:** V/TV Sleep is the only timer authority. The TV refuses a direct call from V/HOME to the V/TV Sleep service (checked: `denied method ... for category "/"`), so V/HOME opens V/TV Sleep with the request (needs V/TV Sleep 0.1.1+). V/TV Sleep sets the timer, flashes its own confirmation for about a second, then reopens V/HOME with the confirmed result. The status line only shows what V/TV Sleep confirmed, and can be stale if the timer is changed elsewhere. Not yet checked: that the TV actually switches off at the set time.
- **No overlay above other apps.** Quick controls exist inside V/HOME only.
- **Volume, sound output and picture presets** are not offered until verified on this TV.
- **A revoked TV** keeps showing its cached content until it reconnects to the internet.
- **Free cloud tier:** Supabase pauses after about 7 days without use; Vercel Hobby is for personal use.
- **Streaming availability** comes from TMDB/JustWatch and can be out of date. V/HOME opens the streaming app, not the specific title.
- **No external calendars** in V1: plans are entered by hand.
- **Developer Mode:** the app disappears if the TV's session expires (`docs/DEV-MODE.md`).
- **Photo exports** (when photos are added) can be large.
- **Sample data:** `SIMULATION` appears whenever the TV app runs without the cloud (desktop preview only).
- The photo frame (Ambient) never fakes input, so LG's "Auto Power Off after 4 hours without input" still switches the TV off while it is showing. That is intended.
- Keeping LG's own screensaver off during the photo frame is best effort (the TV may refuse it); if refused, LG's screensaver covers the frame after a few minutes.
- **VNode and the Home button:** the Pi redirects LG Home to V/HOME after it appears; it does not replace the Home button, and LG Home still flashes for a moment. The redirect needs the TV on and the Pi on the same network.
- **VNode power-on launch is off.** Opening V/HOME at TV power-on is disabled and unverified (`power_on_launch`). Nothing promises it.
- **One watcher is on you.** The node's lock only stops a second program on the Pi. It cannot stop the Mac agent or a phone in standalone mode. Keep them off.
- **No timer from the node.** V/TV Sleep stays the only timer authority (`timer: unavailable`). The node does not sync the app catalog either; that stays on the Mac.
- **Finding the node can fail.** The phone finds the node with network discovery (NSD). Behind a VPN, or on a guest Wi-Fi that isolates devices, it may not, and then you type the host name or IP by hand. The app never trusts an address alone; it checks the pinned certificate.
- **Installs need the Pi's sudo password**, typed once in your terminal.
- **A 3.9 GB card is tight.** It leaves little room (856 MB free before install). A 16 GB card is recommended. The installer refuses to run with less than 200 MB free, and the journal is capped at 16 MB.
- **LEDs are limited on purpose.** Brightness is capped at 4 of 31, colours are dim green, amber and red, and they switch off by themselves at 70 C or on under-voltage until the Pi is below 60 C.
- **After a Pi shutdown from the app** it only comes back when its power is unplugged and replugged.
- **Timed pause and the clock:** The Pi has no clock of its own. If it restarts during a timed pause and can't reach a time server, it stays paused (the safe side) and resumes by itself once its clock is synced; without internet that can take until you resume it by hand.

