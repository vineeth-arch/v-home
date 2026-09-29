// Studio (business command center). Pure helpers shared by the business-sync Edge Function, the TV and the phone.
// No Deno or browser APIs here.
export type SourceKey = 'invoices' | 'outreach' | 'forms'
export const SOURCES: { key: SourceKey; label: string; secret: string }[] = [
  { key: 'invoices', label: 'Invoices', secret: 'STUDIO_INVOICES_DB' },
  { key: 'outreach', label: 'Outreach', secret: 'STUDIO_OUTREACH_DB' },
  { key: 'forms', label: 'Questionnaires', secret: 'STUDIO_FORMS_DB' },
]

export interface StudioWindow { days: number[]; start: number; end: number } // ISO weekdays 1=Mon..7=Sun, minutes [start, end)
export interface StudioSettings { enabled: boolean; sources: Record<SourceKey, boolean>; showNames: boolean; window: StudioWindow }
export const DEFAULT_STUDIO: StudioSettings = {
  enabled: false, sources: { invoices: true, outreach: true, forms: true }, showNames: false,
  window: { days: [1, 2, 3, 4, 5], start: 9 * 60, end: 18 * 60 },
}

/** households.settings.studio -> settings. Never throws; bad values fall back to defaults. */
export function resolveStudio(raw: unknown): StudioSettings {
  const t = (raw && typeof raw === 'object' ? raw : {}) as Record<string, any>
  const min = (v: unknown, d: number) => (typeof v === 'number' && Number.isInteger(v) && v >= 0 && v <= 1439 ? v : d)
  const w = (t.window && typeof t.window === 'object' ? t.window : {}) as Record<string, unknown>
  const days = Array.isArray(w.days) ? [...new Set(w.days.filter((d): d is number => Number.isInteger(d) && d >= 1 && d <= 7))].sort() : DEFAULT_STUDIO.window.days
  const start = min(w.start, DEFAULT_STUDIO.window.start), end = min(w.end, DEFAULT_STUDIO.window.end)
  const src = (t.sources && typeof t.sources === 'object' ? t.sources : {}) as Record<string, unknown>
  return {
    enabled: t.enabled === true,
    sources: { invoices: src.invoices !== false, outreach: src.outreach !== false, forms: src.forms !== false },
    showNames: t.showNames === true,
    window: start < end ? { days, start, end } : DEFAULT_STUDIO.window, // no overnight work window
  }
}

/** Local ISO weekday (1=Mon) and minutes since midnight in the household timezone. */
function localDayMin(now: Date, tz: string): { day: number; min: number } {
  const p = Object.fromEntries(new Intl.DateTimeFormat('en-US', { timeZone: tz, weekday: 'short', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).formatToParts(now).map((x) => [x.type, x.value]))
  const day = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].indexOf(p.weekday) + 1
  return { day, min: Number(p.hour) * 60 + Number(p.minute) }
}

/** Studio shows only when enabled, inside the work window, and never in guest view. */
export function studioVisible(s: StudioSettings, now: Date, tz: string, guest: boolean): boolean {
  if (!s.enabled || guest) return false
  const { day, min } = localDayMin(now, tz)
  return s.window.days.includes(day) && min >= s.window.start && min < s.window.end
}

export interface MetricRow { key: string; source: SourceKey; label: string; value: number | null; detail: Record<string, unknown>; ok: boolean }

/** A source's di_studio_summary() output -> rows. Drops malformed entries; strips names unless showNames. */
export function sanitizeMetrics(source: SourceKey, raw: unknown, showNames: boolean): MetricRow[] {
  if (!Array.isArray(raw)) return []
  return raw.flatMap((m): MetricRow[] => {
    const key = (m as any)?.key, label = (m as any)?.label, value = (m as any)?.value
    if (typeof key !== 'string' || !/^[a-z_]{2,40}$/.test(key) || typeof label !== 'string' || !label.trim()) return []
    const detail = (m as any)?.detail && typeof (m as any).detail === 'object' ? { ...(m as any).detail } : {}
    if (Array.isArray(detail.items)) detail.items = detail.items.slice(0, 3).map((it: any) => ({ due: it?.due, stage: it?.stage, ...(showNames && typeof it?.name === 'string' ? { name: it.name } : {}) }))
    const n = typeof value === 'number' ? value : typeof value === 'string' && value.trim() !== '' && Number.isFinite(Number(value)) ? Number(value) : null
    return [{ key: `${source}.${key}`, source, label: label.trim().slice(0, 60), value: n, detail, ok: true }]
  })
}

/** Throttle: a display may trigger a fetch every 15 min, a member every minute. */
export const minIntervalMs = (role: 'member' | 'display') => (role === 'member' ? 60_000 : 15 * 60_000)
export const shouldFetch = (lastFetchedAt: number | null, now: number, role: 'member' | 'display') => lastFetchedAt === null || now - lastFetchedAt >= minIntervalMs(role)
