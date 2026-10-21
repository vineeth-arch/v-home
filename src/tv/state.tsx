import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { fixtureSnapshot, fixtureWeather } from '../shared/fixtures'
import { appsOf, emptySnapshot, type Snapshot } from '../shared/model'
import { parseLaunchPoints } from '../shared/apps'
import { resolveMode, shouldApplyScheduledMode, type Mode } from '../shared/modes'
import { createPlatform, type Platform } from '../adapters/platform'
import { supabaseConfigured } from '../shared/supabase'
import { launchFailure } from '../shared/launch'
import { EXIT_EVENT } from './FocusProvider'
import { useLive, type Live } from './live'
import { FallbackTimer, MockTimer, parseReport, TimerController, type TimerState } from '../adapters/timer'
import { resolvePrefs } from '../shared/prefs'
import { studioVisible } from '../../supabase/functions/_shared/studio'
import { bundledCatalog, isSystemApp, withRemembered, type CatalogEntry, type Capability } from '../shared/catalog'
import { loadPrefs, savePrefs, MAX_FAVORITES, type LauncherPrefs } from '../shared/launcherPrefs'
import { fetchWeather, loadCached, saveCached, weatherView, type Weather, type WeatherView } from '../adapters/weather'

export type Screen = 'launcher' | 'home' | 'watch' | 'us' | 'ideas' | 'settings' | 'studio'
export type Overlay = null | 'quick' | 'morning' | 'bedtime' | 'pairing' | 'ambient' | 'exit'

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
  catalog: CatalogEntry[]
  launcherPrefs: LauncherPrefs; setLauncherPrefs(p: LauncherPrefs): void
  capabilities: Record<string, Capability>
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
  const timerAdapter = useMemo(() => (platform.simulated ? new MockTimer() : new FallbackTimer(platform)), [platform])
  const ctrl = useMemo(() => new TimerController(timerAdapter), [timerAdapter])
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
  const [screen, setScreen] = useState<Screen>('launcher')
  const [overlay, setOverlay] = useState<Overlay>(null)
  const [timerState, setTimerState] = useState<TimerState | 'unavailable'>('unavailable')
  const lastInput = useRef(Date.now())
  const [toast, setToast] = useState<string | null>(null)
  const toastTimer = useRef<ReturnType<typeof setTimeout>>(undefined)
  const lastLaunch = useRef<{ id: string; at: number }>({ id: '', at: 0 })
  const launch = useCallback(async (id: string, label: string) => {
    const t = Date.now()
    if (id && lastLaunch.current.id === id && t - lastLaunch.current.at < 1500) return // double press: ignore the repeat
    lastLaunch.current = { id, at: t }
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
  useEffect(() => { // scheduled change only when idle on the launcher or Our Home
    const scheduled = resolveMode(now, tz, windows)
    if (shouldApplyScheduledMode(applied, scheduled, { screen, ritualActive: overlay === 'morning' || overlay === 'bedtime', idleMs: Date.now() - lastInput.current })) setApplied(scheduled)
  }, [now, tz, windows, applied, screen, overlay])
  // Studio: only on work days in the work window, never for guests. It never replaces the launcher landing;
  // it is a nav item while available and the screen leaves it after a minute without input once it closes.
  const studioOn = studioVisible(snap.studio.settings, now, tz, guest)
  useEffect(() => { if (screen === 'studio' && !studioOn && (guest || Date.now() - lastInput.current >= 60_000)) setScreen('launcher') }, [now, screen, studioOn, guest])
  useEffect(() => { // photo frame after N idle minutes on Our Home (0 = never)
    const n = prefs.ambientAfterMin
    if (n > 0 && overlay === null && screen === 'home' && Date.now() - lastInput.current >= n * 60_000) setOverlay('ambient')
  }, [now, prefs.ambientAfterMin, overlay, screen])

  useEffect(() => { // root Back: confirm before leaving
    const open = () => setOverlay('exit')
    window.addEventListener(EXIT_EVENT, open)
    return () => window.removeEventListener(EXIT_EVENT, open)
  }, [])

  const refreshTimer = useCallback(async () => {
    const r = await ctrl.refresh()
    setTimerState(r.kind === 'confirmed' ? r.state : 'unavailable')
  }, [ctrl])
  useEffect(() => { // V/TV Sleep reopens V/HOME with its confirmed result after a one-click timer request
    if (!(timerAdapter instanceof FallbackTimer)) return
    const take = (raw: unknown) => {
      let p: unknown = raw
      if (typeof raw === 'string') { try { p = JSON.parse(raw) } catch { return } }
      const rep = timerAdapter.ingest(parseReport((p as { timer?: unknown } | null)?.timer))
      if (!rep) return
      if (rep.op === 'error') { setToast(`V/TV Sleep: ${rep.error}`); clearTimeout(toastTimer.current); toastTimer.current = setTimeout(() => setToast(null), 6000) }
      void refreshTimer()
    }
    const ev = (e: Event) => take((e as CustomEvent).detail)
    document.addEventListener('webOSRelaunch', ev); document.addEventListener('webOSLaunch', ev)
    take(window.PalmSystem && (window.PalmSystem as { launchParams?: unknown }).launchParams)
    return () => { document.removeEventListener('webOSRelaunch', ev); document.removeEventListener('webOSLaunch', ev) }
  }, [timerAdapter, refreshTimer])
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
  // Launcher: bundled catalog is the base; apps installed on the TV are appended when webOS lets us list them.
  const [tvApps, setTvApps] = useState<CatalogEntry[]>([])
  const [lpCap, setLpCap] = useState<Capability>('unverified')
  const [lpDone, setLpDone] = useState(platform.simulated)
  useEffect(() => {
    if (platform.simulated) return
    let stop = false
    void platform.call('luna://com.webos.applicationManager/listLaunchPoints', {}).then((r) => {
      if (stop) return
      if ('ok' in r && r.ok) {
        setLpCap('supported')
        const raw = Array.isArray(r.data.launchPoints) ? (r.data.launchPoints as { id?: unknown; hidden?: unknown; visible?: unknown }[]) : []
        const hiddenByTv = new Set(raw.filter((x) => x.hidden === true || x.visible === false).map((x) => String(x.id)))
        setTvApps(parseLaunchPoints(r.data).map((a) => {
          const kind = a.id.includes('.hdmi') ? 'input' as const : 'app' as const
          return { id: a.id, title: a.label, kind, icon: null, source: 'tv' as const, system: isSystemApp(a.id, kind, hiddenByTv.has(a.id)) }
        }))
      } else if ('ok' in r && /denied|permission|not allowed|security/i.test(r.error)) setLpCap('denied')
    }).catch(() => { if (!stop) setLpCap('unavailable') }).finally(() => { if (!stop) setLpDone(true) })
    return () => { stop = true }
  }, [platform])
  const [launcherPrefs, setPrefsState] = useState<LauncherPrefs>(loadPrefs)
  const catalog = useMemo(() => {
    const base = bundledCatalog().entries
    const current = [...base, ...tvApps.filter((n) => !base.some((b) => b.id === n.id))]
    if (!lpDone) return current // wait for the TV list so installed apps are not briefly marked missing
    const p = launcherPrefs
    return withRemembered(current, (id) => p.favorites.includes(id) || p.order.includes(id) || p.folders.some((f) => f.apps.includes(id)))
  }, [tvApps, lpDone, launcherPrefs])
  // any save (seed or user edit) marks the layout as chosen, so household pins never overwrite it later
  const setLauncherPrefs = useCallback((p: LauncherPrefs) => { const q = { ...p, seeded: true }; setPrefsState(q); savePrefs(q) }, [])
  const hasHousehold = isLive ? live.status === 'ready' && live.snapshot != null : true
  const pinnedIds = appsOf(snap).slice(0, MAX_FAVORITES).map((a) => a.id)
  useEffect(() => { // first run: favorites start as the household's pinned apps once known; afterwards local only
    if (launcherPrefs.seeded || !hasHousehold) return
    setLauncherPrefs({ ...launcherPrefs, favorites: pinnedIds })
  }, [launcherPrefs, hasHousehold, pinnedIds.join(), setLauncherPrefs]) // eslint-disable-line react-hooks/exhaustive-deps
  // unpaired and not yet seeded: show the default strip without saving it
  const shownPrefs = launcherPrefs.seeded ? launcherPrefs : { ...launcherPrefs, favorites: pinnedIds }
  const capabilities: Record<string, Capability> = { listLaunchPoints: lpCap, timerDirect: ctrl.verified ? 'supported' : 'unverified', homeRedirect: 'unverified' }
  const value: AppState = {
    snap, tz, now, mode, manualMode, setManualMode, guest, setGuest, screen, go: setScreen, studioOn, overlay, setOverlay,
    platform, ctrl, timerState, refreshTimer, toggleTask, weather: isLive ? liveWeather : snap.household.city ? weatherView({ ...fixtureWeather, fetchedAt: now.getTime() }, now.getTime(), false) : null, live: isLive ? live : null, launch, toast, images: isLive ? live.images : {},
    catalog, launcherPrefs: shownPrefs, setLauncherPrefs, capabilities,
  }
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export const personName = (s: Snapshot, id: string) => (id === 'both' ? 'Both' : s.household.people.find((p) => p.id === id)?.name ?? '')
