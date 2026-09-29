import { useCallback, useEffect, useState } from 'react'
import { acceptInvite, approvePairing, createHousehold, createInvite, getHousehold, getMe, listMembers, listPrefs, listRows, revokeDisplay, saveHousehold, saveRow, setPref, signIn, signOut, signUp, type Me, type Row } from './api'
import { Crud } from './Crud'
import { ENTITIES } from './entities'
import { supabaseConfigured } from '../shared/supabase'
import { base64ToBlob, blobToBase64, buildExport, previewCounts, remapImport, TABLES, type ExportedPhoto, type ExportFile } from '../shared/exportImport'
import { downloadPhoto, restorePhoto } from './media'
import type { PinnedApp } from '../shared/model'
import { LaunchStrip, MoreApps, TvLayout } from './TvLayout'
import { sanitizeCustomApps } from '../shared/apps'
import { Reflections } from './Reflections'
import { Weekly } from './Weekly'
import { Moments } from './Moments'
import { TmdbSearch, refreshAvailability } from './TmdbSearch'
import { ideaToDream, ideaToTask } from '../shared/convert'

const qs = new URLSearchParams(location.search)
const errMsg = (x: unknown) => (x instanceof Error ? x.message : String(x))

function Auth({ onDone }: { onDone: () => void }) {
  const [mode, setMode] = useState<'in' | 'up'>('in')
  const [email, setEmail] = useState(''); const [pw, setPw] = useState(''); const [err, setErr] = useState(''); const [busy, setBusy] = useState(false)
  const go = async () => { setBusy(true); setErr(''); try { await (mode === 'in' ? signIn(email, pw) : signUp(email, pw)); onDone() } catch (x) { setErr(errMsg(x)) } finally { setBusy(false) } }
  return <div className="p"><h1>V/HOME</h1><div className="dim">Plan, dream and choose together.</div>
    <label>Email</label><input type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} />
    <label>Password</label><input type="password" autoComplete={mode === 'in' ? 'current-password' : 'new-password'} value={pw} onChange={(e) => setPw(e.target.value)} />
    {err && <div className="err">{err}</div>}
    <div className="row" style={{ marginTop: 16 }}><button className="pbtn primary" disabled={busy} onClick={go}>{mode === 'in' ? 'Sign in' : 'Create account'}</button>
      <button className="pbtn" onClick={() => setMode(mode === 'in' ? 'up' : 'in')}>{mode === 'in' ? 'New here?' : 'I have an account'}</button></div></div>
}

function Onboarding({ onDone }: { onDone: () => void }) {
  const [name, setName] = useState(''); const [hname, setHname] = useState('Our Home'); const [token, setToken] = useState(qs.get('token') ?? ''); const [err, setErr] = useState('')
  const run = async (f: () => Promise<unknown>) => { setErr(''); try { await f(); onDone() } catch (x) { setErr(errMsg(x)) } }
  return <div className="p"><h1>Welcome</h1><label>Your name</label><input value={name} onChange={(e) => setName(e.target.value)} />
    {err && <div className="err">{err}</div>}
    {token ? <div className="row" style={{ marginTop: 16 }}><button className="pbtn primary" disabled={!name.trim()} onClick={() => run(() => acceptInvite(token.trim(), name))}>Join household</button></div> : <>
      <h2>Start a household</h2><label>Household name</label><input value={hname} onChange={(e) => setHname(e.target.value)} />
      <div className="row" style={{ marginTop: 12 }}><button className="pbtn primary" disabled={!name.trim()} onClick={() => run(() => createHousehold(hname, name))}>Create</button></div>
      <h2>Or join with an invite</h2><label>Invite code</label><input value={token} onChange={(e) => setToken(e.target.value)} />
      <div className="row" style={{ marginTop: 12 }}><button className="pbtn" disabled={!name.trim() || !token.trim()} onClick={() => run(() => acceptInvite(token.trim(), name))}>Join</button></div></>}</div>
}

