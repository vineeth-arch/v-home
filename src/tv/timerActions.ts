import { useState } from 'react'
import { useApp } from './state'
import { fmtTime } from './ui'
import type { TimerAdapter, TimerResult } from '../adapters/timer'

/** Runs a timer mutation and turns the outcome into an honest message. Never claims success it didn't confirm. */
export function useTimerActions() {
  const { ctrl, refreshTimer, tz } = useApp()
  const [msg, setMsg] = useState<{ text: string; warn?: boolean } | null>(null)
  const run = async (fn: (a: TimerAdapter) => Promise<TimerResult>) => {
    setMsg({ text: 'Working…' })
    const r = await ctrl.mutate(fn)
    switch (r.kind) {
      case 'confirmed': setMsg({ text: r.state.scheduled ? `TV will turn off at ${fmtTime(r.state.shutdownAt, tz)}` : 'No timer set' }); break
      case 'handoff': setMsg({ text: 'Sent to V/TV Sleep. It confirms here when it returns.', warn: true }); break
      case 'failed': setMsg({ text: `Could not do that: ${r.error}`, warn: true }); break
      case 'unknown': setMsg({ text: 'No confirmation received. Checking the timer…', warn: true }); break
      case 'blocked': setMsg({ text: 'Still checking the timer. Try again in a moment.', warn: true }); break
    }
    await refreshTimer()
  }
  return { msg, run, verified: ctrl.verified }
}
