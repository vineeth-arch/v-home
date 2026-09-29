import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { fixtureSnapshot, fixtureWeather } from '../shared/fixtures'
import { emptySnapshot, type Snapshot } from '../shared/model'
import { resolveMode, shouldApplyScheduledMode, type Mode } from '../shared/modes'
import { createPlatform, type Platform } from '../adapters/platform'
import { supabaseConfigured } from '../shared/supabase'
import { launchFailure } from '../shared/launch'
import { useLive, type Live } from './live'
import { LunaTimer, MockTimer, TimerController, type TimerState } from '../adapters/timer'
import { resolvePrefs } from '../shared/prefs'
import { fetchWeather, loadCached, saveCached, weatherView, type Weather, type WeatherView } from '../adapters/weather'

export type Screen = 'home' | 'watch' | 'us' | 'ideas' | 'apps' | 'settings'
export type Overlay = null | 'quick' | 'morning' | 'bedtime' | 'pairing'

export interface AppState {
  snap: Snapshot; tz: string; now: Date; mode: Mode; manualMode: Mode | null; setManualMode(m: Mode | null): void
  guest: boolean; setGuest(g: boolean): void
  screen: Screen; go(s: Screen): void
  overlay: Overlay; setOverlay(o: Overlay): void
  platform: Platform; ctrl: TimerController; timerState: TimerState | 'unavailable'; refreshTimer(): Promise<void>
  toggleTask(id: string): void
  weather: WeatherView | null
  live: Live | null // null = simulation (fixtures)
  launch(id: string, label: string): Promise<void>
  toast: string | null
  images: Record<string, string>
}
const Ctx = createContext<AppState | null>(null)
export const useApp = () => useContext(Ctx)!

/** 15-minute foreground refresh; keeps last good reading on failure and marks it stale. */
function useWeather(lat: number | undefined, lon: number | undefined, tz: string, now: Date): WeatherView | null {
  const [w, setW] = useState<Weather | null>(null)
  const [failed, setFailed] = useState(false)
  useEffect(() => {
    if (lat == null || lon == null) { setW(null); return }
    setW(loadCached(lat, lon))
    let stop = false
    const load = () => fetchWeather(lat, lon, tz).then((x) => { if (!stop) { setW(x); setFailed(false); saveCached(lat, lon, x) } }).catch(() => { if (!stop) setFailed(true) })
    load()
    const id = setInterval(() => { if (!document.hidden) load() }, 15 * 60_000)
    const vis = () => { if (!document.hidden) load() }
    document.addEventListener('visibilitychange', vis)
    return () => { stop = true; clearInterval(id); document.removeEventListener('visibilitychange', vis) }
  }, [lat, lon, tz])
  return weatherView(w, now.getTime(), failed)
}

export function AppProvider({ children }: { children: ReactNode }) {
  const platform = useMemo(createPlatform, [])
  const ctrl = useMemo(() => new TimerController(platform.simulated ? new MockTimer() : new LunaTimer(platform)), [platform])
  // ?empty=1 previews a brand-new household (simulation only)
  const isLive = supabaseConfigured && !new URLSearchParams(location.search).has('sim')
  const live = useLive(isLive)
  const [simSnap, setSnap] = useState<Snapshot>(() => {
    const q = new URLSearchParams(location.search)
    const base = q.has('empty') ? emptySnapshot() : fixtureSnapshot()
    // ?prefs={"showForUs":false} previews display preferences in simulation
    try { const raw = q.get('prefs'); if (raw) base.household.prefs = resolvePrefs(JSON.parse(raw), base.dreams) } catch { /* ignore bad JSON */ }
    return base
  })
  const snap = isLive ? live.snapshot ?? emptySnapshot() : simSnap
  const [now, setNow] = useState(() => new Date())
  const prefs = snap.household.prefs
  const windows = useMemo(() => ({ morning: prefs.morning, evening: prefs.evening }), [prefs.morning, prefs.evening])
  // undefined = the user hasn't chosen yet, so the household's default mode applies
  const [manualChoice, setManualChoice] = useState<Mode | null | undefined>(undefined)
  const manualMode = manualChoice === undefined ? (prefs.defaultMode === 'auto' ? null : prefs.defaultMode) : manualChoice
  const setManualMode = useCallback((m: Mode | null) => setManualChoice(m), [])
  const [applied, setApplied] = useState<Mode>(() => resolveMode(new Date(), snap.household.tz, windows))
  const [guest, setGuest] = useState(false)
  const [screen, setScreen] = useState<Screen>('home')
  const [overlay, setOverlay] = useState<Overlay>(null)
  const [timerState, setTimerState] = useState<TimerState | 'unavailable'>('unavailable')
  const lastInput = useRef(Date.now())
  const [toast, setToast] = useState<string | null>(null)
  const toastTimer = useRef<ReturnType<typeof setTimeout>>(undefined)
  const launch = useCallback(async (id: string, label: string) => {
    const m = launchFailure(await platform.launchApp(id), label)
    if (m) { setToast(m); clearTimeout(toastTimer.current); toastTimer.current = setTimeout(() => setToast(null), 4000) }
  }, [platform])

  const tz = snap.household.tz
  const liveWeather = useWeather(isLive ? snap.household.lat : undefined, isLive ? snap.household.lon : undefined, snap.household.tz, now)
  const mode = manualMode ?? applied

  useEffect(() => { document.documentElement.dataset.mode = mode }, [mode])
  useEffect(() => {
    const bump = () => { lastInput.current = Date.now() }
    addEventListener('keydown', bump); addEventListener('mousemove', bump)
    const id = setInterval(() => setNow(new Date()), 15_000)
    return () => { removeEventListener('keydown', bump); removeEventListener('mousemove', bump); clearInterval(id) }
  }, [])
  useEffect(() => { // scheduled change only when idle on Our Home
    const scheduled = resolveMode(now, tz, windows)
    if (shouldApplyScheduledMode(applied, scheduled, { screen, ritualActive: overlay === 'morning' || overlay === 'bedtime', idleMs: Date.now() - lastInput.current })) setApplied(scheduled)
  }, [now, tz, windows, applied, screen, overlay])

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

  // Live: TV may only complete a task (server-enforced). Simulation toggles locally.
  const toggleTask = useCallback((id: string) => {
    if (isLive) { if (!snap.tasks.find((t) => t.id === id)?.done) void live.completeTask(id); return }
    setSnap((s) => ({ ...s, tasks: s.tasks.map((t) => (t.id === id ? { ...t, done: !t.done } : t)) }))
  }, [isLive, live, snap.tasks])
  const value: AppState = {
    snap, tz, now, mode, manualMode, setManualMode, guest, setGuest, screen, go: setScreen, overlay, setOverlay,
    platform, ctrl, timerState, refreshTimer, toggleTask, weather: isLive ? liveWeather : snap.household.city ? weatherView({ ...fixtureWeather, fetchedAt: now.getTime() }, now.getTime(), false) : null, live: isLive ? live : null, launch, toast, images: isLive ? live.images : {},
  }
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export const personName = (s: Snapshot, id: string) => (id === 'both' ? 'Both' : s.household.people.find((p) => p.id === id)?.name ?? '')
