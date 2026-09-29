import { useState } from 'react'
import { getClient } from '../shared/supabase'
import { saveRow, type Row } from './api'
import type { TmdbHit } from '../../supabase/functions/_shared/tmdb'

const POSTER = 'https://image.tmdb.org/t/p/w154'
export const TMDB_CREDIT = 'This product uses the TMDB API but is not endorsed or certified by TMDB. Streaming data from JustWatch.'

async function call<T>(body: object): Promise<T> {
  const { data, error } = await getClient().functions.invoke('tmdb', { body })
  if (error) {
    // 503 means the token was never set; anything else is an outage. Both fall back to manual entry.
    const status = (error as { context?: Response }).context?.status
    throw new Error(status === 503 ? 'not_configured' : 'unavailable')
  }
  return data as T
}

/** Search TMDB and add a title with runtime, poster and where it streams. Manual entry stays available below. */
export function TmdbSearch({ hh, region, onAdded }: { hh: string; region: string; onAdded: () => void }) {
  const [q, setQ] = useState(''); const [hits, setHits] = useState<TmdbHit[] | null>(null)
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null); const [busy, setBusy] = useState(false)
  const fail = (e: unknown) => setMsg({ ok: false, text: (e as Error).message === 'not_configured' ? 'Search is not set up yet. Add the title manually below.' : 'Search unavailable. Add the title manually below.' })
  const search = async () => {
    setBusy(true); setMsg(null)
    try { setHits((await call<{ results: TmdbHit[] }>({ op: 'search', q })).results) } catch (e) { setHits(null); fail(e) } finally { setBusy(false) }
  }
  const add = async (h: TmdbHit) => {
    setBusy(true); setMsg(null)
    try {
      const { entry } = await call<{ entry: Record<string, unknown> }>({ op: 'pick', id: h.id, type: h.type, region })
      const r = await saveRow('watch_entries', hh, null, entry)
      if ('ok' in r) { setMsg({ ok: true, text: `Added ${h.title}${entry.runtime_min ? `, ${entry.runtime_min} min` : ', runtime unknown'}${entry.service ? `, on ${entry.service}` : ''}.` }); setHits(null); setQ(''); onAdded() }
    } catch (e) { fail(e) } finally { setBusy(false) }
  }
  return <div className="item" style={{ cursor: 'default' }}>
    <span>Find a movie or series</span>
    <div className="row"><input value={q} placeholder="Title" onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && void search()} style={{ flex: 1 }} /><button className="pbtn" disabled={busy || q.trim().length < 2} onClick={() => void search()}>Search</button></div>
    {msg && <div className={msg.ok ? 'ok' : 'err'}>{msg.text}</div>}
    {hits?.length === 0 && <div className="dim">No matches.</div>}
    {hits?.map((h) => <button key={`${h.type}${h.id}`} className="item" style={{ flexDirection: 'row', alignItems: 'center', gap: 12 }} disabled={busy} onClick={() => void add(h)}>
      {h.posterPath ? <img src={`${POSTER}${h.posterPath}`} alt="" style={{ width: 46, height: 69, objectFit: 'cover', borderRadius: 6 }} /> : <span style={{ width: 46 }} />}
      <span style={{ flex: 1 }}>{h.title}<span className="sub"> · {h.type}{h.year ? ` · ${h.year}` : ''}</span></span></button>)}
    <div className="dim" style={{ fontSize: 12 }}>{TMDB_CREDIT}</div>
  </div>
}

/** Re-fetch where a saved title streams (availability changes). */
export async function refreshAvailability(hh: string, r: Row, region: string): Promise<{ ok: boolean; text: string }> {
  try {
    const { providers, updatedAt } = await call<{ providers: Record<string, string[]>; updatedAt: string }>({ op: 'providers', id: r.tmdb_id, type: r.type, region })
    const u = await saveRow('watch_entries', hh, r, { providers, providers_updated_at: updatedAt, service: providers.flatrate?.[0] ?? r.service ?? null })
    return 'ok' in u ? { ok: true, text: 'Availability updated.' } : { ok: false, text: 'Changed elsewhere. Reopen and try again.' }
  } catch (e) { return { ok: false, text: (e as Error).message === 'not_configured' ? 'Search is not set up yet.' : 'Availability unavailable right now.' } }
}
