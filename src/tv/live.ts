import { useCallback, useEffect, useRef, useState } from 'react'
import type { SupabaseClient } from '@supabase/supabase-js'
import { getClient } from '../shared/supabase'
import { normalizeSnapshot, toSnapshot, type Rows } from '../shared/snapshot'
import { RevokedError, SyncEngine } from '../shared/sync'
import { pickStore, type CacheStore } from '../shared/cache'
import { createImageCache } from '../shared/imageCache'
import type { Snapshot } from '../shared/model'
import { backoffDelay, shouldIssueCode } from '../shared/pairing'

export type LiveStatus = 'booting' | 'pairing' | 'ready'
export interface Live { images: Record<string, string>; status: LiveStatus; code: string | null; snapshot: Snapshot | null; offline: boolean; cacheBackend: string; unpair(): Promise<void>; completeTask(id: string): Promise<void>; markWatched(id: string): Promise<void> }

/** Signed URLs live in memory only (they expire after an hour). Offline or unsigned photos fall back to the cached blob. */
async function resolveImages(c: SupabaseClient, paths: string[], cache: ReturnType<typeof createImageCache>, made: string[]): Promise<Record<string, string>> {
  const uniq = [...new Set(paths.filter(Boolean))]
  const out: Record<string, string> = {}
  let signed: Record<string, string> = {}
  try {
    const r = await c.storage.from('household-media').createSignedUrls(uniq, 3600)
    for (const x of r.data ?? []) if (x.path && x.signedUrl) signed[x.path] = x.signedUrl
  } catch { signed = {} }
  for (const p of uniq) {
    if (signed[p]) {
      out[p] = signed[p]
      void (async () => { if (await cache.get(p)) return; try { const b = await (await fetch(signed[p])).blob(); await cache.put(p, b) } catch { /* fetch can fail on file:// (CORS); the <img> still works */ } })()
    } else { const b = await cache.get(p); if (b) { const u = URL.createObjectURL(b); made.push(u); out[p] = u } }
  }
  return out
}

const q = async <T,>(p: PromiseLike<{ data: T | null; error: { message: string } | null }>): Promise<T> => {
  const { data, error } = await p
  if (error) throw new Error(error.message)
  return data as T
}

async function fetchRows(c: SupabaseClient, hh: string): Promise<Rows> {
  const [household, members, events, tasks, notes, dreams, ideas, watch_entries, watch_prefs, quotes, weekly, media] = await Promise.all([
    q(c.from('households').select('id,name,timezone,settings').eq('id', hh).single()),
    q(c.from('members').select('user_id,role,display_name').eq('household_id', hh)),
    q(c.from('events').select('id,title,starts_at,all_day').order('starts_at')),
    q(c.from('tasks').select('id,title,owner,kind,done').order('created_at')),
    q(c.from('notes').select('id,body,author_id,to_user,created_at').order('created_at', { ascending: false })),
    q(c.from('dreams').select('id,title,why,affirmation,next_step,target_date,art,image_path').order('created_at')),
    q(c.from('ideas').select('id,title,note,status,author_id,pinned,image_path').order('created_at', { ascending: false })),
    q(c.from('watch_entries').select('id,title,type,runtime_min,service,mood,summary,watched,providers,providers_updated_at,poster_path')),
    q(c.from('watch_prefs').select('entry_id,user_id,pref')),
    q(c.from('quotes').select('id,slot,body,author,source,favorite').eq('hidden', false)),
    q(c.from('ritual_selections').select('day,payload').eq('slot', 'weekly').order('day', { ascending: false }).limit(1)),
    q(c.from('media').select('path,taken_on,caption').eq('show_on_tv', true).order('created_at', { ascending: false }).limit(200)),
  ])
  return { household, members, events, tasks, notes, dreams, ideas, watch_entries, watch_prefs, quotes, weekly, media } as unknown as Rows
}

