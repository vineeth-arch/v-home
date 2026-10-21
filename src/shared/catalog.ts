// Launcher catalog (contract: docs/contracts/catalog-v1.md). WS-B implements the bodies; signatures are fixed.
import { isValidAppId } from './apps'
import { CANDIDATE_APPS } from './model'

export type Capability = 'supported' | 'denied' | 'unavailable' | 'unverified'
export type LaunchOutcome = 'accepted' | 'failed' | 'unknown' // accepted != destination rendered
export type EntrySource = 'companion' | 'tv' | 'curated'

export interface CatalogEntry {
  id: string
  title: string
  kind: 'app' | 'input'
  icon: string | null // basename in tv-catalog/icons, or null
  iconSrc?: string // icon file on the TV itself (apps found live, not in the bundled export)
  color?: string | null // '#rrggbb' edge colour of the icon, used as the tile background
  source: EntrySource
  system: boolean
  unavailable?: boolean // was in a previous catalog, missing now; layout keeps it
}
export interface Catalog { schema: 1; generatedAt: string; tv: { model: string; firmware: string }; entries: CatalogEntry[] }

const ICON_RE = /^[a-zA-Z0-9._-]{1,100}\.(png|jpe?g)$/i
const COLOR_RE = /^#[0-9a-fA-F]{6}$/
const SOURCES: EntrySource[] = ['companion', 'tv', 'curated']
export const MAX_ENTRIES = 200

function parseEntry(raw: unknown): CatalogEntry | null {
  if (!raw || typeof raw !== 'object') return null
  const r = raw as Record<string, unknown>
  if (!isValidAppId(r.id)) return null
  const title = typeof r.title === 'string' ? r.title.trim() : ''
  if (title.length < 1 || title.length > 60) return null
  if (r.kind !== 'app' && r.kind !== 'input') return null
  if (r.icon !== null && r.icon !== undefined && !(typeof r.icon === 'string' && ICON_RE.test(r.icon))) return null
  if (!SOURCES.includes(r.source as EntrySource)) return null
  const color = typeof r.color === 'string' && COLOR_RE.test(r.color) ? r.color.toLowerCase() : null
  return { id: r.id, title, kind: r.kind, icon: typeof r.icon === 'string' ? r.icon : null, color, source: r.source as EntrySource, system: r.system === true }
}

/** Validates a raw catalog.json value. Drops bad entries; null when the file itself is invalid. */
export function parseCatalog(raw: unknown): Catalog | null {
  try {
    if (!raw || typeof raw !== 'object') return null
    const r = raw as Record<string, unknown>
    if (r.schema !== 1 || !Array.isArray(r.entries)) return null
    const seen = new Set<string>(); const entries: CatalogEntry[] = []
    for (const item of r.entries) {
      const e = parseEntry(item)
      if (!e || seen.has(e.id)) continue
      seen.add(e.id); entries.push(e)
      if (entries.length >= MAX_ENTRIES) break
    }
    const tv = (r.tv && typeof r.tv === 'object' ? r.tv : {}) as Record<string, unknown>
    return {
      schema: 1,
      generatedAt: typeof r.generatedAt === 'string' ? r.generatedAt : '',
      tv: { model: typeof tv.model === 'string' ? tv.model : '', firmware: typeof tv.firmware === 'string' ? tv.firmware : '' },
      entries,
    }
  } catch { return null }
}

// Bundled at build time; the folder is gitignored and usually absent (globs are then empty).
const catalogFiles = import.meta.glob('/tv-catalog/catalog.json', { eager: true, import: 'default' }) as Record<string, unknown>
const iconFiles = import.meta.glob('/tv-catalog/icons/*', { eager: true, query: '?url', import: 'default' }) as Record<string, unknown>

