import type { Mode } from './modes'

/** Household display preferences (households.settings.tv). Layout stays fixed; these tune it. */
export interface TvPrefs {
  featuredDreamId: string | null
  hero: 'dream' | 'reflection'
  morning: [number, number]   // minutes since midnight, [start, end)
  evening: [number, number]
  showToday: boolean
  showForUs: boolean
  defaultMode: 'auto' | Mode
}
export const DEFAULT_PREFS: TvPrefs = {
  featuredDreamId: null, hero: 'dream', morning: [300, 660], evening: [1080, 300], showToday: true, showForUs: true, defaultMode: 'auto',
}

const clamp = (n: unknown, fallback: number) => (typeof n === 'number' && Number.isFinite(n) ? Math.min(1439, Math.max(0, Math.round(n))) : fallback)
const win = (v: unknown, d: [number, number]): [number, number] => {
  if (!Array.isArray(v) || v.length !== 2) return d
  const w: [number, number] = [clamp(v[0], d[0]), clamp(v[1], d[1])]
  return w[0] === w[1] ? d : w // an empty (or all-day) window is not a schedule
}
const MODES = ['auto', 'home', 'morning', 'evening']

/** Never throws; any bad or missing value falls back to its default. dreams = the ones this display can see. */
export function resolvePrefs(raw: unknown, dreams: { id: string }[]): TvPrefs {
  const t = (raw && typeof raw === 'object' ? raw : {}) as Record<string, unknown>
  const featured = typeof t.featuredDreamId === 'string' && dreams.some((d) => d.id === t.featuredDreamId) ? t.featuredDreamId : null
  return {
    featuredDreamId: featured,
    hero: t.hero === 'reflection' ? 'reflection' : 'dream',
    morning: win(t.morning, DEFAULT_PREFS.morning), evening: win(t.evening, DEFAULT_PREFS.evening),
    showToday: t.showToday !== false, showForUs: t.showForUs !== false,
    defaultMode: MODES.includes(t.defaultMode as string) ? (t.defaultMode as TvPrefs['defaultMode']) : 'auto',
  }
}

/** The dream shown as the hero, or undefined for reflection-only. Falls back to the first visible dream. */
export const heroDream = <D extends { id: string }>(p: TvPrefs, dreams: D[]): D | undefined =>
  p.hero === 'reflection' ? undefined : dreams.find((d) => d.id === p.featuredDreamId) ?? dreams[0]

const inWin = (m: number, [s, e]: [number, number]) => (s <= e ? m >= s && m < e : m >= s || m < e)
/** True when some minute of the day is inside both windows (the TV resolves ties as Morning). */
export const windowsOverlap = (a: [number, number], b: [number, number]) => {
  for (let m = 0; m < 1440; m += 1) if (inWin(m, a) && inWin(m, b)) return true
  return false
}

export const toHHMM = (m: number) => `${String(Math.floor(m / 60)).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`
export const fromHHMM = (s: string): number | null => { const m = /^(\d{1,2}):(\d{2})$/.exec(s); if (!m) return null; const v = Number(m[1]) * 60 + Number(m[2]); return Number(m[1]) < 24 && Number(m[2]) < 60 ? v : null }
