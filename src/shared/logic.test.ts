import { expect, test } from 'vitest'
import { resolveMode, shouldApplyScheduledMode } from './modes'
import { localDate } from './daily'
import { BUNDLED, pickDaily } from './reflections'
import { eligible, explainEmpty, pickForUs, rank, type Candidate } from './picker'

const TZ = 'Asia/Kolkata'
const at = (hhmm: string, day = '2026-09-29') => new Date(`${day}T${hhmm}:00+05:30`)

test('mode windows: wrap, boundaries, manual override', () => {
  expect(resolveMode(at('04:59'), TZ)).toBe('evening')
  expect(resolveMode(at('05:00'), TZ)).toBe('morning')
  expect(resolveMode(at('10:59'), TZ)).toBe('morning')
  expect(resolveMode(at('11:00'), TZ)).toBe('home')
  expect(resolveMode(at('17:59'), TZ)).toBe('home')
  expect(resolveMode(at('18:00'), TZ)).toBe('evening')
  expect(resolveMode(at('23:30'), TZ, undefined, 'morning')).toBe('morning')
})
test('scheduled mode never interrupts', () => {
  const ok = { screen: 'home', ritualActive: false, idleMs: 61_000 }
  expect(shouldApplyScheduledMode('home', 'evening', ok)).toBe(true)
  expect(shouldApplyScheduledMode('home', 'evening', { ...ok, screen: 'watch' })).toBe(false)
  expect(shouldApplyScheduledMode('home', 'evening', { ...ok, ritualActive: true })).toBe(false)
  expect(shouldApplyScheduledMode('home', 'evening', { ...ok, idleMs: 5000 })).toBe(false)
  expect(shouldApplyScheduledMode('home', 'home', ok)).toBe(false)
})
test('localDate uses household tz', () => {
  expect(localDate(new Date('2026-09-29T20:00:00Z'), TZ)).toBe('2026-09-30')
})
test('40 bundled reflections split 20/20; daily pick stable, differs by slot and day', () => {
  expect(BUNDLED.length).toBe(40)
  expect(BUNDLED.filter((r) => r.slot === 'morning').length).toBe(20)
  const a = pickDaily('h1', '2026-09-29', 'morning')!
  expect(pickDaily('h1', '2026-09-29', 'morning')!.id).toBe(a.id)
  expect(pickDaily('h1', '2026-09-29', 'evening')!.slot).toBe('evening')
  const days = new Set(Array.from({ length: 10 }, (_, i) => pickDaily('h1', `2026-10-${10 + i}`, 'morning')!.id))
  expect(days.size).toBeGreaterThan(1)
  expect(pickDaily('h1', '2026-09-29', 'morning', [a.id])!.id).not.toBe(a.id)
})

const M = ['a', 'b']
const c = (id: string, prefs: Candidate['prefs'], over: Partial<Candidate['entry']> = {}): Candidate => ({ entry: { id, title: id, type: 'movie', runtimeMin: 100, ...over }, prefs })
test('picker: pass excludes, mutual want first, unknown runtime stays unknown', () => {
  const list = [c('x', { a: 'want', b: 'pass' }), c('y', { a: 'want', b: 'maybe' }), c('z', { a: 'want', b: 'want' }), c('u', { a: 'want', b: 'want' }, { runtimeMin: null })]
  expect(eligible(list, M).map((x) => x.entry.id)).toEqual(['y', 'z', 'u'])
  expect(rank(eligible(list, M), M)[0].entry.id).toMatch(/z|u/)
  expect(eligible(list, M, { maxMinutes: 90 }).map((x) => x.entry.id)).toEqual(['u'])
  expect(eligible(list, M, { maxMinutes: 90, includeUnknown: false })).toEqual([])
  expect(pickForUs(list, M, {}, () => 0)!.entry.id).toBe('z')
  expect(pickForUs(list, M, { maxMinutes: 10, includeUnknown: false })).toBeNull()
})
test('explainEmpty names filters to relax', () => {
  const list = [c('y', { a: 'want', b: 'want' }, { runtimeMin: 200 })]
  expect(explainEmpty(list, M, { maxMinutes: 90 })).toEqual(['Remove the time filter'])
  expect(explainEmpty([], M, {})[0]).toMatch(/empty/)
})
