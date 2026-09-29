import { expect, test } from 'vitest'
import { appForService, launchFailure } from './launch'

test('failure messages are specific; success is null', () => {
  expect(launchFailure({ ok: true, data: {} }, 'Netflix')).toBeNull()
  expect(launchFailure({ ok: false, error: 'x' }, 'Netflix')).toBe("Couldn't open Netflix.")
  expect(launchFailure({ unknown: true }, 'YouTube')).toMatch(/No answer .* YouTube/)
})
test('service text maps to a launcher case-insensitively, unknown maps to nothing', () => {
  expect(appForService('prime video')?.id).toBe('amazon')
  expect(appForService(' Netflix ')?.label).toBe('Netflix')
  expect(appForService('Some Small Service')).toBeUndefined()
  expect(appForService(undefined)).toBeUndefined()
})
