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
import { studioVisible } from '../../supabase/functions/_shared/studio'
import { fetchWeather, loadCached, saveCached, weatherView, type Weather, type WeatherView } from '../adapters/weather'

export type Screen = 'home' | 'watch' | 'us' | 'ideas' | 'apps' | 'settings' | 'studio'
export type Overlay = null | 'quick' | 'morning' | 'bedtime' | 'pairing' | 'ambient'

export interface AppState {
  snap: Snapshot; tz: string; now: Date; mode: Mode; manualMode: Mode | null; setManualMode(m: Mode | null): void
  guest: boolean; setGuest(g: boolean): void
  screen: Screen; go(s: Screen): void; studioOn: boolean
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
    // ?studio=1 previews Studio at any hour
    if (q.has('studio')) base.studio.settings.window = { days: [1, 2, 3, 4, 5, 6, 7], start: 0, end: 1439 }
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
  const bootAt = useRef(lastInput.current) // unchanged until the first key press
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
    addEventListener('keydown', bump, true); addEventListener('mousemove', bump) // capture: runs even when the photo frame swallows the key
    const id = setInterval(() => setNow(new Date()), 15_000)
    return () => { removeEventListener('keydown', bump, true); removeEventListener('mousemove', bump); clearInterval(id) }
  }, [])
  useEffect(() => { // scheduled change only when idle on Our Home
    const scheduled = resolveMode(now, tz, windows)
    if (shouldApplyScheduledMode(applied, scheduled, { screen, ritualActive: overlay === 'morning' || overlay === 'bedtime', idleMs: Date.now() - lastInput.current })) setApplied(scheduled)
  }, [now, tz, windows, applied, screen, overlay])
  // Studio: only on work days in the work window, never for guests. It becomes the start screen once, when the app
  // opens inside the window; it never takes the screen mid-session, and leaves only after a minute without input.
  const studioOn = studioVisible(snap.studio.settings, now, tz, guest)
  const startedStudio = useRef(false)
  useEffect(() => { // "when the app opens": no key pressed yet and within 2 min of launch (a cached snapshot may arrive first)
    if (startedStudio.current || !studioOn) return
    startedStudio.current = true
    if (screen === 'home' && lastInput.current === bootAt.current && Date.now() - bootAt.current < 120_000) setScreen('studio')
  }, [studioOn, screen])
  useEffect(() => { if (screen === 'studio' && !studioOn && (guest || Date.now() - lastInput.current >= 60_000)) setScreen('home') }, [now, screen, studioOn, guest])
  useEffect(() => { // photo frame after N idle minutes on Our Home (0 = never)
    const n = prefs.ambientAfterMin
    if (n > 0 && overlay === null && screen === 'home' && Date.now() - lastInput.current >= n * 60_000) setOverlay('ambient')
  }, [now, prefs.ambientAfterMin, overlay, screen])

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
    snap, tz, now, mode, manualMode, setManualMode, guest, setGuest, screen, go: setScreen, studioOn, overlay, setOverlay,
    platform, ctrl, timerState, refreshTimer, toggleTask, weather: isLive ? liveWeather : snap.household.city ? weatherView({ ...fixtureWeather, fetchedAt: now.getTime() }, now.getTime(), false) : null, live: isLive ? live : null, launch, toast, images: isLive ? live.images : {},
  }
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export const personName = (s: Snapshot, id: string) => (id === 'both' ? 'Both' : s.household.people.find((p) => p.id === id)?.name ?? '')
