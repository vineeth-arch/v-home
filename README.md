# V/HOME

An ad-free launcher and shared household dashboard for an LG webOS TV, with a phone companion and an optional Mac helper that makes the Home button return to V/HOME.

**Start here:** [docs/HELP.md](docs/HELP.md) is the complete user guide with every feature. Design authority: `.claude/docs/design-system.md`. Original plan: `docs/PLAN.md`.

![V/HOME launcher, desktop preview](docs/screenshots/after-launcher-curated.png)

*Desktop preview of the launcher. Before 2.0: [before-home.png](docs/screenshots/before-home.png).*

## What it does

- **Launcher:** colour-matched app tiles, up to 9 favorites in a 3x3 grid with a photo card, which you can reorder, folders you name with an on-screen keyboard, hold OK on an app to edit it, a full scrolling app list, HDMI inputs at the bottom, five wallpapers, a built-in Help screen. Opens without pairing, internet or the Mac helper. App list and icons come from your own TV.
- **One-click sleep timer** (15, 30, 45, 60, 90 min, Cancel) on the right of the Home screen. V/TV Sleep stays the only thing that turns the TV off; it confirms each request and returns you to V/HOME, and Check timer asks it for the true state.
- **Home button:** a Mac helper watches the foreground app and reopens V/HOME when LG Home appears. Pause and resume any time, with automatic safety limits.
- **Household:** Our Home (morning and evening rituals, reflections, plans, notes), Watch Together, Us, Idea Wall, photo frame, guest view, weather, and Studio business numbers in work hours.
- **Phone app:** plans, tasks, dreams, notes, photos, ideas, weekly check-in, reflections, watch list with TMDB search, pairing, backup.
- **Privacy:** no ads, no telemetry, no recommendations. Household data is in your own Supabase project; the launcher layout stays on the TV.

## Install

Needs the TV in Developer Mode with the `tv` device saved (`node_modules/.bin/ares-setup-device --list`). From this folder:

```bash
npm install
./scripts/build-tv.sh && ./scripts/install-tv.sh
```

For the Home button and real app icons, set up the Mac helper: [docs/COMPANION.md](docs/COMPANION.md). The sleep timer needs V/TV Sleep 0.1.2 or newer from the [LGTV repo](https://github.com/vineeth-arch/lgtv) installed on the same TV.

Refresh the app list after installing or removing TV apps (icons and tile colours come from your own TV):

```bash
./scripts/refresh-tv.sh
```

The Mac helper also notices app changes by itself and can run this for you (`python -m vhome_companion autorefresh on`).

## Develop

| Command | What |
|---|---|
| `npm run dev` | phone app |
| `npm run dev:tv` | TV app in the browser (add `?sim` for sample data) |
| `npm run check` | typecheck, tests, both builds |
| `python3 -m unittest discover companion/tests` | Mac helper tests |
| `./scripts/refresh-tv.sh` | export TV apps and icons, rebuild, install |

Stack: React 19, Vite, TypeScript, plain CSS (the brief overrides the global Next.js default). The TV build is a single script that works from `file://`. Mac helper: Python 3.11+, one dependency (`websockets`).

## Docs

- [Help and all features](docs/HELP.md)
- [VNode: always-on Raspberry Pi](docs/VNODE.md): install, pair, LEDs, backup, recovery, hardware checklist
- [Mac companion](docs/COMPANION.md): setup, Home-button return, pause, uninstall, test checklists
- [Capabilities](docs/CAPABILITIES.md): what is verified on the TV and what is not
- [Opening V/HOME by default](docs/OPENING.md) · [Recovery](docs/RECOVERY.md) · [Developer Mode](docs/DEV-MODE.md) · [Limitations](docs/LIMITATIONS.md)
- [Studio setup](docs/STUDIO.md)
- [2.0 audit](docs/AUDIT-2.0.md) · [Open-source matrix](docs/OPEN-SOURCE-INTEGRATION-MATRIX.md) · [Android helper assessment](docs/ANDROID.md) · [Notices](NOTICE.md) · [Catalog contract](docs/contracts/catalog-v1.md)

## Status

Working on the real TV (LG 43NU885BPLA): install, pairing with the Mac helper, Home button return (11 of 11 in manual tests), real app list with icons, the launcher, and the one-click timer (set and cancel). Not yet checked on the TV: the full 20-trial Home test, Wi-Fi off, Mac sleep and wake, multi-hour stability, the TV actually switching off at the timer time, the photo frame, Studio, live weather. Details and test steps: [docs/CAPABILITIES.md](docs/CAPABILITIES.md) and [docs/COMPANION.md](docs/COMPANION.md).
