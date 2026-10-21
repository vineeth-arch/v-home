# V/HOME design system (highest design authority; overrides any design skill)

- Mood: warm, calm, personal. Warm charcoal background, warm white text, restrained amber and sage accents. Evening darkens the app palette only; never touch TV picture settings.
- No gradients, no generic animated backgrounds, no autoplay audio. Personal images carry the character.
- TV canvas 1920x1080, 96px safe margin. H1 56-72px, body 30-36px. Tokens live in `src/styles/tokens.css`.
- Focus: visible border AND scale/shape change, never colour alone. Every action reachable with arrows, OK, Back. Pointer and keyboard focus stay synced.
- Motion: subtle, 150-250ms, `prefers-reduced-motion` disables it. Focus moves use `--dur-focus` (120ms, never staggered); Our Home cells cascade in on screen entry only (`--dur`, 3 steps max). Easing `--ease-out`.
- Depth (no gradients): cells use `box-shadow: var(--hairline), var(--shadow-1)`; focused elements lift with `--shadow-3`. Radius `--radius-cell` (28px) for bento cells, `--radius-inner` (16px) for tiles inside. Overlays use `--scrim` (hero text) and `--veil` (full-screen). Text on amber/sage uses `--on-accent`.
- Placeholder dream art (`DreamArt`) is solid layered shapes filled from tokens (`.da-*` classes), so evening mode recolours it too.
- Our Home fits one screen, no vertical scroll. Max 3 events, 1 shared note, 6 launch tiles.
- Copy: manifestation is personal intention and visualisation, never guaranteed outcomes. Reflections are labelled "Original reflection", no invented authors.
- No scoring, streaks, rankings, or completion pressure.
- Fonts self-hosted in public/fonts (no CDN): Newsreader (serif, headings/quotes) and Atkinson Hyperlegible (body). @font-face lives inline in each HTML file with document-relative URLs (works for the phone and for file:// in the IPK). Phone UI is mobile-first at 390px.

## Launcher (Home screen only; user decision 2026-10-21)
- The launcher screen (`.launcher`, tokens in `src/tv/launcher.css`) may use a dark neutral palette and a subtle, static gradient wallpaper (preset list). This overrides "warm charcoal" and "no gradients" for that screen only. Household screens (Our Home, Watch, Us, Ideas, rituals) keep the warm tokens above.
- No animated wallpaper, no backdrop blur, no particle effects, no network images required. Six-column grid, six dock slots, focus scale ~1.05 + outline + shadow, 150–200 ms transform/opacity; reduced-motion respected.
