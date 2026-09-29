/** Ambient photo frame order: "on this day" photos first (with how many years ago), then least recently shown. */
export interface AmbientPhoto { path: string; takenOn?: string; caption?: string }
export interface AmbientItem extends AmbientPhoto { yearsAgo?: number }

const isLeap = (y: number) => (y % 4 === 0 && y % 100 !== 0) || y % 400 === 0

/** Years since `takenOn` if it falls on today's month/day (a Feb 29 photo counts on Feb 28 in other years). */
export function onThisDay(takenOn: string | undefined, today: string): number | undefined {
  if (!takenOn) return undefined
  const [ty, tm, td] = takenOn.split('-').map(Number), [y, m, d] = today.split('-').map(Number)
  const years = y - ty
  if (years < 1) return undefined
  const same = tm === m && (td === d || (tm === 2 && td === 29 && d === 28 && !isLeap(y)))
  return same ? years : undefined
}

export function ambientQueue(photos: AmbientPhoto[], today: string, lastShown: ReadonlyMap<string, number> = new Map()): AmbientItem[] {
  const seen = new Set<string>()
  const uniq = photos.filter((p) => !seen.has(p.path) && seen.add(p.path))
  const withYears = uniq.map((p): AmbientItem => ({ ...p, yearsAgo: onThisDay(p.takenOn, today) }))
  const when = (p: AmbientItem) => lastShown.get(p.path) ?? 0
  return [...withYears.filter((p) => p.yearsAgo), ...withYears.filter((p) => !p.yearsAgo).sort((a, b) => when(a) - when(b))]
}
