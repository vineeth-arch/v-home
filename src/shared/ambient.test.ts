import { describe, expect, it } from 'vitest'
import { ambientQueue, onThisDay } from './ambient'

describe('ambient', () => {
  it('on this day: same month/day in an earlier year only', () => {
    expect(onThisDay('2024-09-30', '2026-09-30')).toBe(2)
    expect(onThisDay('2026-09-30', '2026-09-30')).toBeUndefined()
    expect(onThisDay('2025-09-29', '2026-09-30')).toBeUndefined()
    expect(onThisDay(undefined, '2026-09-30')).toBeUndefined()
  })
  it('Feb 29 photos show on Feb 28 in non-leap years, and on Feb 29 in leap years', () => {
    expect(onThisDay('2024-02-29', '2025-02-28')).toBe(1)
    expect(onThisDay('2024-02-29', '2028-02-28')).toBeUndefined()
    expect(onThisDay('2024-02-29', '2028-02-29')).toBe(4)
  })
  it('puts on-this-day first, then least recently shown; drops duplicates', () => {
    const q = ambientQueue([{ path: 'a' }, { path: 'b' }, { path: 'c', takenOn: '2025-09-30' }, { path: 'a' }], '2026-09-30', new Map([['a', 5], ['b', 1]]))
    expect(q.map((p) => p.path)).toEqual(['c', 'b', 'a'])
    expect(q[0].yearsAgo).toBe(1)
  })
  it('empty input', () => expect(ambientQueue([], '2026-09-30')).toEqual([]))
})
