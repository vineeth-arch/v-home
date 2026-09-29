import type { Dream, EventItem, Idea, NoteItem, Snapshot, TaskItem, WatchItem } from './model'

/** Raw rows as returned by the TV-scoped selects. Column names match the DB. */
export interface Rows {
  household: { name: string; timezone: string; settings: Record<string, unknown> }
  members: { user_id: string; role: string; display_name: string }[]
  events: { id: string; title: string; starts_at: string; all_day: boolean }[]
  tasks: { id: string; title: string; owner: string; kind: 'task' | 'grocery'; done: boolean }[]
  notes: { id: string; body: string; author_id: string }[]
  dreams: { id: string; title: string; why: string; affirmation: string; next_step: string; target_date: string | null; art: string }[]
  ideas: { id: string; title: string; note: string; status: Idea['status']; author_id: string; pinned: boolean }[]
  watch_entries: { id: string; title: string; type: 'movie' | 'series'; runtime_min: number | null; service: string | null; mood: string | null; summary: string | null; watched: boolean; providers: Record<string, string[]>; providers_updated_at: string | null }[]
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
      name: r.household.name, tz: r.household.timezone,
      people: r.members.filter((m) => m.role === 'member').map((m) => ({ id: m.user_id, name: m.display_name })),
      city: typeof st.city === 'string' ? st.city : undefined, lat: num(st.lat), lon: num(st.lon),
      region: typeof st.region === 'string' ? st.region : undefined,
      pinnedApps: Array.isArray(st.pinnedApps) ? (st.pinnedApps as Snapshot['household']['pinnedApps']) : [],
    },
    events: r.events.map((e): EventItem => ({ id: e.id, title: e.title, at: e.starts_at, allDay: e.all_day })),
    tasks: r.tasks.map((t): TaskItem => ({ id: t.id, title: t.title, owner: t.owner, kind: t.kind, done: t.done })),
    notes: r.notes.map((n): NoteItem => ({ id: n.id, text: n.body, author: n.author_id })),
    dreams: r.dreams.map((d): Dream => ({ id: d.id, title: d.title, why: d.why, affirmation: d.affirmation, nextStep: d.next_step, targetDate: d.target_date ?? undefined, art: (ART as readonly string[]).includes(d.art) ? (d.art as Dream['art']) : 'sun' })),
    ideas: r.ideas.map((i): Idea => ({ id: i.id, title: i.title, note: i.note, status: i.status, author: i.author_id, pinned: i.pinned })),
    watch: r.watch_entries.map((w): WatchItem => ({
      entry: { id: w.id, title: w.title, type: w.type, runtimeMin: w.runtime_min, service: w.service ?? undefined, mood: w.mood ?? undefined, summary: w.summary ?? undefined, watched: w.watched, providers: w.providers, providersUpdatedAt: w.providers_updated_at ?? undefined },
      prefs: prefsBy.get(w.id) ?? {},
    })),
    syncedAt: now,
  }
}
