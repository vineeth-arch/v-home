# V/HOME
Ad-free launcher + shared household dashboard for an LG TV, with a phone companion and an optional Mac helper that returns Home to V/HOME. Plan: `docs/PLAN.md`. Design authority: `.claude/docs/design-system.md`.
Stack note: brief mandates React+Vite+plain CSS, overriding the global Next.js/Tailwind default.
Commands: `npm run dev` (phone), `npm run dev:tv`, `npm run check`.

## Docs
- [Capabilities (what is verified on the TV)](docs/CAPABILITIES.md)
- [Opening V/HOME by default](docs/OPENING.md)
- [Recovery](docs/RECOVERY.md) · [Developer Mode](docs/DEV-MODE.md) · [Limitations](docs/LIMITATIONS.md)
- Install on the TV: `./scripts/build-tv.sh && ./scripts/install-tv.sh`
- [Studio setup](docs/STUDIO.md): Design Innsaeit numbers on the TV during work hours.
- [Mac companion](docs/COMPANION.md): Home-button return, pairing, catalog refresh (`python -m vhome_companion sync-catalog && ./scripts/build-tv.sh && ./scripts/install-tv.sh`).
- [2.0 audit](docs/AUDIT-2.0.md) · [Open-source matrix](docs/OPEN-SOURCE-INTEGRATION-MATRIX.md) · [Android helper assessment](docs/ANDROID.md) · [Notices](NOTICE.md) · [Catalog contract](docs/contracts/catalog-v1.md)

## 2.0 behaviour
- Opens on the launcher (Home): favorites dock, app grid, inputs, clock, weather, one personal card. Works without pairing, internet or the Mac helper; household screens show the pairing card until paired.
- Nav: Home · Our Home · Watch Together · Settings (+ Studio in work hours; it never opens by itself). Us and Idea Wall live on Our Home.
- Back on the launcher asks before leaving. Layout (favorites, order, hidden, folders, wallpaper) is stored on this TV only (`vhomeLauncher.v1`); first run copies the household's pinned apps once.
- Before/after (desktop preview, not the TV): [before](docs/screenshots/before-home.png) · [after](docs/screenshots/after-launcher-curated.png) · [after, sample catalog](docs/screenshots/after-launcher-sample-catalog.png)