function Watch({ hh, me, people }: { hh: string; me: string; people: { id: string; name: string }[] }) {
  const [prefs, setPrefs] = useState<Awaited<ReturnType<typeof listPrefs>>>([])
  const [tick, setTick] = useState(0); const [region, setRegion] = useState('IN'); const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)
  useEffect(() => { void listPrefs().then(setPrefs) }, [tick])
  useEffect(() => { void getHousehold().then((h) => setRegion(String(h.settings.region ?? 'IN'))).catch(() => {}) }, [])
  return <div>
    <TmdbSearch hh={hh} region={region} onAdded={() => setTick((t) => t + 1)} />
    {msg && <div className={msg.ok ? 'ok' : 'err'}>{msg.text}</div>}
    <Crud key={tick} e={ENTITIES.watch_entries} hh={hh} me={me} decorate={(r: Row) => (
      <div className="row" style={{ marginBottom: 6 }}>
        {(['want', 'maybe', 'pass'] as const).map((p) => {
          const mine = prefs.find((x) => x.entry_id === r.id && x.user_id === me)?.pref
          return <button key={p} className={`pbtn ${mine === p ? 'on' : ''}`} onClick={async () => { await setPref(r.id, hh, me, p); setTick(tick + 1) }}>{p}</button>
        })}
        {r.tmdb_id != null && <button className="pbtn" onClick={async () => { setMsg(await refreshAvailability(hh, r, region)); setTick((t) => t + 1) }}>Refresh availability</button>}
        <span className="dim">{people.filter((x) => x.id !== me).map((x) => `${x.name}: ${prefs.find((q) => q.entry_id === r.id && q.user_id === x.id)?.pref ?? 'no vote'}`).join(' · ')}</span>
      </div>)} />
  </div>
}

function Ideas({ hh, me }: { hh: string; me: string }) {
  const [n, setN] = useState(0); const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const make = async (r: Row, kind: 'task' | 'dream') => {
    setMsg(null)
    try {
      const idea = { title: String(r.title), note: String(r.note ?? '') }
      await saveRow(kind === 'task' ? 'tasks' : 'dreams', hh, null, kind === 'task' ? ideaToTask(idea) : ideaToDream(idea))
      const u = await saveRow('ideas', hh, r, { status: 'planned' })
      setMsg('conflict' in u ? { ok: false, text: `Created the ${kind}, but the idea changed elsewhere. Open it to review.` } : { ok: true, text: `Created a ${kind}. The idea is now planned.` })
    } catch (x) { setMsg({ ok: false, text: errMsg(x) }) }
    setN(n + 1)
  }
  return <div>{msg && <div className={msg.ok ? 'ok' : 'err'}>{msg.text}</div>}
    <Crud key={n} e={ENTITIES.ideas} hh={hh} me={me} decorate={(r: Row) => r.status === 'archived' ? null : <div className="row" style={{ marginBottom: 6 }}><button className="pbtn" onClick={() => void make(r, 'task')}>Make task</button><button className="pbtn" onClick={() => void make(r, 'dream')}>Make dream</button></div>} /></div>
}

function Displays({ hh }: { hh: string }) {
  const [code, setCode] = useState((qs.get('code') ?? '').toUpperCase()); const [msg, setMsg] = useState(''); const [list, setList] = useState<{ user_id: string; created_at: string }[]>([])
  const load = useCallback(() => listMembers().then((m) => setList(m.filter((x) => x.role === 'display'))), [])
  useEffect(() => { void load() }, [load])
  return <div><h1>Displays</h1><div className="dim">Enter the code shown on the TV.</div>
    <label>TV code</label><input value={code} maxLength={6} autoCapitalize="characters" onChange={(e) => setCode(e.target.value.toUpperCase())} />
    <div className="row" style={{ marginTop: 12 }}><button className="pbtn primary" onClick={async () => { try { await approvePairing(code, hh); setMsg('TV paired.'); setCode(''); void load() } catch (x) { setMsg(errMsg(x)) } }}>Pair this TV</button></div>
    {msg && <div className={msg === 'TV paired.' ? 'ok' : 'err'}>{msg}</div>}
    <h2>Paired</h2>{list.length === 0 && <div className="dim">No TVs yet.</div>}
    {list.map((d) => <div className="item" key={d.user_id}><span>TV paired {new Date(d.created_at).toLocaleDateString()}</span>
      <div className="row"><button className="pbtn danger" onClick={async () => { if (confirm('Remove this TV? It will stop showing your content when it reconnects.')) { await revokeDisplay(hh, d.user_id); void load() } }}>Revoke</button></div></div>)}</div>
}

