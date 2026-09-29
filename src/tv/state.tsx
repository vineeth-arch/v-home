import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { fixtureSnapshot, fixtureWeather } from '../shared/fixtures'
import { emptySnapshot, type Snapshot } from '../shared/model'
import { DEFAULT_WINDOWS, resolveMode, shouldApplyScheduledMode, type Mode } from '../shared/modes'
import { createPlatform, type Platform } from '../adapters/platform'
import { LunaTimer, MockTimer, TimerController, type TimerState } from '../adapters/timer'

export type Screen = 'home' | 'watch' | 'us' | 'ideas' | 'settings'
export type Overlay = null | 'quick' | 'morning' | 'bedtime' | 'pairing'

export interface AppState {
  snap: Snapshot; tz: string; now: Date; mode: Mode; manualMode: Mode | null; setManualMode(m: Mode | null): void
  guest: boolean; setGuest(g: boolean): void
  screen: Screen; go(s: Screen): void
  overlay: Overlay; setOverlay(o: Overlay): void
  platform: Platform; ctrl: TimerController; timerState: TimerState | 'unavailable'; refreshTimer(): Promise<void>
  toggleTask(id: string): void
  weather: typeof fixtureWeather | null
}
const Ctx = createContext<AppState | null>(null)
export const useApp = () => useContext(Ctx)!

export function AppProvider({ children }: { children: ReactNode }) {
  const platform = useMemo(createPlatform, [])
  const ctrl = useMemo(() => new TimerController(platform.simulated ? new MockTimer() : new LunaTimer(platform)), [platform])
  // ?empty=1 previews a brand-new household (simulation only)
  const [snap, setSnap] = useState<Snapshot>(() => (new URLSearchParams(location.search).has('empty') ? emptySnapshot() : fixtureSnapshot()))
  const [now, setNow] = useState(() => new Date())
  const [manualMode, setManualMode] = useState<Mode | null>(null)
  const [applied, setApplied] = useState<Mode>(() => resolveMode(new Date(), snap.household.tz, DEFAULT_WINDOWS))
  const [guest, setGuest] = useState(false)
  const [screen, setScreen] = useState<Screen>('home')
  const [overlay, setOverlay] = useState<Overlay>(null)
  const [timerState, setTimerState] = useState<TimerState | 'unavailable'>('unavailable')
  const lastInput = useRef(Date.now())

  const tz = snap.household.tz
  const mode = manualMode ?? applied

  useEffect(() => { document.documentElement.dataset.mode = mode }, [mode])
  useEffect(() => {
    const bump = () => { lastInput.current = Date.now() }
    addEventListener('keydown', bump); addEventListener('mousemove', bump)
    const id = setInterval(() => setNow(new Date()), 15_000)
    return () => { removeEventListener('keydown', bump); removeEventListener('mousemove', bump); clearInterval(id) }
  }, [])
  useEffect(() => { // scheduled change only when idle on Our Home
    const scheduled = resolveMode(now, tz, DEFAULT_WINDOWS)
    if (shouldApplyScheduledMode(applied, scheduled, { screen, ritualActive: overlay === 'morning' || overlay === 'bedtime', idleMs: Date.now() - lastInput.current })) setApplied(scheduled)
  }, [now, tz, applied, screen, overlay])

  const refreshTimer = useCallback(async () => {
    const r = await ctrl.refresh()
    setTimerState(r.kind === 'confirmed' ? r.state : 'unavailable')
  }, [ctrl])
  useEffect(() => { // launch, resume, every 30s while visible
    refreshTimer()
    const tick = setInterval(() => { if (!document.hidden) refreshTimer() }, 30_000)
    const vis = () => { if (!document.hidden) refreshTimer() }
    document.addEventListener('visibilitychange', vis)
    return () => { clearInterval(tick); document.removeEventListener('visibilitychange', vis) }
  }, [refreshTimer])

  const toggleTask = useCallback((id: string) => setSnap((s) => ({ ...s, tasks: s.tasks.map((t) => (t.id === id ? { ...t, done: !t.done } : t)) })), [])
  const value: AppState = {
    snap, tz, now, mode, manualMode, setManualMode, guest, setGuest, screen, go: setScreen, overlay, setOverlay,
    platform, ctrl, timerState, refreshTimer, toggleTask, weather: snap.household.city ? fixtureWeather : null,
  }
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export const personName = (s: Snapshot, id: string) => (id === 'both' ? 'Both' : s.household.people.find((p) => p.id === id)?.name ?? '')
