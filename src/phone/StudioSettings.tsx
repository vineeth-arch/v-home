import { useEffect, useState } from 'react'
import { getClient } from '../shared/supabase'
import { resolveStudio, SOURCES, type SourceKey, type StudioSettings as S } from '../../supabase/functions/_shared/studio'
import { fromHHMM, toHHMM } from '../shared/prefs'

const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
type Status = { studio: true; configured: Record<SourceKey, boolean> } | null
interface Row { source: string; ok: boolean; fetched_at: string }

/** Studio (business numbers on the TV). Shown only for the household the server is set up for (STUDIO_HOUSEHOLD_ID). */
export function StudioSettings({ raw, onSave }: { raw: unknown; onSave: (studio: S) => Promise<void> }) {
  const [status, setStatus] = useState<Status | undefined>(undefined)
  const [s, setS] = useState(() => resolveStudio(raw))
  const [rows, setRows] = useState<Row[]>([]); const [msg, setMsg] = useState(''); const [busy, setBusy] = useState(false)
  const c = getClient()
  const loadRows = async () => setRows(((await c.from('business_metrics').select('source,ok,fetched_at')).data ?? []) as Row[])
  useEffect(() => {
    void c.functions.invoke('business-sync', { body: { op: 'status' } }).then(({ data, error }) => setStatus(error ? null : (data as Status)))
    void loadRows()
  }, [])
  if (status === undefined || status === null) return null // not set up for this household: no Studio section at all

  const lastBy = (k: SourceKey) => rows.filter((r) => r.source === k).sort((a, b) => b.fetched_at.localeCompare(a.fetched_at))[0]
  const refresh = async () => {
    setBusy(true); setMsg('')
    const { data, error } = await c.functions.invoke('business-sync', { body: {} })
    setMsg(error ? 'Refresh failed. Try again in a minute.' : (data as { skipped?: string }).skipped === 'fresh' ? 'Already fresh (refreshes at most once a minute).' : 'Refreshed.')
    await loadRows(); setBusy(false)
  }
  const set = (p: Partial<S>) => setS({ ...s, ...p })
  return <div>
    <h2>Studio (business on the TV)</h2>
    <div className="dim">Aggregate numbers only, shown on work days during work hours, never in guest view. Setup: docs/STUDIO.md.</div>
    <label className="chk"><input type="checkbox" checked={s.enabled} onChange={(e) => set({ enabled: e.target.checked })} />Show Studio on the TV</label>
    {SOURCES.map((src) => {
      const last = lastBy(src.key)
      return <label className="chk" key={src.key}><input type="checkbox" checked={s.sources[src.key]} disabled={!status.configured[src.key]} onChange={(e) => set({ sources: { ...s.sources, [src.key]: e.target.checked } })} />
        {src.label} <span className="dim">{!status.configured[src.key] ? '· not connected' : last ? `· ${last.ok ? 'ok' : 'last refresh failed'}, ${new Date(last.fetched_at).toLocaleTimeString()}` : '· not synced yet'}</span></label>
    })}
    <label>Work days</label>
    <div className="row">{DAYS.map((d, i) => <label className="chk" key={d} style={{ marginRight: 8 }}><input type="checkbox" checked={s.window.days.includes(i + 1)} onChange={(e) => set({ window: { ...s.window, days: e.target.checked ? [...s.window.days, i + 1].sort() : s.window.days.filter((x) => x !== i + 1) } })} />{d}</label>)}</div>
    <label>Work hours</label>
    <div className="row"><input type="time" value={toHHMM(s.window.start)} onChange={(e) => { const v = fromHHMM(e.target.value); if (v !== null) set({ window: { ...s.window, start: v } }) }} />
      <span className="dim">to</span><input type="time" value={toHHMM(s.window.end)} onChange={(e) => { const v = fromHHMM(e.target.value); if (v !== null) set({ window: { ...s.window, end: v } }) }} /></div>
    {s.window.start >= s.window.end && <div className="err">Work hours must end after they start.</div>}
    <label className="chk"><input type="checkbox" checked={s.showNames} onChange={(e) => set({ showNames: e.target.checked })} />Show brand names in "Next follow-ups"</label>
    {msg && <div className="dim">{msg}</div>}
    <div className="row" style={{ marginTop: 12 }}>
      <button className="pbtn primary" disabled={busy || s.window.start >= s.window.end} onClick={() => void onSave(s)}>Save Studio</button>
      <button className="pbtn" disabled={busy} onClick={() => void refresh()}>Refresh now</button></div>
  </div>
}