function Settings({ hh, me, onSignOut }: { hh: string; me: Me; onSignOut: () => void }) {
  const [h, setH] = useState<Awaited<ReturnType<typeof getHousehold>> | null>(null); const [msg, setMsg] = useState(''); const [invite, setInvite] = useState('')
  const [city, setCity] = useState(''); const [hits, setHits] = useState<{ name: string; admin1?: string; country_code: string; latitude: number; longitude: number }[]>([])
  const [imp, setImp] = useState<ExportFile | null>(null)
  const [dreams, setDreams] = useState<{ id: string; title: string }[]>([])
  useEffect(() => { void listRows('dreams').then((r) => setDreams(r.map((d) => ({ id: d.id, title: String(d.title) })))).catch(() => {}) }, [])
  useEffect(() => { void getHousehold().then((x) => { setH(x); setCity(String(x.settings.city ?? '')) }) }, [])
  const patchSettings = async (p: Record<string, unknown>, extra: Record<string, unknown> = {}) => { if (!h) return; try { await saveHousehold(h, { ...extra, settings: { ...h.settings, ...p } }); setH(await getHousehold()); setMsg('Saved.') } catch (x) { setMsg(errMsg(x)) } }
  const pinned = (h?.settings.pinnedApps as PinnedApp[] | undefined) ?? []
  const doExport = async () => {
    const rows = Object.fromEntries(await Promise.all(TABLES.map(async (t) => [t, await listRows(t)]))) as never
    const media: ExportedPhoto[] = []
    const mrows = await listRows('media').catch(() => [] as Row[])
    for (const t of ['dreams', 'ideas'] as const) for (const r of (rows as Record<string, Row[]>)[t]) {
      const p = r.image_path as string | null; if (!p || media.some((m) => m.path === p)) continue
      const b = await downloadPhoto(p); if (b) media.push({ path: p, base64: await blobToBase64(b), showOnTv: Boolean(mrows.find((m) => (m as unknown as { path: string }).path === p)?.show_on_tv) })
    }
    const f = buildExport({ name: h!.name, timezone: h!.timezone, settings: h!.settings }, rows, new Date(), media)
    const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([JSON.stringify(f)], { type: 'application/json' })); a.download = `vhome-export-${new Date().toISOString().slice(0, 10)}.json`; a.click()
  }
  const doImport = async () => { if (!imp) return; try { const { items, photos } = remapImport(imp, hh, me.userId); for (const p of photos) await restorePhoto(hh, p.newPath, base64ToBlob(p.base64), p.showOnTv); for (const it of items) await saveRow(it.table, hh, null, it.row); setMsg(`Imported ${items.length} items${photos.length ? ` and ${photos.length} photos` : ''}.`); setImp(null) } catch (x) { setMsg(errMsg(x)) } }
  if (!h) return <div className="dim">Loading…</div>
  return <div><h1>Settings</h1>
    <h2>Household</h2><label>Name</label><input defaultValue={h.name} onBlur={(e) => e.target.value !== h.name && void patchSettings({}, { name: e.target.value })} />
    <label>Timezone</label><input defaultValue={h.timezone} onBlur={(e) => e.target.value !== h.timezone && void patchSettings({}, { timezone: e.target.value })} />
    <h2>Weather city</h2><div className="dim">Current: {String(h.settings.city ?? 'not set')}</div>
    <div className="row"><input value={city} onChange={(e) => setCity(e.target.value)} style={{ flex: 1 }} placeholder="Search city" />
      <button className="pbtn" onClick={async () => { try { const r = await fetch(`https://geocoding-api.open-meteo.com/v1/search?name=${encodeURIComponent(city)}&count=5`); setHits(((await r.json()).results ?? [])) } catch { setMsg('City search unavailable.') } }}>Search</button></div>
    {hits.map((x) => <button key={`${x.latitude}${x.longitude}`} className="item" onClick={() => { void patchSettings({ city: x.name, lat: x.latitude, lon: x.longitude, region: x.country_code }); setHits([]) }}>{x.name}{x.admin1 ? `, ${x.admin1}` : ''} · {x.country_code}</button>)}
    <h2>Streaming region</h2><div className="dim">Two-letter country code for where titles stream (IN for India).</div><input defaultValue={String(h.settings.region ?? 'IN')} maxLength={2} onBlur={(e) => { const v = e.target.value.trim().toUpperCase(); if (/^[A-Z]{2}$/.test(v) && v !== h.settings.region) void patchSettings({ region: v }) }} style={{ maxWidth: 100, textTransform: 'uppercase' }} />
    <h2>TV launch strip</h2><LaunchStrip pinned={pinned as PinnedApp[]} onChange={(next) => void patchSettings({ pinnedApps: next })} />
    <h2>More apps</h2><MoreApps apps={sanitizeCustomApps(h.settings.customApps)} onChange={(next) => void patchSettings({ customApps: next })} />
    <h2>TV layout</h2><div className="dim">The layout stays fixed. These tune it.</div>
    <TvLayout key={h.revision} raw={h.settings.tv} dreams={dreams} onSave={(tv) => patchSettings({ tv })} />
    <h2>Invite your partner</h2><div className="row"><button className="pbtn" onClick={async () => { try { setInvite(`${location.origin}/?token=${await createInvite(hh)}`) } catch (x) { setMsg(errMsg(x)) } }}>Create invite link</button></div>
    {invite && <div className="item"><span className="sub">Send this once. It works for 7 days and one person.</span><span style={{ wordBreak: 'break-all' }}>{invite}</span></div>}
    <h2>Backup</h2><div className="row"><button className="pbtn" onClick={() => void doExport()}>Export household</button>
      <label className="pbtn" style={{ margin: 0 }}>Import<input type="file" accept="application/json" hidden onChange={async (e) => { const f = e.target.files?.[0]; if (f) try { setImp(JSON.parse(await f.text())) } catch { setMsg('That file is not a V/HOME export.') } }} /></label></div>
    <div className="dim">Exports include your photos, so the file can be large.</div>
    {imp && <div className="item"><span>Import into this household?</span><span className="sub">{Object.entries(previewCounts(imp)).map(([k, n]) => `${n} ${k}`).join(', ')}</span><div className="row"><button className="pbtn primary" onClick={() => void doImport()}>Import</button><button className="pbtn" onClick={() => setImp(null)}>Cancel</button></div></div>}
    {msg && <div className={/^(Saved|Imported)/.test(msg) ? 'ok' : 'err'}>{msg}</div>}
    <h2>Account</h2><div className="dim">{me.email}</div><div className="row" style={{ marginTop: 8 }}><button className="pbtn" onClick={async () => { await signOut(); onSignOut() }}>Sign out</button></div></div>
}

