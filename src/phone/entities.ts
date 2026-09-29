import type { Row } from './api'

export type FieldType = 'text' | 'textarea' | 'datetime' | 'date' | 'checkbox' | 'number' | 'select'
export interface Field { key: string; label: string; type: FieldType; options?: string[]; required?: boolean; defaultValue?: unknown; nullable?: boolean }
export interface Entity {
  table: string; label: string; plural: string; fields: Field[]
  title: (r: Row) => string; sub?: (r: Row) => string
  tvToggle: boolean // dreams and notes must be explicitly shown on TV
  photo?: boolean   // dreams and ideas can carry one photo
}

const S = (v: unknown) => (v == null ? '' : String(v))
export const ENTITIES: Record<string, Entity> = {
  events: { table: 'events', label: 'Event', plural: 'Plans', tvToggle: false,
    fields: [{ key: 'title', label: 'What', type: 'text', required: true }, { key: 'starts_at', label: 'When', type: 'datetime', required: true }, { key: 'all_day', label: 'All day', type: 'checkbox' }],
    title: (r) => S(r.title), sub: (r) => new Date(S(r.starts_at)).toLocaleString() },
  tasks: { table: 'tasks', label: 'Task', plural: 'Tasks', tvToggle: false,
    fields: [{ key: 'title', label: 'Task or grocery', type: 'text', required: true }, { key: 'kind', label: 'Kind', type: 'select', options: ['task', 'grocery'], defaultValue: 'task' }, { key: 'owner', label: 'Whose', type: 'select', options: ['both'], defaultValue: 'both' }, { key: 'done', label: 'Done', type: 'checkbox' }],
    title: (r) => S(r.title), sub: (r) => `${S(r.kind)}${r.done ? ' · done' : ''}` },
  dreams: { table: 'dreams', label: 'Dream', plural: 'Dreams', tvToggle: true, photo: true,
    fields: [{ key: 'title', label: 'Dream', type: 'text', required: true }, { key: 'why', label: 'Why it matters', type: 'textarea' }, { key: 'affirmation', label: 'Affirmation', type: 'textarea' }, { key: 'next_step', label: 'Next small step', type: 'text' }, { key: 'target_date', label: 'Target date', type: 'date' }, { key: 'art', label: 'Art style', type: 'select', options: ['sun', 'hills', 'sea', 'window'], defaultValue: 'sun' }],
    title: (r) => S(r.title), sub: (r) => S(r.next_step) },
  notes: { table: 'notes', label: 'Note', plural: 'Notes', tvToggle: true,
    fields: [{ key: 'body', label: 'Note', type: 'textarea', required: true }, { key: 'to_user', label: 'For (optional: shows on the TV today as a note for them)', type: 'select', nullable: true, defaultValue: '' }],
    title: (r) => S(r.body), sub: (r) => (r.to_user ? 'a note for you' : '') },
  ideas: { table: 'ideas', label: 'Idea', plural: 'Ideas', tvToggle: false, photo: true,
    fields: [{ key: 'title', label: 'Idea', type: 'text', required: true }, { key: 'note', label: 'Note', type: 'textarea' }, { key: 'link', label: 'Link', type: 'text' }, { key: 'status', label: 'Status', type: 'select', options: ['new', 'discuss', 'planned', 'archived'], defaultValue: 'new' }, { key: 'pinned', label: 'Pinned', type: 'checkbox' }],
    title: (r) => S(r.title), sub: (r) => `${S(r.status)}${r.pinned ? ' · pinned' : ''}` },
  quotes: { table: 'quotes', label: 'Reflection', plural: 'Reflections', tvToggle: false,
    fields: [{ key: 'body', label: 'Reflection', type: 'textarea', required: true }, { key: 'slot', label: 'Shown in', type: 'select', options: ['morning', 'evening'], defaultValue: 'morning' }, { key: 'author', label: 'Author (optional)', type: 'text' }, { key: 'source', label: 'Source (optional)', type: 'text' }, { key: 'favorite', label: 'Favourite (shown more often)', type: 'checkbox' }, { key: 'hidden', label: 'Hide from the TV', type: 'checkbox' }],
    title: (r) => S(r.body), sub: (r) => `${S(r.slot)}${r.favorite ? ' · favourite' : ''}${r.hidden ? ' · hidden' : ''}` },
  watch_entries: { table: 'watch_entries', label: 'Title', plural: 'Watch', tvToggle: false,
    fields: [{ key: 'title', label: 'Title', type: 'text', required: true }, { key: 'type', label: 'Type', type: 'select', options: ['movie', 'series'], defaultValue: 'movie' }, { key: 'runtime_min', label: 'Runtime (min, blank if unknown)', type: 'number' }, { key: 'service', label: 'Service', type: 'text' }, { key: 'mood', label: 'Mood', type: 'text' }, { key: 'summary', label: 'Summary', type: 'textarea' }, { key: 'watched', label: 'Watched', type: 'checkbox' }],
    title: (r) => S(r.title), sub: (r) => `${S(r.type)} · ${r.runtime_min ? `${r.runtime_min} min` : 'runtime unknown'}` },
}

/** Form values to DB payload: blanks become null so "unknown" stays unknown. */
export function toPayload(e: Entity, v: Record<string, unknown>) {
  const out: Record<string, unknown> = {}
  for (const f of e.fields) {
    const x = v[f.key]
    if (f.type === 'checkbox') out[f.key] = Boolean(x)
    else if (f.type === 'number') out[f.key] = x === '' || x == null ? null : Number(x)
    else if (f.type === 'datetime') out[f.key] = x ? new Date(String(x)).toISOString() : null
    else if (f.type === 'date' || f.nullable) out[f.key] = x ? String(x) : null
    else out[f.key] = x == null ? '' : x
  }
  return out
}
export const missingRequired = (e: Entity, v: Record<string, unknown>) => e.fields.filter((f) => f.required && !String(v[f.key] ?? '').trim()).map((f) => f.label)