/** TV lifecycle: anonymous session, pairing, cached-first render, versioned sync, revoke handling. */
export function useLive(enabled: boolean): Live {
  const [status, setStatus] = useState<LiveStatus>('booting')
  const [code, setCode] = useState<string | null>(null)
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null)
  const [offline, setOffline] = useState(false)
  const [cacheBackend, setBackend] = useState('')
  const hhRef = useRef<string | null>(null)
  const engineRef = useRef<SyncEngine | null>(null)
  const storeRef = useRef<CacheStore | null>(null)
  const epoch = useRef(0)
  const [images, setImages] = useState<Record<string, string>>({})
  const imgCache = useRef(createImageCache())
  const objectUrls = useRef<string[]>([])
  const lastPaths = useRef<string[]>([])

  const boot = useCallback(async () => {
    const my = ++epoch.current
    const alive = () => epoch.current === my
    const c = getClient()
    const store = (storeRef.current ??= await pickStore())
    setBackend(store.name)
    let { data: { session } } = await c.auth.getSession()
    if (!session) { const r = await c.auth.signInAnonymously(); if (r.error) throw r.error; session = r.data.session }
    const paired = async () => { const { data } = await c.rpc('pairing_status'); return (data as string | null) ?? null }
    let hh = await paired()
    if (!alive()) return
    if (!hh) {
      setStatus('pairing'); setSnapshot(null)
      let current: string | null = null, issued = 0 // loop-local: state from a render closure would be stale
      while (alive() && !hh) {
        if (shouldIssueCode(current, issued, Date.now())) { const r = await c.rpc('start_pairing'); if (r.error) throw r.error; current = r.data as string; issued = Date.now(); setCode(current) }
        await new Promise((r) => setTimeout(r, 3000))
        hh = await paired()
      }
      if (!alive()) return
    }
    hhRef.current = hh
    setCode(null)
    const cached = normalizeSnapshot(await store.get().catch(() => null))
    if (cached) setSnapshot(cached)
    setStatus('ready')
    const engine = new SyncEngine({
      fetchVersion: async () => {
        const { data, error } = await c.from('household_versions').select('version').eq('household_id', hh!).maybeSingle()
        if (error) throw new Error(error.message)
        if (!data) throw new RevokedError()
        return Number(data.version)
      },
      fetchSnapshot: async () => toSnapshot(await fetchRows(c, hh!)),
      onSnapshot: (s) => {
        setSnapshot(s); setOffline(false); void store.set(s)
        const paths = [...s.dreams.map((d) => d.imagePath), ...s.ideas.map((i) => i.imagePath), ...s.moments.map((m) => m.path)].filter((x): x is string => !!x)
        lastPaths.current = paths
        void resolveImages(c, paths, imgCache.current, objectUrls.current).then(setImages)
      },
      onOffline: () => setOffline(true),
      onRevoked: () => { void store.clear(); setSnapshot(null); run() },
    })
    engineRef.current = engine
    engine.start()
    const ch = c.channel(`hv-${hh}`).on('postgres_changes', { event: '*', schema: 'public', table: 'household_versions', filter: `household_id=eq.${hh}` }, () => engine.nudge()).subscribe()
    // signed URLs expire after 1h; re-sign well before that so a screen change never shows a dead picture
    const resign = setInterval(() => { if (lastPaths.current.length) void resolveImages(c, lastPaths.current, imgCache.current, objectUrls.current).then(setImages) }, 45 * 60_000)
    const nudge = () => engine.nudge()
    document.addEventListener('visibilitychange', nudge); addEventListener('online', nudge)
    const stop = () => { engine.stop(); clearInterval(resign); void c.removeChannel(ch); document.removeEventListener('visibilitychange', nudge); removeEventListener('online', nudge) }
    cleanup.current = stop
  }, []) // eslint-disable-line react-hooks/exhaustive-deps
  const cleanup = useRef<() => void>(() => {})
  const runId = useRef(0)

  /** boot with retry, so a TV that starts before Wi-Fi recovers on its own. */
  const run = useCallback(() => {
    const my = ++runId.current
    let attempt = 0
    const go = () => boot().then(() => { if (runId.current === my) setOffline(false) }).catch(() => {
      if (runId.current !== my) return
      setOffline(true)
      setTimeout(go, backoffDelay(attempt++))
    })
    go()
  }, [boot])

  useEffect(() => {
    if (!enabled) return
    run()
    return () => { runId.current++; epoch.current++; cleanup.current(); engineRef.current?.stop() }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled])

  const unpair = useCallback(async () => {
    const c = getClient()
    cleanup.current(); engineRef.current?.stop()
    await c.rpc('display_unpair'); await storeRef.current?.clear(); await imgCache.current.clear(); setImages({}); await c.auth.signOut()
    setSnapshot(null); setStatus('booting'); run()
  }, [run])
  const completeTask = useCallback(async (id: string) => { await getClient().rpc('tv_complete_task', { p_id: id }); engineRef.current?.nudge() }, [])
  const markWatched = useCallback(async (id: string) => { await getClient().rpc('tv_mark_watched', { p_id: id }); engineRef.current?.nudge() }, [])
  return { images, status, code, snapshot, offline, cacheBackend, unpair, completeTask, markWatched }
}
