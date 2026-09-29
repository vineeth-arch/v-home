import type { Snapshot } from './model'

export class RevokedError extends Error { constructor() { super('display revoked'); this.name = 'RevokedError' } }

export interface SyncDeps {
  fetchVersion(): Promise<number>          // throws RevokedError when the version row is not visible
  fetchSnapshot(): Promise<Snapshot>
  onSnapshot(s: Snapshot): void
  onOffline(err: unknown): void            // keep showing cached content
  onRevoked(): void                        // clear cache, show pairing
  pollMs?: number
  debounceMs?: number
}

/**
 * Cloud is the source of truth. We refetch the whole snapshot whenever the household version changes
 * (realtime nudge, 30s poll, resume, reconnect). Row-level realtime is never trusted: RLS hides removals.
 */
export class SyncEngine {
  private last = -1
  private poll?: ReturnType<typeof setInterval>
  private deb?: ReturnType<typeof setTimeout>
  private running = false
  constructor(private d: SyncDeps) {}

  start() {
    if (this.running) return
    this.running = true
    void this.refresh(true)
    this.poll = setInterval(() => { if (typeof document === 'undefined' || !document.hidden) void this.refresh() }, this.d.pollMs ?? 30_000)
  }
  stop() { this.running = false; clearInterval(this.poll); clearTimeout(this.deb) }

  /** Realtime event, visibility change, or online event. Debounced. */
  nudge() {
    clearTimeout(this.deb)
    this.deb = setTimeout(() => void this.refresh(), this.d.debounceMs ?? 300)
  }

  async refresh(force = false) {
    if (!this.running) return
    try {
      const v = await this.d.fetchVersion()
      if (!force && v === this.last) return
      const s = await this.d.fetchSnapshot()
      if (!this.running) return
      this.last = v
      this.d.onSnapshot(s)
    } catch (e) {
      if (e instanceof RevokedError) { this.stop(); this.d.onRevoked() } else this.d.onOffline(e)
    }
  }
}
