import { expect, test } from 'vitest'
import { backoffDelay, shouldIssueCode } from './pairing'

test('code is issued once, then kept until near expiry', () => {
  expect(shouldIssueCode(null, 0, 1000)).toBe(true)
  expect(shouldIssueCode('ABC123', 1000, 1000 + 3000)).toBe(false) // the old bug: re-issued every 3 s
  expect(shouldIssueCode('ABC123', 0, 8 * 60_000)).toBe(false)
  expect(shouldIssueCode('ABC123', 0, 9 * 60_000 + 1)).toBe(true)
})
test('boot backoff grows then caps at 60s', () => {
  expect([0, 1, 2, 3, 10].map(backoffDelay)).toEqual([5000, 15000, 30000, 60000, 60000])
})
