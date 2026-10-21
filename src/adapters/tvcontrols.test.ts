import { expect, test } from 'vitest'
import { classify, parsePictureMode, parseVolume, probePicture, probeVolume, PICTURE_MODES } from './tvcontrols'
import type { Platform } from './platform'

const fake = (reply: Awaited<ReturnType<Platform['call']>>): Platform => ({ simulated: true, call: async () => reply, launchApp: async () => reply, subscribe: () => () => {} })

test('classify: ok supported, timeout unverified, refusal denied, other errors unavailable', () => {
  expect(classify({ ok: true, data: {} })).toBe('supported')
  expect(classify({ unknown: true })).toBe('unverified')
  expect(classify({ ok: false, error: 'Denied method call "getVolume" for category "/master"' })).toBe('denied')
  expect(classify({ ok: false, error: 'Service does not exist' })).toBe('unavailable')
})
test('volume parsing handles both response shapes and junk', () => {
  expect(parseVolume({ volumeStatus: { volume: 17, muted: false } })).toEqual({ volume: 17, muted: false })
  expect(parseVolume({ volume: 9.4, mute: true })).toEqual({ volume: 9, muted: true })
  expect(parseVolume({ volume: 'loud' })).toEqual({ volume: null, muted: null })
  expect(parseVolume({})).toEqual({ volume: null, muted: null })
})
test('picture mode parsing', () => {
  expect(parsePictureMode({ settings: { pictureMode: 'cinema' } })).toBe('cinema')
  expect(parsePictureMode({ pictureMode: 'game' })).toBe('game')
  expect(parsePictureMode({ settings: {} })).toBeNull()
  expect(PICTURE_MODES).toContain('cinema')
})
test('probes report what the TV says and never invent values', async () => {
  expect(await probeVolume(fake({ ok: false, error: 'denied method' }))).toEqual({ cap: 'denied', volume: null, muted: null })
  expect(await probeVolume(fake({ ok: true, data: { volumeStatus: { volume: 12, muted: true } } }))).toEqual({ cap: 'supported', volume: 12, muted: true })
  expect(await probePicture(fake({ unknown: true }))).toEqual({ cap: 'unverified', mode: null })
})
