import type { EventItem, Snapshot, TaskItem } from './model'
import type { Mode } from './modes'
import { localDate } from './daily'

export type Upcoming = { key: string; when: string; title: string; kind: 'event' | 'task' }

/** Up to `n` commitments: Morning = today, Evening = tomorrow, Home = today then tomorrow. Events first, then open tasks (today only). */
export function upcoming(s: Snapshot, now: Date, mode: Mode, n = 3): Upcoming[] {
  const tz = s.household.tz
  const today = localDate(now, tz), tomorrow = localDate(new Date(now.getTime() + 864e5), tz)
  const days = mode === 'evening' ? [tomorrow] : mode === 'morning' ? [today] : [today, tomorrow]
  const evs = [...s.events].filter((e: EventItem) => days.includes(localDate(new Date(e.at), tz))).sort((a, b) => a.at.localeCompare(b.at))
  const out: Upcoming[] = evs.map((e) => ({ key: e.id, when: e.at, title: e.title, kind: 'event' as const }))
  if (mode !== 'evening') for (const t of s.tasks.filter((t: TaskItem) => !t.done && t.kind === 'task')) out.push({ key: t.id, when: '', title: t.title, kind: 'task' })
  return out.slice(0, n)
}
