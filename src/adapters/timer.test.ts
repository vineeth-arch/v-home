import { expect, test } from 'vitest'
import { FallbackTimer, HandoffTimer, LunaTimer, MockTimer, TimerController, parseReport, parseStatus, validMinutes } from './timer'
import type { LunaResult, Platform } from './platform'

const fake = (reply: LunaResult): Platform => ({ simulated: true, call: async () => reply, launchApp: async () => reply, subscribe: () => () => {} })

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

test('direct call denied by the TV -> falls back to opening V/TV Sleep, never confirms', async () => {
  const launches: unknown[] = []
  const p: Platform = { simulated: true, call: async () => ({ ok: false, error: 'denied method schedule for category "/"' }), launchApp: async (id, params) => { launches.push([id, params]); return { ok: true, data: {} } }, subscribe: () => () => {} }
  const t = new FallbackTimer(p)
  expect(await t.schedule(30)).toEqual({ kind: 'handoff' })
  expect(launches).toEqual([['com.designinnsaeit.vtvsleep', { mode: 'schedule', minutes: 30, returnTo: 'com.designinnsaeit.vhome' }]])
  expect(t.label).toBe('Opens V/TV Sleep')
  expect(await t.status()).toEqual({ kind: 'unavailable' })
  expect(await t.cancel()).toEqual({ kind: 'handoff' })
})
test('direct call that works stays direct; other failures are not turned into a handoff', async () => {
  const ok = new FallbackTimer(fake({ ok: true, data: { scheduled: true, shutdownAt: 5, minutes: 30 } }))
  expect(await ok.schedule(30)).toMatchObject({ kind: 'confirmed' })
  const bad = new FallbackTimer(fake({ ok: false, error: 'service crashed' }))
  expect(await bad.schedule(30)).toEqual({ kind: 'failed', error: 'service crashed' })
  expect(await new FallbackTimer(fake({ unknown: true })).schedule(30)).toEqual({ kind: 'unknown' })
})

test('after a denied direct call, status comes only from what V/TV Sleep reported back', async () => {
  localStorage.clear()
  let now = 1000
  const denied: Platform = { simulated: true, call: async () => ({ ok: false, error: 'denied method status for category "/"' }), launchApp: async () => ({ ok: true, data: {} }), subscribe: () => () => {} }
  const t = new FallbackTimer(denied, () => now)
  expect(await t.status()).toEqual({ kind: 'unavailable' }) // nothing reported yet: no invented countdown
  expect(t.ingest(parseReport({ op: 'schedule', minutes: 15, shutdownAt: 901000, at: 500 }))).not.toBeNull()
  expect(await t.status()).toEqual({ kind: 'confirmed', state: { scheduled: true, shutdownAt: 901000, minutes: 15 } })
  now = 902000
  expect(await t.status()).toEqual({ kind: 'unavailable' }) // past its time: unknown, not "no timer"
  expect(t.ingest(parseReport({ op: 'cancel', at: 100 }))).toBeNull() // older than what we have: ignored
  expect(t.ingest(parseReport({ op: 'cancel', at: 600 }))).not.toBeNull()
  expect(await t.status()).toEqual({ kind: 'confirmed', state: { scheduled: false } })
  expect(parseReport({ op: 'schedule', at: 1 })).toBeNull()
  expect(parseReport('x')).toBeNull()
})

test('a status report from V/TV Sleep corrects the timer view; check() asks V/TV Sleep with returnTo', async () => {
  localStorage.clear()
  const launches: unknown[] = []
  const p: Platform = { simulated: true, call: async () => ({ ok: false, error: 'denied method status for category "/"' }), launchApp: async (id, params) => { launches.push([id, params]); return { ok: true, data: {} } }, subscribe: () => () => {} }
  let now = 1000
  const t = new FallbackTimer(p, () => now)
  t.ingest(parseReport({ op: 'schedule', minutes: 60, shutdownAt: 3_600_000, at: 100 }))
  expect(t.believesRunning).toBe(true)
  await t.check()
  expect(launches).toEqual([['com.designinnsaeit.vtvsleep', { mode: 'status', returnTo: 'com.designinnsaeit.vhome' }]])
  t.ingest(parseReport({ op: 'status', scheduled: false, at: 200 })) // it was cancelled elsewhere
  expect(t.believesRunning).toBe(false)
  expect(await t.status()).toEqual({ kind: 'confirmed', state: { scheduled: false } })
  t.ingest(parseReport({ op: 'status', scheduled: true, minutes: 30, shutdownAt: 1_900_000, at: 300 }))
  expect(await t.status()).toEqual({ kind: 'confirmed', state: { scheduled: true, shutdownAt: 1_900_000, minutes: 30 } })
  expect(parseReport({ op: 'status', at: 1 })).toBeNull()
})
