import { expect, test } from 'vitest'
import { evictOldest } from './imageCache'

test('keeps everything at or under the limit', () => {
  expect(evictOldest([{ path: 'a', at: 1 }, { path: 'b', at: 2 }], 2)).toEqual([])
})
test('drops the oldest entries first', () => {
  const e = [{ path: 'new', at: 9 }, { path: 'old', at: 1 }, { path: 'mid', at: 5 }]
  expect(evictOldest(e, 2)).toEqual(['old'])
  expect(evictOldest(e, 1)).toEqual(['old', 'mid'])
})
test('default limit is 40', () => {
  const e = Array.from({ length: 43 }, (_, i) => ({ path: `p${i}`, at: i }))
  expect(evictOldest(e)).toEqual(['p0', 'p1', 'p2'])
})
