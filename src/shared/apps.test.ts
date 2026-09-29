import { expect, test } from 'vitest'
import { allApps, isValidAppId, MAX_CUSTOM_APPS, sanitizeCustomApps } from './apps'

test('app id validation', () => {
  expect(['netflix', 'com.webos.app.hdmi1', 'youtube.leanback.v4'].every(isValidAppId)).toBe(true)
  expect(['', 'a', 'has space', 'semi;colon', "x'y", 5, null].some(isValidAppId)).toBe(false)
})
test('sanitize drops malformed, blank-label, duplicate and non-array input', () => {
  const out = sanitizeCustomApps([{ id: 'in.startv.hotstar', label: ' JioHotstar ' }, { id: 'bad id', label: 'X' }, { id: 'ok.id', label: '' }, { id: 'in.startv.hotstar', label: 'Dup' }, null, 3])
  expect(out).toEqual([{ id: 'in.startv.hotstar', label: 'JioHotstar', verified: false }])
  expect(sanitizeCustomApps('nope')).toEqual([]); expect(sanitizeCustomApps(undefined)).toEqual([])
})
test('capped at 20', () => {
  const many = Array.from({ length: 30 }, (_, i) => ({ id: `app.${i}`, label: `A${i}` }))
  expect(sanitizeCustomApps(many).length).toBe(MAX_CUSTOM_APPS)
})
test('allApps lists candidates then custom, without duplicate ids', () => {
  const list = allApps([{ id: 'netflix', label: 'Dup', verified: false }, { id: 'my.app', label: 'Mine', verified: false }])
  expect(list.filter((a) => a.id === 'netflix').length).toBe(1)
  expect(list[list.length - 1].id).toBe('my.app')
})
