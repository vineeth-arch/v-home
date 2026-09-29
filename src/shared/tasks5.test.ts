import { expect, test } from 'vitest'
import { BUNDLED, pickDaily, type Reflection } from './reflections'
import { ideaToDream, ideaToTask } from './convert'
import { inWeek, mondayOf } from './week'

const custom = (id: string, favorite = false): Reflection => ({ id, slot: 'morning', text: id, favorite })

test('custom reflections join the pool; hidden ones are skipped', () => {
  const only = BUNDLED.filter((r) => r.slot === 'morning').map((r) => r.id)
  const p = pickDaily('h', '2026-10-01', 'morning', only, [custom('mine')])!
  expect(p.id).toBe('mine')
  expect(pickDaily('h', '2026-10-01', 'morning', [...only, 'mine'], [custom('mine')])).toBeNull()
})
test('favourites are drawn about twice as often', () => {
  const fav = custom('fav', true)
  let hits = 0
  for (let d = 1; d <= 300; d++) { const day = `2027-01-${String((d % 28) + 1).padStart(2, '0')}-${d}`; if (pickDaily(`h${d}`, day, 'morning', [], [fav])!.id === 'fav') hits++ }
  expect(hits).toBeGreaterThan(300 * (2 / 22) * 0.5) // base rate is 1/21 for a normal item; favourite ~2/22
  expect(hits).toBeLessThan(300 * 0.25)
})
test('"Next" changes the pick and is not sticky at offset 0', () => {
  const a = pickDaily('h', '2026-10-01', 'evening', [], [], 0)!
  const b = pickDaily('h', '2026-10-01', 'evening', [], [], 1)!
  expect(b.id).not.toBe(a.id)
  expect(pickDaily('h', '2026-10-01', 'evening', [], [], 0)!.id).toBe(a.id)
})
test('idea conversion trims and keeps the note as the dream reason', () => {
  const i = { title: '  Paint hallway ', note: ' warm sand ' }
  expect(ideaToTask(i)).toEqual({ title: 'Paint hallway', kind: 'task', owner: 'both', done: false })
  expect(ideaToDream(i)).toMatchObject({ title: 'Paint hallway', why: 'warm sand' })
})
test('mondayOf, including across a year boundary and on Sunday', () => {
  expect(mondayOf('2026-09-30')).toBe('2026-09-28')   // Wednesday
  expect(mondayOf('2026-09-28')).toBe('2026-09-28')   // Monday itself
  expect(mondayOf('2026-10-04')).toBe('2026-09-28')   // Sunday belongs to the week before
  expect(mondayOf('2027-01-01')).toBe('2026-12-28')   // Friday, previous year
  expect(inWeek('2026-10-02', '2026-09-28')).toBe(true); expect(inWeek('2026-10-05', '2026-09-28')).toBe(false)
})
