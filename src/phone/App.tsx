import { useCallback, useEffect, useState } from 'react'
import { acceptInvite, approvePairing, createHousehold, createInvite, getHousehold, getMe, listMembers, listPrefs, listRows, revokeDisplay, saveHousehold, saveRow, setPref, signIn, signOut, signUp, type Me, type Row } from './api'
import { Crud } from './Crud'
import { ENTITIES } from './entities'
import { supabaseConfigured } from '../shared/supabase'
import { buildExport, previewCounts, remapImport, TABLES, type ExportFile } from '../shared/exportImport'
import { DEFAULT_APPS } from '../shared/model'

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
  const [tick, setTick] = useState(0)
  useEffect(() => { void listPrefs().then(setPrefs) }, [tick])
  return <Crud e={ENTITIES.watch_entries} hh={hh} me={me} decorate={(r: Row) => (
    <div className="row" style={{ marginBottom: 6 }}>
      {(['want', 'maybe', 'pass'] as const).map((p) => {
        const mine = prefs.find((x) => x.entry_id === r.id && x.user_id === me)?.pref
        return <button key={p} className={`pbtn ${mine === p ? 'on' : ''}`} onClick={async () => { await setPref(r.id, hh, me, p); setTick(tick + 1) }}>{p}</button>
      })}
      <span className="dim">{people.filter((x) => x.id !== me).map((x) => `${x.name}: ${prefs.find((q) => q.entry_id === r.id && q.user_id === x.id)?.pref ?? 'no vote'}`).join(' · ')}</span>
    </div>)} />
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
  useEffect(() => { void getHousehold().then((x) => { setH(x); setCity(String(x.settings.city ?? '')) }) }, [])
  const patchSettings = async (p: Record<string, unknown>, extra: Record<string, unknown> = {}) => { if (!h) return; try { await saveHousehold(h, { ...extra, settings: { ...h.settings, ...p } }); setH(await getHousehold()); setMsg('Saved.') } catch (x) { setMsg(errMsg(x)) } }
  const pinned = (h?.settings.pinnedApps as { id: string }[] | undefined) ?? []
  const doExport = async () => {
    const rows = Object.fromEntries(await Promise.all(TABLES.map(async (t) => [t, await listRows(t)]))) as never
    const f = buildExport({ name: h!.name, timezone: h!.timezone, settings: h!.settings }, rows)
    const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([JSON.stringify(f)], { type: 'application/json' })); a.download = `vhome-export-${new Date().toISOString().slice(0, 10)}.json`; a.click()
  }
  const doImport = async () => { if (!imp) return; try { const items = remapImport(imp, hh, me.userId); for (const it of items) await saveRow(it.table, hh, null, it.row); setMsg(`Imported ${items.length} items.`); setImp(null) } catch (x) { setMsg(errMsg(x)) } }
  if (!h) return <div className="dim">Loading…</div>
  return <div><h1>Settings</h1>
    <h2>Household</h2><label>Name</label><input defaultValue={h.name} onBlur={(e) => e.target.value !== h.name && void patchSettings({}, { name: e.target.value })} />
    <label>Timezone</label><input defaultValue={h.timezone} onBlur={(e) => e.target.value !== h.timezone && void patchSettings({}, { timezone: e.target.value })} />
    <h2>Weather city</h2><div className="dim">Current: {String(h.settings.city ?? 'not set')}</div>
    <div className="row"><input value={city} onChange={(e) => setCity(e.target.value)} style={{ flex: 1 }} placeholder="Search city" />
      <button className="pbtn" onClick={async () => { try { const r = await fetch(`https://geocoding-api.open-meteo.com/v1/search?name=${encodeURIComponent(city)}&count=5`); setHits(((await r.json()).results ?? [])) } catch { setMsg('City search unavailable.') } }}>Search</button></div>
    {hits.map((x) => <button key={`${x.latitude}${x.longitude}`} className="item" onClick={() => { void patchSettings({ city: x.name, lat: x.latitude, lon: x.longitude, region: x.country_code }); setHits([]) }}>{x.name}{x.admin1 ? `, ${x.admin1}` : ''} · {x.country_code}</button>)}
    <h2>TV launch strip</h2><div className="dim">Unverified until tested on your TV.</div>
    {DEFAULT_APPS.map((a) => <label className="chk" key={a.id}><input type="checkbox" checked={pinned.some((p) => p.id === a.id)} onChange={(e) => void patchSettings({ pinnedApps: e.target.checked ? [...pinned, a] : pinned.filter((p) => p.id !== a.id) })} />{a.label}</label>)}
    <h2>Invite your partner</h2><div className="row"><button className="pbtn" onClick={async () => { try { setInvite(`${location.origin}/?token=${await createInvite(hh)}`) } catch (x) { setMsg(errMsg(x)) } }}>Create invite link</button></div>
    {invite && <div className="item"><span className="sub">Send this once. It works for 7 days and one person.</span><span style={{ wordBreak: 'break-all' }}>{invite}</span></div>}
    <h2>Backup</h2><div className="row"><button className="pbtn" onClick={() => void doExport()}>Export household</button>
      <label className="pbtn" style={{ margin: 0 }}>Import<input type="file" accept="application/json" hidden onChange={async (e) => { const f = e.target.files?.[0]; if (f) try { setImp(JSON.parse(await f.text())) } catch { setMsg('That file is not a V/HOME export.') } }} /></label></div>
    <div className="dim">Photos are not part of exports yet.</div>
    {imp && <div className="item"><span>Import into this household?</span><span className="sub">{Object.entries(previewCounts(imp)).map(([k, n]) => `${n} ${k}`).join(', ')}</span><div className="row"><button className="pbtn primary" onClick={() => void doImport()}>Import</button><button className="pbtn" onClick={() => setImp(null)}>Cancel</button></div></div>}
    {msg && <div className={/^(Saved|Imported)/.test(msg) ? 'ok' : 'err'}>{msg}</div>}
    <h2>Account</h2><div className="dim">{me.email}</div><div className="row" style={{ marginTop: 8 }}><button className="pbtn" onClick={async () => { await signOut(); onSignOut() }}>Sign out</button></div></div>
}

const TABS = ['events', 'tasks', 'dreams', 'notes', 'ideas', 'watch', 'displays', 'settings'] as const
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
  return <><div className="p">
    {tab === 'settings' ? <Settings hh={hh} me={me} onSignOut={() => setMe(null)} />
      : tab === 'displays' ? <Displays hh={hh} />
        : tab === 'watch' ? <Watch hh={hh} me={me.userId} people={people} />
          : <Crud key={tab} e={ENTITIES[tab]} hh={hh} me={me.userId} extraOptions={ownerOpts} />}
  </div>
    <nav className="tabs">{TABS.map((t) => <button key={t} className={`pbtn ${tab === t ? 'cur' : ''}`} onClick={() => setTab(t)}>{ENTITIES[t]?.plural ?? (t === 'watch' ? 'Watch' : t[0].toUpperCase() + t.slice(1))}</button>)}</nav></>
}
