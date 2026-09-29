import { expect, test } from 'vitest'
import { DEFAULT_PREFS, fromHHMM, heroDream, resolvePrefs, toHHMM, windowsOverlap } from './prefs'
import { resolveMode } from './modes'

const dreams = [{ id: 'a' }, { id: 'b' }]
test('missing or junk settings give defaults, never throw', () => {
  expect(resolvePrefs(undefined, dreams)).toEqual(DEFAULT_PREFS)
  expect(resolvePrefs('junk', dreams)).toEqual(DEFAULT_PREFS)
  expect(resolvePrefs({ morning: 'x', evening: [1, 2, 3], hero: 7, defaultMode: 'night' }, dreams)).toEqual(DEFAULT_PREFS)
})
test('windows are clamped; equal start/end falls back', () => {
  expect(resolvePrefs({ morning: [-50, 5000] }, dreams).morning).toEqual([0, 1439])
  expect(resolvePrefs({ morning: [400, 400] }, dreams).morning).toEqual([300, 660])
})
test('featured dream the display cannot see falls back; hero can be reflection-only', () => {
  expect(resolvePrefs({ featuredDreamId: 'gone' }, dreams).featuredDreamId).toBeNull()
  expect(heroDream(resolvePrefs({ featuredDreamId: 'b' }, dreams), dreams)?.id).toBe('b')
  expect(heroDream(resolvePrefs({ featuredDreamId: 'gone' }, dreams), dreams)?.id).toBe('a')
  expect(heroDream(resolvePrefs({ hero: 'reflection' }, dreams), dreams)).toBeUndefined()
  expect(heroDream(DEFAULT_PREFS, [])).toBeUndefined()
})
test('cards default on, and only an explicit false hides them', () => {
  expect(resolvePrefs({ showToday: false }, dreams)).toMatchObject({ showToday: false, showForUs: true })
})
test('overlap detection incl. wrap past midnight; defaults do not overlap', () => {
  expect(windowsOverlap(DEFAULT_PREFS.morning, DEFAULT_PREFS.evening)).toBe(false)
  expect(windowsOverlap([300, 700], [600, 300])).toBe(true)
  expect(windowsOverlap([1200, 200], [100, 400])).toBe(true)
})
test('HH:MM helpers round trip and reject bad input', () => {
  expect(toHHMM(305)).toBe('05:05'); expect(fromHHMM('18:00')).toBe(1080); expect(fromHHMM('24:00')).toBeNull(); expect(fromHHMM('7:5')).toBeNull()
})
test('custom windows drive the mode, including an evening that wraps midnight', () => {
  const p = resolvePrefs({ morning: [360, 600], evening: [1200, 240] }, dreams)
  const w = { morning: p.morning, evening: p.evening }
  const at = (h: string) => new Date(`2026-09-29T${h}:00+05:30`)
  expect([resolveMode(at('05:59'), 'Asia/Kolkata', w), resolveMode(at('06:00'), 'Asia/Kolkata', w), resolveMode(at('10:00'), 'Asia/Kolkata', w), resolveMode(at('20:00'), 'Asia/Kolkata', w), resolveMode(at('03:59'), 'Asia/Kolkata', w), resolveMode(at('04:00'), 'Asia/Kolkata', w)])
    .toEqual(['home', 'morning', 'home', 'evening', 'evening', 'home'])
})
