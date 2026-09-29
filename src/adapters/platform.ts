// webOS bridge. Real = PalmServiceBridge; Mock = desktop simulation (logs calls).
export type LunaResult =
  | { ok: true; data: Record<string, unknown> }
  | { ok: false; error: string }
  | { unknown: true } // timed out: outcome unknown, caller must re-read state before retrying

export interface Platform {
  readonly simulated: boolean
  call(uri: string, params: object, timeoutMs?: number): Promise<LunaResult>
  launchApp(id: string, params?: object): Promise<LunaResult>
  /** Long-lived subscription; every response goes to onMsg. Returns cancel. */
  subscribe(uri: string, params: object, onMsg: (r: LunaResult) => void): () => void
}

declare global {
  interface Window { PalmServiceBridge?: new () => { onservicecallback: ((m: string) => void) | null; call(uri: string, p: string): void; cancel(): void }; PalmSystem?: unknown }
}

export class WebOSPlatform implements Platform {
  readonly simulated = false
  call(uri: string, params: object, timeoutMs = 8000): Promise<LunaResult> {
    return new Promise((resolve) => {
      const bridge = new window.PalmServiceBridge!()
      const timer = setTimeout(() => { bridge.cancel(); resolve({ unknown: true }) }, timeoutMs)
      bridge.onservicecallback = (msg) => {
        clearTimeout(timer)
        try {
          const data = JSON.parse(msg) as Record<string, unknown>
          resolve(data.returnValue === false ? { ok: false, error: String(data.errorText ?? 'error') } : { ok: true, data })
        } catch { resolve({ ok: false, error: 'bad response' }) }
      }
      bridge.call(uri, JSON.stringify(params))
    })
  }
  launchApp(id: string, params: object = {}) {
    return this.call('luna://com.webos.applicationManager/launch', { id, params })
  }
  subscribe(uri: string, params: object, onMsg: (r: LunaResult) => void) {
    const bridge = new window.PalmServiceBridge!()
    bridge.onservicecallback = (msg) => {
      try { const data = JSON.parse(msg) as Record<string, unknown>; onMsg(data.returnValue === false ? { ok: false, error: String(data.errorText ?? 'error') } : { ok: true, data }) }
      catch { onMsg({ ok: false, error: 'bad response' }) }
    }
    bridge.call(uri, JSON.stringify({ ...params, subscribe: true }))
    return () => bridge.cancel()
  }
}

export class MockPlatform implements Platform {
  readonly simulated = true
  calls: { uri: string; params: object }[] = []
  async call(uri: string, params: object): Promise<LunaResult> {
    this.calls.push({ uri, params })
    return { ok: true, data: { returnValue: true } }
  }
  launchApp(id: string, params: object = {}) { return this.call('launch', { id, params }) }
  subscribe(uri: string, params: object) { this.calls.push({ uri, params: { ...params, subscribe: true } }); return () => {} }
}

export const createPlatform = (): Platform => (window.PalmServiceBridge ? new WebOSPlatform() : new MockPlatform())
