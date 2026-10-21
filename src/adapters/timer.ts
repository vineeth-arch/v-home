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

export const VHOME_APP = 'com.designinnsaeit.vhome'

/** What V/TV Sleep tells V/HOME after it handled a request (launch params `{timer: ...}`). It comes from the timer authority itself. */
export interface TimerReport { op: 'schedule' | 'cancel' | 'error'; minutes?: number; shutdownAt?: number; error?: string; at: number }
export function parseReport(raw: unknown): TimerReport | null {
  const t = raw && typeof raw === 'object' ? (raw as Record<string, unknown>) : null
  if (!t || typeof t.at !== 'number') return null
  if (t.op === 'cancel') return { op: 'cancel', at: t.at }
  if (t.op === 'error') return { op: 'error', error: typeof t.error === 'string' ? t.error.slice(0, 120) : 'error', at: t.at }
  if (t.op === 'schedule' && typeof t.shutdownAt === 'number' && typeof t.minutes === 'number') return { op: 'schedule', minutes: t.minutes, shutdownAt: t.shutdownAt, at: t.at }
  return null
}
const REPORT_KEY = 'vhomeLauncher.timerReport'

/** Fallback: launch V/TV Sleep with params. It sets the timer, shows its own confirmation, then reopens V/HOME with the
 *  result (`returnTo`). The launch itself is only a handoff, never a confirmation. */
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
  schedule(minutes: number) { return validMinutes(minutes) ? this.go({ mode: 'schedule', minutes, returnTo: VHOME_APP }) : Promise.resolve<TimerResult>({ kind: 'failed', error: 'minutes must be 1-720' }) }
  cancel() { return this.go({ mode: 'cancel', returnTo: VHOME_APP }) }
  powerOff() { return this.go({ mode: 'off' }) }
}

const DENIED = /denied|not allowed|permission|security|category/i

/** Direct service first. If the TV refuses the cross-app call (seen on the LG 43NU885BPLA: 'denied method schedule
 *  for category /'), every later request opens V/TV Sleep with the request instead. A handoff is never a confirmation. */
export class FallbackTimer implements TimerAdapter {
  readonly verified = false
  private denied = false
  private direct: LunaTimer
  private handoff: HandoffTimer
  private report: TimerReport | null = null
  constructor(p: Platform, private now: () => number = Date.now) {
    this.direct = new LunaTimer(p); this.handoff = new HandoffTimer(p)
    try { this.report = parseReport(JSON.parse(localStorage.getItem(REPORT_KEY) ?? 'null')) } catch { this.report = null }
  }
  /** V/TV Sleep's result for the last request, delivered when it reopens V/HOME. Newest wins; stale ones are ignored. */
  ingest(r: TimerReport | null): TimerReport | null {
    if (!r || (this.report && r.at <= this.report.at)) return null
    this.report = r
    try { localStorage.setItem(REPORT_KEY, JSON.stringify(r)) } catch { /* storage unavailable */ }
    return r
  }
  get label() { return this.denied ? this.handoff.label : this.direct.label }
  private isDenied(r: TimerResult) { return r.kind === 'failed' && DENIED.test(r.error) }
  private async via(fn: (a: TimerAdapter) => Promise<TimerResult>): Promise<TimerResult> {
    if (!this.denied) {
      const r = await fn(this.direct)
      if (!this.isDenied(r)) return r
      this.denied = true
    }
    return fn(this.handoff)
  }
  /** Direct status is denied too, so the last confirmation V/TV Sleep sent back is all we know (it can be stale if the timer is changed elsewhere). */
  private fromReport() {
    const r = this.report
    if (r?.op === 'schedule' && r.shutdownAt! > this.now()) return { kind: 'confirmed' as const, state: { scheduled: true as const, shutdownAt: r.shutdownAt!, minutes: r.minutes! } }
    if (r?.op === 'cancel') return { kind: 'confirmed' as const, state: { scheduled: false as const } }
    return { kind: 'unavailable' as const }
  }
  async status() {
    if (this.denied) return this.fromReport()
    const r = await this.direct.status()
    if (this.isDenied(r)) { this.denied = true; return this.fromReport() }
    return r
  }
  schedule(minutes: number) { return this.via((a) => a.schedule(minutes)) }
  cancel() { return this.via((a) => a.cancel()) }
  powerOff() { return this.via((a) => a.powerOff()) }
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
