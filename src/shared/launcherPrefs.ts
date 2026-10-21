// Launcher layout, local to this TV only (no cloud). Key is outside the "vhome." prefix that the crash
// Boundary wipes, so a crash never destroys the layout. WS-B implements the bodies; signatures are fixed.
import type { CatalogEntry } from './catalog'

export const LAUNCHER_KEY = 'vhomeLauncher.v1'
export const MAX_FAVORITES = 6
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

/** Never throws; bad values fall back to defaults. */
export function resolveLauncherPrefs(_raw: unknown): LauncherPrefs { return { ...DEFAULT_LAUNCHER_PREFS } }
export function loadPrefs(): LauncherPrefs { return resolveLauncherPrefs(null) }
export function savePrefs(_p: LauncherPrefs): void {}

export interface Layout {
  dock: CatalogEntry[]      // favorites that exist, max 6
  grid: CatalogEntry[]      // apps not hidden, not system, not in a folder
  inputs: CatalogEntry[]
  folders: { folder: Folder; apps: CatalogEntry[] }[]
  unavailable: CatalogEntry[]
}
export function applyLayout(entries: CatalogEntry[], _p: LauncherPrefs): Layout {
  return { dock: [], grid: entries.filter((e) => e.kind === 'app' && !e.system), inputs: entries.filter((e) => e.kind === 'input'), folders: [], unavailable: [] }
}