let cached: Catalog | null = null
/** Catalog bundled into this build (tv-catalog/), else curated candidates. Never throws. */
export function bundledCatalog(): Catalog {
  if (cached) return cached
  let c: Catalog | null = null
  try { c = parseCatalog(Object.values(catalogFiles)[0]) } catch { c = null }
  if (!c) {
    c = {
      schema: 1, generatedAt: '', tv: { model: '', firmware: '' },
      entries: CANDIDATE_APPS.map((a) => ({ id: a.id, title: a.label, kind: a.id.includes('.hdmi') ? 'input' as const : 'app' as const, icon: null, source: 'curated' as const, system: false })),
    }
  }
  cached = c
  return c
}

/** Refresh: keeps prev order, marks vanished entries unavailable, appends new ones, no duplicate ids. */
export function mergeEntries(prev: CatalogEntry[], next: CatalogEntry[]): CatalogEntry[] {
  const nextById = new Map<string, CatalogEntry>()
  for (const n of next) if (!nextById.has(n.id)) nextById.set(n.id, n)
  const out: CatalogEntry[] = []; const seen = new Set<string>()
  for (const p of prev) {
    if (seen.has(p.id)) continue
    seen.add(p.id)
    const n = nextById.get(p.id)
    if (n) { const { unavailable: _u, ...rest } = n; out.push({ ...rest }) } else out.push({ ...p, unavailable: true })
  }
  for (const n of nextById.values()) {
    if (seen.has(n.id)) continue
    seen.add(n.id); const { unavailable: _u, ...rest } = n; out.push({ ...rest })
  }
  return out
}

// Same rule as companion catalog.py `_is_system`: internal webOS helpers and V/HOME itself stay out of the grid.
export const VHOME_ID = 'com.designinnsaeit.vhome'
const USER_FACING = new Set(['com.webos.app.browser', 'com.webos.app.photovideo', 'com.webos.app.music', 'com.webos.app.screenshare', 'com.webos.app.livetv'])
export const isSystemApp = (id: string, kind: CatalogEntry['kind'], hiddenByTv = false) =>
  kind === 'app' && (hiddenByTv || id === VHOME_ID || (id.startsWith('com.webos.app.') && !USER_FACING.has(id)))

/** Icon path from the TV's own app list -> a file:// URL, only for a plain absolute image path (no '..', no query). */
export function tvIconSrc(raw: unknown): string | undefined {
  if (typeof raw !== 'string') return undefined
  const p = raw.startsWith('file://') ? raw.slice(7) : raw
  return /^\/[A-Za-z0-9._\/-]{1,200}\.(png|jpe?g)$/i.test(p) && !p.includes('..') ? `file://${p}` : undefined
}

const PREV_KEY = 'vhomeLauncher.catalog.v1'
/** Remembers the last catalog on this TV so apps that disappear stay in the layout, greyed ("Not on this TV"),
 *  instead of silently vanishing. Only entries the layout still references are kept as unavailable. Never throws. */
export function withRemembered(current: CatalogEntry[], referenced: (id: string) => boolean): CatalogEntry[] {
  let prev: CatalogEntry[] = []
  try { prev = parseCatalog({ schema: 1, generatedAt: '', tv: { model: '', firmware: '' }, entries: JSON.parse(localStorage.getItem(PREV_KEY) ?? '[]') })?.entries ?? [] } catch { prev = [] }
  const merged = mergeEntries(prev, current).filter((e) => !e.unavailable || referenced(e.id))
  try { localStorage.setItem(PREV_KEY, JSON.stringify(merged.map(({ unavailable: _u, ...e }) => e))) } catch { /* storage unavailable */ }
  return merged
}

/** URL usable in <img src> for the entry's bundled icon, or null (show lettered fallback). */
export function iconUrl(e: CatalogEntry): string | null {
  if (!e.icon) return e.iconSrc ?? null
  const key = Object.keys(iconFiles).find((k) => k.endsWith('/' + e.icon))
  const v = key ? iconFiles[key] : null
  return typeof v === 'string' && v ? v : null
}
