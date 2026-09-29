import { describe, expect, it } from 'vitest'
import { DEFAULT_STUDIO, resolveStudio, sanitizeMetrics, shouldFetch, studioVisible } from '../../supabase/functions/_shared/studio'

const on = { ...DEFAULT_STUDIO, enabled: true }
const ist = (s: string) => new Date(`${s}+05:30`)

describe('studio settings', () => {
  it('defaults and bad values', () => {
    expect(resolveStudio(undefined)).toEqual(DEFAULT_STUDIO)
    expect(resolveStudio({ enabled: true, window: { days: [9, 1, 1], start: 1200, end: 600 }, sources: { forms: false } })).toMatchObject({ enabled: true, window: DEFAULT_STUDIO.window, sources: { invoices: true, outreach: true, forms: false } })
    expect(resolveStudio({ window: { days: [6, 1], start: 600, end: 700 } }).window).toEqual({ days: [1, 6], start: 600, end: 700 })
  })
  it('visible only on work days inside the window, never for guests or when off', () => {
    expect(studioVisible(on, ist('2026-09-30T09:00:00'), 'Asia/Kolkata', false)).toBe(true)   // Wed 09:00
    expect(studioVisible(on, ist('2026-09-30T17:59:00'), 'Asia/Kolkata', false)).toBe(true)
    expect(studioVisible(on, ist('2026-09-30T18:00:00'), 'Asia/Kolkata', false)).toBe(false)
    expect(studioVisible(on, ist('2026-10-03T11:00:00'), 'Asia/Kolkata', false)).toBe(false)  // Saturday
    expect(studioVisible(on, ist('2026-09-30T11:00:00'), 'Asia/Kolkata', true)).toBe(false)
    expect(studioVisible(DEFAULT_STUDIO, ist('2026-09-30T11:00:00'), 'Asia/Kolkata', false)).toBe(false)
  })
})

describe('studio metrics', () => {
  const raw = [
    { key: 'followups_next', label: 'Next follow-ups', value: 2, detail: { items: [{ due: '2026-09-30', stage: 'Contacted', name: 'Aura Teas' }] } },
    { key: 'invoices_open_total', label: 'Waiting to be paid', value: '14800' },
    { key: 'Bad Key!', label: 'x', value: 1 }, { key: 'no_label', value: 1 }, 'junk',
  ]
  it('prefixes keys with the source, parses numbers, drops junk, strips names by default', () => {
    const rows = sanitizeMetrics('outreach', raw, false)
    expect(rows.map((r) => r.key)).toEqual(['outreach.followups_next', 'outreach.invoices_open_total'])
    expect(rows[0].detail.items).toEqual([{ due: '2026-09-30', stage: 'Contacted' }])
    expect(rows[1].value).toBe(14800)
  })
  it('keeps names only when asked', () => expect(sanitizeMetrics('outreach', raw, true)[0].detail.items).toEqual([{ due: '2026-09-30', stage: 'Contacted', name: 'Aura Teas' }]))
  it('throttles displays to 15 min and members to 1 min', () => {
    expect(shouldFetch(null, 0, 'display')).toBe(true)
    expect(shouldFetch(0, 14 * 60_000, 'display')).toBe(false)
    expect(shouldFetch(0, 15 * 60_000, 'display')).toBe(true)
    expect(shouldFetch(0, 60_000, 'member')).toBe(true)
  })
})