const TABS = ['events', 'tasks', 'dreams', 'notes', 'photos', 'ideas', 'weekly', 'reflections', 'watch', 'displays', 'settings'] as const
export function App() {
  const [me, setMe] = useState<Me | null | undefined>(undefined); const [tab, setTab] = useState<(typeof TABS)[number]>(qs.get('code') ? 'displays' : 'events')
  const [people, setPeople] = useState<{ id: string; name: string }[]>([])
  const refresh = useCallback(async () => { try { setMe(await getMe()) } catch { setMe(null) } }, [])
  useEffect(() => { if (supabaseConfigured) void refresh(); else setMe(null) }, [refresh])
  useEffect(() => { if (me?.householdId) void listMembers().then((m) => setPeople(m.filter((x) => x.role === 'member').map((x) => ({ id: x.user_id, name: x.display_name })))) }, [me?.householdId])
  if (!supabaseConfigured) return <div className="p"><h1>V/HOME</h1><div className="err">Not configured. Copy .env.example to .env.local.</div></div>
  if (me === undefined) return <div className="p dim">Loading…</div>
  if (!me) return <Auth onDone={refresh} />
  if (!me.householdId) return <Onboarding onDone={refresh} />
  const hh = me.householdId
  const ownerOpts = { people: people.map((p) => p.id) }
  const names = Object.fromEntries(people.map((p) => [p.id, p.name]))
  return <><div className="p">
    {tab === 'settings' ? <Settings hh={hh} me={me} onSignOut={() => setMe(null)} />
      : tab === 'displays' ? <Displays hh={hh} />
        : tab === 'watch' ? <Watch hh={hh} me={me.userId} people={people} />
          : tab === 'weekly' ? <Weekly hh={hh} />
          : tab === 'photos' ? <Moments hh={hh} />
            : tab === 'reflections' ? <Reflections hh={hh} me={me.userId} />
              : tab === 'ideas' ? <Ideas hh={hh} me={me.userId} />
                : <Crud key={tab} e={ENTITIES[tab]} hh={hh} me={me.userId} extraOptions={ownerOpts} labels={names} />}
  </div>
    <nav className="tabs">{TABS.map((t) => <button key={t} className={`pbtn ${tab === t ? 'cur' : ''}`} onClick={() => setTab(t)}>{t === 'weekly' ? 'This week' : ENTITIES[t]?.plural ?? (t === 'watch' ? 'Watch' : t[0].toUpperCase() + t.slice(1))}</button>)}</nav></>
}
