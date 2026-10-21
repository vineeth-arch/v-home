// Launcher layout, local to this TV only (no cloud). Key is outside the "vhome." prefix that the crash
// Boundary wipes, so a crash never destroys the layout. WS-B implements the bodies; signatures are fixed.
import type { CatalogEntry } from './catalog'
import { isValidAppId } from './apps'

export const LAUNCHER_KEY = 'vhomeLauncher.v1'
export const MAX_FAVORITES = 6
export const WALLPAPERS = ['dusk', 'ocean', 'forest', 'ember', 'graphite'] as const
export interface Folder { id: string; name: string; apps: string[] }
export interface LauncherPrefs {
  favorites: string[] // entry ids, dock order, max 6
  order: string[]     // grid order; ids not listed go to the end
  hidden: string[]
  folders: Folder[]
  wallpaper: string   // preset id
  reducedMotion: boolean
  seeded: boolean     // favorites seeded once from household pins
}
export const DEFAULT_LAUNCHER_PREFS: LauncherPrefs = { favorites: [], order: [], hidden: [], folders: [], wallpaper: 'dusk', reducedMotion: false, seeded: false }

const ids = (raw: unknown): string[] => {
  if (!Array.isArray(raw)) return []
  const seen = new Set<string>(); const out: string[] = []
  for (const v of raw) if (isValidAppId(v) && !seen.has(v)) { seen.add(v); out.push(v) }
  return out
}

/** Never throws; bad values fall back to defaults. */
export function resolveLauncherPrefs(raw: unknown): LauncherPrefs {
  try {
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return { ...DEFAULT_LAUNCHER_PREFS }
    const r = raw as Record<string, unknown>
    const inFolder = new Set<string>(); const folderIds = new Set<string>(); const folders: Folder[] = []
    if (Array.isArray(r.folders)) for (const f of r.folders) {
      if (!f || typeof f !== 'object') continue
      const fo = f as Record<string, unknown>
      const name = typeof fo.name === 'string' ? fo.name.trim() : ''
      if (typeof fo.id !== 'string' || !fo.id || folderIds.has(fo.id) || name.length < 1 || name.length > 30) continue
      const apps = ids(fo.apps).filter((a) => !inFolder.has(a))
      apps.forEach((a) => inFolder.add(a)); folderIds.add(fo.id)
      folders.push({ id: fo.id, name, apps })
    }
    return {
      favorites: ids(r.favorites).slice(0, MAX_FAVORITES),
      order: ids(r.order), hidden: ids(r.hidden), folders,
      wallpaper: (WALLPAPERS as readonly string[]).includes(r.wallpaper as string) ? (r.wallpaper as string) : 'dusk',
      reducedMotion: r.reducedMotion === true,
      seeded: r.seeded === true,
    }
  } catch { return { ...DEFAULT_LAUNCHER_PREFS } }
}

export function loadPrefs(): LauncherPrefs {
  try {
    const t = localStorage.getItem(LAUNCHER_KEY)
    return resolveLauncherPrefs(t ? JSON.parse(t) : null)
  } catch { return resolveLauncherPrefs(null) }
}
export function savePrefs(p: LauncherPrefs): void {
  try { localStorage.setItem(LAUNCHER_KEY, JSON.stringify(p)) } catch { /* storage unavailable */ }
}

