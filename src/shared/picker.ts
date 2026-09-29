export type Pref = 'want' | 'maybe' | 'pass'
export interface WatchEntry { id: string; title: string; type: 'movie' | 'series'; runtimeMin: number | null; service?: string; mood?: string; watched?: boolean }
export type Prefs = Record<string, Pref | undefined> // key = userId
export interface Filters { type?: 'movie' | 'series'; mood?: string; service?: string; maxMinutes?: number; includeUnknown?: boolean }

export interface Candidate { entry: WatchEntry; prefs: Prefs }

export function eligible(cands: Candidate[], members: string[], f: Filters = {}): Candidate[] {
  const includeUnknown = f.includeUnknown ?? true
  return cands.filter(({ entry: e, prefs }) => {
    if (e.watched) return false
    if (members.some((m) => prefs[m] === 'pass')) return false
    if (f.type && e.type !== f.type) return false
    if (f.mood && e.mood !== f.mood) return false
    if (f.service && e.service !== f.service) return false
    if (f.maxMinutes != null) {
      if (e.runtimeMin == null) return includeUnknown // unknown stays unknown
      if (e.runtimeMin > f.maxMinutes) return false
    }
    return true
  })
}

const score = (p: Prefs, members: string[]) => {
  const v = members.map((m) => p[m])
  if (v.every((x) => x === 'want')) return 3
  if (v.every((x) => x === 'want' || x === 'maybe') && v.some((x) => x === 'want')) return 2
  return v.some((x) => x === 'want') ? 1 : 0
}
export const rank = (c: Candidate[], members: string[]) => [...c].sort((a, b) => score(b.prefs, members) - score(a.prefs, members))

export function topMatches(cands: Candidate[], members: string[], f: Filters, n = 3) { return rank(eligible(cands, members, f), members).slice(0, n) }

/** Random pick among the best-ranked tier so a mutual Want always beats a lone Want. */
export function pickForUs(cands: Candidate[], members: string[], f: Filters, rng: () => number = Math.random): Candidate | null {
  const r = rank(eligible(cands, members, f), members)
  if (!r.length) return null
  const top = score(r[0].prefs, members)
  const tier = r.filter((c) => score(c.prefs, members) === top)
  return tier[Math.floor(rng() * tier.length)]
}

/** Explain why nothing matched and which filters could be relaxed. */
export function explainEmpty(cands: Candidate[], members: string[], f: Filters): string[] {
  if (!cands.length) return ['The shared list is empty. Add titles on your phone.']
  const out: string[] = []
  const notPassed = cands.filter((c) => !c.entry.watched && !members.some((m) => c.prefs[m] === 'pass'))
  if (!notPassed.length) return ['Every title is watched or marked Pass by one of you.']
  for (const key of ['maxMinutes', 'mood', 'service', 'type'] as const) {
    if (f[key] != null && eligible(cands, members, { ...f, [key]: undefined }).length) out.push(`Remove the ${key === 'maxMinutes' ? 'time' : key} filter`)
  }
  return out.length ? out : ['No title fits these filters together. Try clearing them.']
}
