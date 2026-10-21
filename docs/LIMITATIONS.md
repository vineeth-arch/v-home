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
