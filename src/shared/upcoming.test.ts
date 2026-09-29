import { expect, test } from 'vitest'
import { upcoming } from './upcoming'
import { fixtureSnapshot } from './fixtures'

test('mode selects days, caps at 3, events before tasks, evening skips tasks', () => {
  const s = fixtureSnapshot(); const now = new Date()
  expect(upcoming(s, now, 'home').length).toBeLessThanOrEqual(3)
  const m = upcoming(s, now, 'morning'); expect(m[0].kind).toBe('event')
  const e = upcoming(s, now, 'evening'); expect(e.every((x) => x.kind === 'event')).toBe(true)
  expect(e.map((x) => x.title)).toEqual(['Plumber visit'])
})
