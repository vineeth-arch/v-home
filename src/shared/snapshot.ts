import type { Dream, EventItem, Idea, Moment, NoteItem, Snapshot, TaskItem, WatchItem } from './model'
import { resolvePrefs } from './prefs'
import { sanitizeCustomApps } from './apps'
import type { WeeklyPayload } from './week'

/** Raw rows as returned by the TV-scoped selects. Column names match the DB. */
export interface Rows {
  household: { id: string; name: string; timezone: string; settings: Record<string, unknown> }
  quotes: { id: string; slot: 'morning' | 'evening'; body: string; author: string | null; source: string | null; favorite: boolean }[]
  weekly: { day: string; payload: Record<string, unknown> }[]
  members: { user_id: string; role: string; display_name: string }[]
  events: { id: string; title: string; starts_at: string; all_day: boolean }[]
  tasks: { id: string; title: string; owner: string; kind: 'task' | 'grocery'; done: boolean }[]
  notes: { id: string; body: string; author_id: string; to_user?: string | null; created_at?: string }[]
  media?: { path: string; taken_on: string | null; caption: string | null }[]
  dreams: { id: string; title: string; why: string; affirmation: string; next_step: string; target_date: string | null; art: string; image_path?: string | null }[]
  ideas: { id: string; title: string; note: string; status: Idea['status']; author_id: string; pinned: boolean; image_path?: string | null }[]
  watch_entries: { id: string; title: string; type: 'movie' | 'series'; runtime_min: number | null; service: string | null; mood: string | null; summary: string | null; watched: boolean; providers: Record<string, string[]>; providers_updated_at: string | null; poster_path?: string | null }[]
  watch_prefs: { entry_id: string; user_id: string; pref: 'want' | 'maybe' | 'pass' }[]
}

const ART = ['sun', 'hills', 'sea', 'window'] as const

/** Pure mapper: DB rows to the TV/phone Snapshot. Missing settings never throw. */
export function toSnapshot(r: Rows, now = Date.now()): Snapshot {
  const st = r.household.settings ?? {}
  const num = (v: unknown) => (typeof v === 'number' ? v : undefined)
  const prefsBy = new Map<string, WatchItem['prefs']>()
  for (const p of r.watch_prefs) prefsBy.set(p.entry_id, { ...(prefsBy.get(p.entry_id) ?? {}), [p.user_id]: p.pref })
  return {
    household: {
      id: r.household.id, name: r.household.name, tz: r.household.timezone,
      hiddenReflections: Array.isArray(st.hiddenReflections) ? (st.hiddenReflections as string[]).filter((x) => typeof x === 'string') : [],
      people: r.members.filter((m) => m.role === 'member').map((m) => ({ id: m.user_id, name: m.display_name })),
      city: typeof st.city === 'string' ? st.city : undefined, lat: num(st.lat), lon: num(st.lon),
      region: typeof st.region === 'string' ? st.region : undefined,
      pinnedApps: Array.isArray(st.pinnedApps) ? (st.pinnedApps as Snapshot['household']['pinnedApps']) : [],
      customApps: sanitizeCustomApps(st.customApps),
      prefs: resolvePrefs(st.tv, r.dreams),
    },
    events: r.events.map((e): EventItem => ({ id: e.id, title: e.title, at: e.starts_at, allDay: e.all_day })),
    tasks: r.tasks.map((t): TaskItem => ({ id: t.id, title: t.title, owner: t.owner, kind: t.kind, done: t.done })),
    notes: r.notes.map((n): NoteItem => ({ id: n.id, text: n.body, author: n.author_id, to: n.to_user ?? undefined, at: n.created_at })),
    dreams: r.dreams.map((d): Dream => ({ id: d.id, title: d.title, why: d.why, affirmation: d.affirmation, nextStep: d.next_step, targetDate: d.target_date ?? undefined, art: (ART as readonly string[]).includes(d.art) ? (d.art as Dream['art']) : 'sun', imagePath: d.image_path ?? undefined })),
    ideas: r.ideas.map((i): Idea => ({ id: i.id, title: i.title, note: i.note, status: i.status, author: i.author_id, pinned: i.pinned, imagePath: i.image_path ?? undefined })),
    watch: r.watch_entries.map((w): WatchItem => ({
      entry: { id: w.id, title: w.title, type: w.type, runtimeMin: w.runtime_min, service: w.service ?? undefined, mood: w.mood ?? undefined, summary: w.summary ?? undefined, watched: w.watched, providers: w.providers, providersUpdatedAt: w.providers_updated_at ?? undefined, posterPath: w.poster_path ?? undefined },
      prefs: prefsBy.get(w.id) ?? {},
    })),
    quotes: r.quotes.map((q) => ({ id: q.id, slot: q.slot, text: q.body, author: q.author ?? undefined, source: q.source ?? undefined, favorite: q.favorite })),
    weekly: r.weekly[0] ? { day: r.weekly[0].day, ...(r.weekly[0].payload as WeeklyPayload) } : undefined,
    moments: momentsOf(r),
    syncedAt: now,
  }
}

/** Media rows not attached to a dream or idea are Moments (the TV only ever receives rows marked Show on TV). */
function momentsOf(r: Rows): Moment[] {
  const attached = new Set([...r.dreams.map((d) => d.image_path), ...r.ideas.map((i) => i.image_path)].filter(Boolean))
  return (r.media ?? []).filter((m) => !attached.has(m.path)).map((m) => ({ path: m.path, takenOn: m.taken_on ?? undefined, caption: m.caption ?? undefined }))
}

/**
 * A cached snapshot may come from an older app version (missing newer fields). Fill defaults so a new build never
 * crashes on old cached data; return null when it isn't a snapshot at all (caller then just waits for the network).
 */
export function normalizeSnapshot(raw: unknown): Snapshot | null {
  if (!raw || typeof raw !== 'object') return null
  const s = raw as Partial<Snapshot>
  if (!s.household || typeof s.household !== 'object') return null
  const arr = <T,>(v: T[] | undefined) => (Array.isArray(v) ? v : [])
  const h = s.household as Partial<Snapshot['household']>
  return {
    household: {
      id: h.id ?? '', name: h.name ?? 'Our Home', tz: h.tz ?? 'Asia/Kolkata', hiddenReflections: arr(h.hiddenReflections),
      people: arr(h.people), city: h.city, lat: h.lat, lon: h.lon, region: h.region, pinnedApps: arr(h.pinnedApps), customApps: sanitizeCustomApps(h.customApps),
      prefs: resolvePrefs(h.prefs, arr(s.dreams)),
    },
    events: arr(s.events), tasks: arr(s.tasks), dreams: arr(s.dreams), notes: arr(s.notes), ideas: arr(s.ideas), watch: arr(s.watch),
    quotes: arr(s.quotes), weekly: s.weekly, moments: arr(s.moments), syncedAt: typeof s.syncedAt === 'number' ? s.syncedAt : Date.now(),
  }
}
