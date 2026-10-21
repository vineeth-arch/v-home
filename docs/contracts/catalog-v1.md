# Catalog v1 contract

Written by the Mac companion (`python -m vhome_companion sync-catalog`) to repo-root `tv-catalog/` (gitignored):

- `tv-catalog/catalog.json` — shape below, sample in `catalog-v1.sample.json`.
- `tv-catalog/icons/<file>` — icon files referenced by `entries[].icon` (basename only, `[a-zA-Z0-9._-]`, `.png`/`.jpg`).

The TV build bundles both with `import.meta.glob` (works on `file://`). Missing folder = curated fallback list.

| Field | Type | Rule |
|---|---|---|
| `schema` | `1` | anything else rejected |
| `generatedAt` | ISO string | |
| `tv` | `{model, firmware}` strings | informational |
| `entries[].id` | string | `/^[a-zA-Z0-9._-]{2,100}$/`, unique; stable identity |
| `entries[].title` | string | 1–60 chars after trim |
| `entries[].kind` | `"app"` \| `"input"` | inputs launch by their appId (e.g. `com.webos.app.hdmi1`) |
| `entries[].icon` | string \| null | null when download failed; entry is kept |
| `entries[].color` | string \| null (optional) | `#rrggbb` edge colour of the icon, the tile background; absent/invalid = neutral tint |
| `entries[].source` | `"companion"` \| `"tv"` \| `"curated"` | |
| `entries[].system` | boolean | true = internal helper; hidden from grid, shown in Diagnostics |

Invalid entries are dropped individually; an invalid file falls back to the curated list. Max 200 entries.