export interface Layout {
  dock: CatalogEntry[]      // favorites that exist, max 6
  grid: CatalogEntry[]      // apps not hidden, not system, not in a folder
  inputs: CatalogEntry[]
  folders: { folder: Folder; apps: CatalogEntry[] }[]
  unavailable: CatalogEntry[]
}
export function applyLayout(entries: CatalogEntry[], p: LauncherPrefs): Layout {
  const byId = new Map<string, CatalogEntry>()
  for (const e of entries) if (!byId.has(e.id)) byId.set(e.id, e)
  const hidden = new Set(p.hidden)
  const inFolder = new Set(p.folders.flatMap((f) => f.apps))
  const dock = p.favorites.flatMap((id) => { const e = byId.get(id); return e && !hidden.has(id) ? [e] : [] }).slice(0, MAX_FAVORITES)
  const inputs = [...byId.values()].filter((e) => e.kind === 'input' && !hidden.has(e.id) && !e.system && !e.unavailable)
  const pool = [...byId.values()].filter((e) => e.kind === 'app' && !e.system && !hidden.has(e.id) && !inFolder.has(e.id))
  const rank = new Map(p.order.map((id, i) => [id, i]))
  const ordered = pool.filter((e) => rank.has(e.id)).sort((a, b) => rank.get(a.id)! - rank.get(b.id)!)
  const grid = [...ordered, ...pool.filter((e) => !rank.has(e.id))]
  const folders = p.folders.map((folder) => ({ folder, apps: folder.apps.flatMap((id) => { const e = byId.get(id); return e ? [e] : [] }) }))
  const referenced = new Set([...p.favorites, ...p.order, ...inFolder])
  const unavailable = [...byId.values()].filter((e) => e.unavailable && referenced.has(e.id))
  return { dock, grid, inputs, folders, unavailable }
}

/** Moves id within list by delta positions (clamped); returns a new list. Unknown id: unchanged copy. */
export function moveId(list: string[], id: string, delta: number): string[] {
  const i = list.indexOf(id)
  if (i < 0) return [...list]
  const j = Math.max(0, Math.min(list.length - 1, i + delta))
  const out = [...list]; out.splice(i, 1); out.splice(j, 0, id)
  return out
}

export function toggleFavorite(p: LauncherPrefs, id: string): LauncherPrefs {
  if (p.favorites.includes(id)) return { ...p, favorites: p.favorites.filter((f) => f !== id) }
  if (!isValidAppId(id) || p.favorites.length >= MAX_FAVORITES) return p
  return { ...p, favorites: [...p.favorites, id] }
}

export function toggleHidden(p: LauncherPrefs, id: string): LauncherPrefs {
  return { ...p, hidden: p.hidden.includes(id) ? p.hidden.filter((h) => h !== id) : isValidAppId(id) ? [...p.hidden, id] : p.hidden }
}

const cleanName = (n: string) => n.trim().slice(0, 30)
const stripFromFolders = (folders: Folder[], moved: Set<string>): Folder[] => folders.map((f) => ({ ...f, apps: f.apps.filter((a) => !moved.has(a)) }))

export function createFolder(p: LauncherPrefs, name: string, appIds: string[]): LauncherPrefs {
  const n = cleanName(name)
  if (!n) return p
  const apps = ids(appIds)
  let k = p.folders.length + 1; const taken = new Set(p.folders.map((f) => f.id))
  while (taken.has('f' + k)) k++
  return { ...p, folders: [...stripFromFolders(p.folders, new Set(apps)), { id: 'f' + k, name: n, apps }] }
}

/** Removes the folder; its apps return to the grid. */
export function deleteFolder(p: LauncherPrefs, id: string): LauncherPrefs {
  return { ...p, folders: p.folders.filter((f) => f.id !== id) }
}

export function renameFolder(p: LauncherPrefs, id: string, name: string): LauncherPrefs {
  const n = cleanName(name)
  return n ? { ...p, folders: p.folders.map((f) => (f.id === id ? { ...f, name: n } : f)) } : p
}

/** folderId null = back to the grid. An app lives in at most one folder. */
export function moveToFolder(p: LauncherPrefs, appId: string, folderId: string | null): LauncherPrefs {
  if (!isValidAppId(appId)) return p
  if (folderId !== null && !p.folders.some((f) => f.id === folderId)) return p
  const stripped = stripFromFolders(p.folders, new Set([appId]))
  return { ...p, folders: stripped.map((f) => (f.id === folderId ? { ...f, apps: [...f.apps, appId] } : f)) }
}
