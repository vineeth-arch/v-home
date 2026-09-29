// Timer contract: V/TV Sleep stays the ONLY timer authority. Nothing here schedules shutdown itself.
import type { Platform } from './platform'

export type TimerState =
  | { scheduled: false; stale?: boolean }
  | { scheduled: true; shutdownAt: number; minutes: number }
export type TimerResult =
  | { kind: 'confirmed'; state: TimerState }
  | { kind: 'handoff' } // opened V/TV Sleep; outcome not observable, never show a countdown
  | { kind: 'failed'; error: string }
  | { kind: 'unknown' } // timeout: refresh status before any retry

export interface TimerAdapter {
  readonly label: string
  readonly verified: boolean // false until proven on the real TV
  status(): Promise<TimerResult | { kind: 'unavailable' }>
  schedule(minutes: number): Promise<TimerResult>
  cancel(): Promise<TimerResult>
  powerOff(): Promise<TimerResult>
}

export const validMinutes = (m: number) => Number.isInteger(m) && m >= 1 && m <= 720
export const SERVICE = 'luna://com.designinnsaeit.vtvsleep.service'
export const SLEEP_APP = 'com.designinnsaeit.vtvsleep'

/** Maps a raw service `status` reply to TimerState (shapes from LGTV handlers.js:83-92). */
export function parseStatus(d: Record<string, unknown>): TimerState {
  if (d.scheduled === true && typeof d.shutdownAt === 'number') return { scheduled: true, shutdownAt: d.shutdownAt, minutes: Number(d.minutes ?? 0) }
  return d.stale ? { scheduled: false, stale: true } : { scheduled: false }
}

export class LunaTimer implements TimerAdapter {
  readonly label = 'Direct service'
  readonly verified = false
  constructor(private p: Platform) {}
  private async run(method: string, params: object): Promise<TimerResult> {
    const r = await this.p.call(`${SERVICE}/${method}`, params)
    if ('unknown' in r) return { kind: 'unknown' }
    if (!r.ok) return { kind: 'failed', error: r.error }
    return { kind: 'confirmed', state: method === 'status' || method === 'schedule' ? parseStatus({ scheduled: method === 'schedule' ? true : r.data.scheduled, ...r.data }) : { scheduled: false } }
  }
  status() { return this.run('status', {}) }
  schedule(minutes: number) { return validMinutes(minutes) ? this.run('schedule', { minutes }) : Promise.resolve<TimerResult>({ kind: 'failed', error: 'minutes must be 1-720' }) }
  cancel() { return this.run('cancel', {}) }
  powerOff() { return this.run('powerOff', {}) }
}

/** Fallback: launch V/TV Sleep with params. Foreground is taken; result is a handoff, never confirmed. */
export class HandoffTimer implements TimerAdapter {
  readonly label = 'Opens V/TV Sleep'
  readonly verified = false
  constructor(private p: Platform) {}
  private async go(params: object): Promise<TimerResult> {
    const r = await this.p.launchApp(SLEEP_APP, params)
    if ('unknown' in r) return { kind: 'unknown' }
    return r.ok ? { kind: 'handoff' } : { kind: 'failed', error: r.error }
  }
  async status() { return { kind: 'unavailable' as const } }
  schedule(minutes: number) { return validMinutes(minutes) ? this.go({ mode: 'schedule', minutes }) : Promise.resolve<TimerResult>({ kind: 'failed', error: 'minutes must be 1-720' }) }
  cancel() { return this.go({ mode: 'cancel' }) }
  powerOff() { return this.go({ mode: 'off' }) }
}

export class MockTimer implements TimerAdapter {
  readonly label = 'Simulation'
  readonly verified = false
  private at: number | null = null
  private mins = 0
  constructor(private now: () => number = Date.now) {}
  private state(): TimerState { return this.at && this.at > this.now() ? { scheduled: true, shutdownAt: this.at, minutes: this.mins } : { scheduled: false } }
  async status(): Promise<TimerResult> { return { kind: 'confirmed', state: this.state() } }
  async schedule(minutes: number): Promise<TimerResult> {
    if (!validMinutes(minutes)) return { kind: 'failed', error: 'minutes must be 1-720' }
    this.at = this.now() + minutes * 60000; this.mins = minutes
    return { kind: 'confirmed', state: this.state() }
  }
  async cancel(): Promise<TimerResult> { this.at = null; return { kind: 'confirmed', state: this.state() } }
  async powerOff(): Promise<TimerResult> { return { kind: 'confirmed', state: { scheduled: false } } }
}

/**
 * UI-side guard: after an 'unknown' outcome, mutations are blocked until a status read confirms state.
 * Returns the message to show, never claims success.
 */
export class TimerController {
  needsRefresh = false
  constructor(private a: TimerAdapter) {}
  get verified() { return this.a.verified }
  get label() { return this.a.label }
  async refresh() {
    const r = await this.a.status()
    if (r.kind === 'confirmed') this.needsRefresh = false
    return r
  }
  async mutate(fn: (a: TimerAdapter) => Promise<TimerResult>): Promise<TimerResult | { kind: 'blocked' }> {
    if (this.needsRefresh) {
      await this.refresh()
      if (this.needsRefresh) return { kind: 'blocked' }
    }
    const r = await fn(this.a)
    if (r.kind === 'unknown') this.needsRefresh = true
    return r
  }
}
