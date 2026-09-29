import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { toSnapshot, type Rows } from './snapshot'
import { RevokedError, SyncEngine } from './sync'
import { localStorageStore, memoryStore, pickStore } from './cache'
import { fixtureSnapshot } from './fixtures'

const rows = (): Rows => ({
  household: { name: 'Home', timezone: 'Asia/Kolkata', settings: { city: 'Pune', lat: 18.5, lon: 73.8 } },
  members: [{ user_id: 'u1', role: 'member', display_name: 'A' }, { user_id: 'tv', role: 'display', display_name: 'TV' }],
  events: [{ id: 'e', title: 'Dinner', starts_at: '2026-10-01T20:00:00Z', all_day: false }],
  tasks: [{ id: 't', title: 'Plants', owner: 'u1', kind: 'task', done: false }],
  notes: [], dreams: [{ id: 'd', title: 'Sea', why: '', affirmation: '', next_step: 'Look', target_date: null, art: 'nonsense' }], ideas: [],
  watch_entries: [{ id: 'w', title: 'Film', type: 'movie', runtime_min: null, service: null, mood: null, summary: null, watched: false, providers: {}, providers_updated_at: null }],
  watch_prefs: [{ entry_id: 'w', user_id: 'u1', pref: 'want' }],
})

test('toSnapshot maps rows, excludes displays from people, tolerates bad art and missing settings', () => {
  const s = toSnapshot(rows(), 1)
  expect(s.household.people).toEqual([{ id: 'u1', name: 'A' }])
  expect(s.household).toMatchObject({ city: 'Pune', lat: 18.5, pinnedApps: [] })
  expect(s.dreams[0].art).toBe('sun')
  expect(s.watch[0].prefs).toEqual({ u1: 'want' })
  expect(s.watch[0].entry.runtimeMin).toBeNull()
  expect(toSnapshot({ ...rows(), household: { name: 'x', timezone: 'UTC', settings: {} } }).household.city).toBeUndefined()
})

beforeEach(() => { vi.useFakeTimers() })
afterEach(() => { vi.useRealTimers() })

const engine = (over: Partial<ConstructorParameters<typeof SyncEngine>[0]> = {}) => {
  const log: string[] = []
  let version = 1
  const e = new SyncEngine({
    fetchVersion: async () => version, fetchSnapshot: async () => fixtureSnapshot(),
    onSnapshot: () => log.push('snap'), onOffline: () => log.push('offline'), onRevoked: () => log.push('revoked'), ...over,
  })
  return { e, log, bump: () => { version++ } }
}

test('sync: initial fetch, unchanged version skips, change refetches', async () => {
  const { e, log, bump } = engine()
  e.start(); await vi.advanceTimersByTimeAsync(0)
  expect(log).toEqual(['snap'])
  await vi.advanceTimersByTimeAsync(30_000); expect(log).toEqual(['snap'])
  bump(); await vi.advanceTimersByTimeAsync(30_000); expect(log).toEqual(['snap', 'snap'])
  e.stop()
})
test('sync: nudges are debounced into one refetch', async () => {
  const { e, log, bump } = engine()
  e.start(); await vi.advanceTimersByTimeAsync(0); log.length = 0; bump()
  e.nudge(); e.nudge(); e.nudge(); await vi.advanceTimersByTimeAsync(400)
  expect(log).toEqual(['snap']); e.stop()
})
test('sync: network failure keeps cache (offline), revoked stops polling and clears', async () => {
  let mode: 'ok' | 'net' | 'revoked' = 'net'
  const { e, log } = engine({ fetchVersion: async () => { if (mode === 'net') throw new Error('net'); if (mode === 'revoked') throw new RevokedError(); return 1 } })
  e.start(); await vi.advanceTimersByTimeAsync(0); expect(log).toEqual(['offline'])
  mode = 'revoked'; await vi.advanceTimersByTimeAsync(30_000); expect(log).toEqual(['offline', 'revoked'])
  await vi.advanceTimersByTimeAsync(90_000); expect(log).toEqual(['offline', 'revoked'])
})

test('cache: memory and localStorage round trip and clear; pickStore falls through a failing backend', async () => {
  const snap = fixtureSnapshot()
  const m = memoryStore(); await m.set(snap); expect((await m.get())?.household.name).toBe('Our Home'); await m.clear(); expect(await m.get()).toBeNull()
  const l = localStorageStore(); await l.set(snap); expect((await l.get())?.tasks.length).toBe(5); await l.clear(); expect(await l.get()).toBeNull()
  const broken = () => ({ ...memoryStore(), name: 'broken', get: async () => { throw new Error('no idb') } })
  expect((await pickStore([broken, localStorageStore])).name).toBe('localStorage')
})
