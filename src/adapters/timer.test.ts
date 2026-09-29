import { expect, test } from 'vitest'
import { HandoffTimer, LunaTimer, MockTimer, TimerController, parseStatus, validMinutes } from './timer'
import type { LunaResult, Platform } from './platform'

const fake = (reply: LunaResult): Platform => ({ simulated: true, call: async () => reply, launchApp: async () => reply })

test('parseStatus covers none / stale / active', () => {
  expect(parseStatus({ returnValue: true, scheduled: false })).toEqual({ scheduled: false })
  expect(parseStatus({ scheduled: false, stale: true, shutdownAt: 1 })).toEqual({ scheduled: false, stale: true })
  expect(parseStatus({ scheduled: true, minutes: 30, shutdownAt: 99, remainingMs: 5 })).toEqual({ scheduled: true, shutdownAt: 99, minutes: 30 })
})
test('minutes validated 1..720 whole', () => {
  expect([0, 721, 1.5, 1, 720].map(validMinutes)).toEqual([false, false, false, true, true])
})
test('luna timeout -> unknown, service error -> failed', async () => {
  expect(await new LunaTimer(fake({ unknown: true })).status()).toEqual({ kind: 'unknown' })
  expect(await new LunaTimer(fake({ ok: false, error: 'denied' })).cancel()).toEqual({ kind: 'failed', error: 'denied' })
})
test('handoff never confirms and has no status', async () => {
  const t = new HandoffTimer(fake({ ok: true, data: {} }))
  expect(await t.schedule(30)).toEqual({ kind: 'handoff' })
  expect(await t.status()).toEqual({ kind: 'unavailable' })
  expect(await t.schedule(0)).toMatchObject({ kind: 'failed' })
})
test('after unknown, mutation blocked until status confirms', async () => {
  let ok = false
  const a = new MockTimer()
  a.schedule = async () => ({ kind: 'unknown' })
  a.status = async () => (ok ? { kind: 'confirmed', state: { scheduled: false } } : { kind: 'unknown' })
  const c = new TimerController(a)
  expect((await c.mutate((x) => x.schedule(30))).kind).toBe('unknown')
  expect((await c.mutate((x) => x.cancel())).kind).toBe('blocked')
  ok = true
  expect((await c.mutate((x) => x.cancel())).kind).toBe('confirmed')
})
test('mock countdown derives from deadline', async () => {
  let now = 0
  const m = new MockTimer(() => now)
  await m.schedule(1)
  expect(await m.status()).toMatchObject({ state: { scheduled: true, shutdownAt: 60000 } })
  now = 61000
  expect(await m.status()).toMatchObject({ state: { scheduled: false } })
})
