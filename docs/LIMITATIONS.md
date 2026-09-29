# Known limitations

- **Home button and power-on:** V/HOME cannot replace the Home button or open automatically at power-on. See `docs/OPENING.md` for the supported setup.
- **Sleep timer:** V/TV Sleep is the only timer authority. V/HOME reaches it either directly (not yet verified) or by opening V/TV Sleep, which takes the foreground; press Back to return. A handoff never shows a countdown.
- **No overlay above other apps.** Quick controls exist inside V/HOME only.
- **Volume, sound output and picture presets** are not offered until verified on this TV.
- **A revoked TV** keeps showing its cached content until it reconnects to the internet.
- **Free cloud tier:** Supabase pauses after about 7 days without use; Vercel Hobby is for personal use.
- **Streaming availability** comes from TMDB/JustWatch and can be out of date. V/HOME opens the streaming app, not the specific title.
- **No external calendars** in V1: plans are entered by hand.
- **Developer Mode:** the app disappears if the TV's session expires (`docs/DEV-MODE.md`).
- **Photo exports** (when photos are added) can be large.
- **Sample data:** `SIMULATION` appears whenever the TV app runs without the cloud (desktop preview only).
