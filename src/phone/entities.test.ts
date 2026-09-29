import { expect, test } from 'vitest'
import { ENTITIES, missingRequired, toPayload } from './entities'

test('blank runtime stays unknown (null), not 0', () => {
  const p = toPayload(ENTITIES.watch_entries, { title: 'x', type: 'movie', runtime_min: '', watched: false })
  expect(p.runtime_min).toBeNull()
  expect(toPayload(ENTITIES.watch_entries, { runtime_min: '96' }).runtime_min).toBe(96)
})
test('checkbox coerces, blank date is null, datetime is ISO', () => {
  expect(toPayload(ENTITIES.events, { title: 'a', all_day: undefined, starts_at: '2026-10-01T20:00' }).all_day).toBe(false)
  expect(toPayload(ENTITIES.dreams, { title: 'a', target_date: '' }).target_date).toBeNull()
  expect(String(toPayload(ENTITIES.events, { starts_at: '2026-10-01T20:00' }).starts_at)).toMatch(/Z$/)
})
test('required fields reported by label', () => {
  expect(missingRequired(ENTITIES.events, { title: ' ' })).toEqual(['What', 'When'])
  expect(missingRequired(ENTITIES.notes, { body: 'hi' })).toEqual([])
})
