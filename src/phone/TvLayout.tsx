import { useState } from 'react'
import { CANDIDATE_APPS, type PinnedApp } from '../shared/model'
import { DEFAULT_PREFS, fromHHMM, resolvePrefs, toHHMM, windowsOverlap, type TvPrefs } from '../shared/prefs'

export const MAX_STRIP = 6

/** Ordered launch strip: order here is the order on the TV. Max 6 (design-system.md). */
export function LaunchStrip({ pinned, onChange }: { pinned: PinnedApp[]; onChange: (next: PinnedApp[]) => void }) {
  const move = (i: number, d: -1 | 1) => { const n = [...pinned]; const j = i + d; if (j < 0 || j >= n.length) return; [n[i], n[j]] = [n[j], n[i]]; onChange(n) }
  const rest = CANDIDATE_APPS.filter((c) => !pinned.some((p) => p.id === c.id))
  return <div>
    <div className="dim">{pinned.length ? `Shown on the TV in this order (max ${MAX_STRIP}).` : 'Nothing chosen: the TV shows its default set.'} Unverified until tested on your TV.</div>
    {pinned.map((a, i) => <div className="item" key={a.id}><span>{i + 1}. {a.label}</span>
      <div className="row"><button className="pbtn" disabled={i === 0} onClick={() => move(i, -1)}>Up</button><button className="pbtn" disabled={i === pinned.length - 1} onClick={() => move(i, 1)}>Down</button>
        <button className="pbtn danger" onClick={() => onChange(pinned.filter((p) => p.id !== a.id))}>Remove</button></div></div>)}
    {rest.length > 0 && <><label>Add an app</label><div className="row">{rest.map((a) => <button key={a.id} className="pbtn" disabled={pinned.length >= MAX_STRIP} onClick={() => onChange([...pinned, a])}>+ {a.label}</button>)}</div></>}
    {pinned.length >= MAX_STRIP && <div className="dim">The strip holds {MAX_STRIP}. Remove one to add another.</div>}
  </div>
}

/** Fixed layout, tunable parts. Saved together so one edit is one revision. */
export function TvLayout({ raw, dreams, onSave }: { raw: unknown; dreams: { id: string; title: string }[]; onSave: (tv: TvPrefs | undefined) => Promise<void> }) {
  const [p, setP] = useState<TvPrefs>(() => resolvePrefs(raw, dreams))
  const [busy, setBusy] = useState(false)
  const set = <K extends keyof TvPrefs>(k: K, v: TvPrefs[K]) => setP({ ...p, [k]: v })
  const time = (k: 'morning' | 'evening', i: 0 | 1) => <input type="time" value={toHHMM(p[k][i])} onChange={(e) => { const m = fromHHMM(e.target.value); if (m != null) { const w: [number, number] = [...p[k]]; w[i] = m; set(k, w) } }} />
  const overlap = windowsOverlap(p.morning, p.evening)
  const run = async (f: () => Promise<void>) => { setBusy(true); try { await f() } finally { setBusy(false) } }
  return <div>
    <label>Featured dream</label>
    <select value={p.featuredDreamId ?? ''} onChange={(e) => set('featuredDreamId', e.target.value || null)}>
      <option value="">Let V/HOME choose</option>{dreams.map((d) => <option key={d.id} value={d.id}>{d.title}</option>)}</select>
    <label>Big picture on Our Home</label>
    <select value={p.hero} onChange={(e) => set('hero', e.target.value as TvPrefs['hero'])}><option value="dream">Featured dream</option><option value="reflection">Reflection only</option></select>
    <label>Morning starts / ends</label><div className="row">{time('morning', 0)}{time('morning', 1)}</div>
    <label>Evening starts / ends</label><div className="row">{time('evening', 0)}{time('evening', 1)}</div>
    {overlap && <div className="err">Morning and Evening overlap. The TV will show Morning during the overlap.</div>}
    <label className="chk"><input type="checkbox" checked={p.showToday} onChange={(e) => set('showToday', e.target.checked)} />Show Today / Tomorrow plans</label>
    <label className="chk"><input type="checkbox" checked={p.showForUs} onChange={(e) => set('showForUs', e.target.checked)} />Show "For us"</label>
    <label>Start the TV in</label>
    <select value={p.defaultMode} onChange={(e) => set('defaultMode', e.target.value as TvPrefs['defaultMode'])}><option value="auto">Auto (by time of day)</option><option value="home">Home</option><option value="morning">Morning</option><option value="evening">Evening</option></select>
    <div className="row" style={{ marginTop: 14 }}>
      <button className="pbtn primary" disabled={busy} onClick={() => run(() => onSave(p))}>Save TV layout</button>
      <button className="pbtn" disabled={busy} onClick={() => run(async () => { await onSave(undefined); setP(DEFAULT_PREFS) })}>Reset to defaults</button></div>
  </div>
}
