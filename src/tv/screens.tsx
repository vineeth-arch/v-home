import { useMemo, useState } from 'react'
import { Btn, DreamArt, fmtDay, fmtTime } from './ui'
import { useLayer } from './FocusProvider'
import { useApp, personName, type Screen } from './state'
import { pickDaily } from '../shared/reflections'
import { localDate } from '../shared/daily'
import { upcoming } from '../shared/upcoming'
import { explainEmpty, pickForUs, topMatches, type Candidate, type Filters } from '../shared/picker'
import { appsOf, type WatchItem } from '../shared/model'
import qrcode from 'qrcode-generator'

export const NAV: { id: Screen; label: string }[] = [
  { id: 'home', label: 'Our Home' }, { id: 'watch', label: 'Watch Together' }, { id: 'us', label: 'Us' }, { id: 'ideas', label: 'Idea Wall' },
]
const MODE_LABEL = { home: 'Home', morning: 'Morning', evening: 'Evening' } as const

export function Header({ title }: { title?: string }) {
  const { now, tz, snap, mode, manualMode, setManualMode, setOverlay, go, weather, screen } = useApp()
  const hour = Number(new Intl.DateTimeFormat('en-GB', { timeZone: tz, hour: '2-digit', hourCycle: 'h23' }).format(now))
  const greet = hour < 12 ? 'Good morning' : hour < 18 ? 'Good afternoon' : 'Good evening'
  const cycle = () => setManualMode(manualMode === null ? 'home' : manualMode === 'home' ? 'morning' : manualMode === 'morning' ? 'evening' : null)
  return (
    <div className="hdr">
      {title ? <h1>{title}</h1> : <>
        <div className="clock">{fmtTime(now, tz)}</div>
        <div className="when"><span className="small">{fmtDay(now, tz)}</span><span className="greet">{greet}, {snap.household.people.map((p) => p.name).join(' & ') || snap.household.name}</span></div>
      </>}
      <div className="sp" />
      {weather ? (
        <div className="wx">{weather.showCurrent && <><b>{weather.tempC}°</b> {weather.label}<br /></>}
          <span className="dim">{mode === 'evening' ? `Tomorrow H${weather.tomorrow.hiC}° L${weather.tomorrow.loC}° · Rain ${weather.tomorrow.rainPct}%` : `H${weather.hiC}° L${weather.loC}° · Rain ${weather.rainPct}%`}</span>
          {weather.stale && <><br /><span className="dim">Updated {fmtTime(weather.fetchedAt, tz)}</span></>}</div>
      ) : <div className="wx dim">{snap.household.lat == null ? 'Set up weather on your phone' : 'Weather loading…'}</div>}
      <Btn id="hdr-mode" className="chip" onClick={cycle}>{manualMode ? MODE_LABEL[mode] : `Auto · ${MODE_LABEL[mode]}`}</Btn>
      <Btn id="hdr-quick" className="chip" onClick={() => setOverlay('quick')}>Quick controls</Btn>
      {screen !== 'settings' && <Btn id="hdr-settings" className="chip ghost" onClick={() => go('settings')}>Settings</Btn>}
    </div>
  )
}

export function Nav() {
  const { screen, go, timerState, now, tz } = useApp()
  const line = timerState === 'unavailable' ? 'Timer status unavailable'
    : timerState.scheduled ? `TV off at ${fmtTime(timerState.shutdownAt, tz)} · ${Math.max(0, Math.ceil((timerState.shutdownAt - now.getTime()) / 60000))} min` : 'No timer'
  return (
    <div className="nav">
      {NAV.map((n) => <Btn key={n.id} id={`nav-${n.id}`} className={screen === n.id ? 'cur' : ''} onClick={() => go(n.id)}>{n.label}</Btn>)}
      <span className="timer-line">{line}</span>
    </div>
  )
}

export function OurHome() {
  const { snap, now, tz, mode, guest, setOverlay, go, platform } = useApp()
  const [skipped, setSkipped] = useState(false)
  const date = localDate(now, tz)
  const slot = mode === 'evening' ? 'evening' : 'morning'
  const refl = pickDaily(snap.household.name, date, slot)
  const dream = guest ? undefined : snap.dreams[0]
  const quote = mode === 'home' && dream ? dream.affirmation : refl?.text ?? ''
  const cap = mode === 'home' && dream ? dream.title : 'Original reflection'
  const items = guest ? [] : upcoming(snap, now, mode)
  const note = guest ? undefined : snap.notes[0]
  const forUs = note ? { l: 'A note', t: `“${note.text}” · ${personName(snap, note.author)}` } : dream ? { l: 'A small step', t: dream.nextStep } : null
  return <>
    <div className="main">
      <div className="hero">
        <DreamArt kind={dream?.art ?? 'sun'} />
        <div className="scrim">
          <p className="quote">{quote || 'Welcome home.'}</p>
          <div className="cap">{cap}</div>
          <div className="acts">
            {mode === 'morning' && !skipped && <>
              <Btn id="act-start" initial className="primary" onClick={() => setOverlay('morning')}>Start our morning</Btn>
              <Btn id="act-step" onClick={() => setOverlay('morning')}>Choose today’s step</Btn>
              <Btn id="act-skip" className="ghost" onClick={() => setSkipped(true)}>Skip</Btn>
            </>}
            {mode === 'evening' && <Btn id="act-wind" initial className="primary" onClick={() => setOverlay('bedtime')}>Wind down together</Btn>}
            {(mode === 'home' || (mode === 'morning' && skipped)) && <Btn id="act-watch" initial className="primary" onClick={() => go('watch')}>Watch Together</Btn>}
            {mode === 'evening' && <Btn id="act-watch2" className="ghost" onClick={() => go('watch')}>Watch Together</Btn>}
          </div>
        </div>
      </div>
      <div className="col">
        <div className="card grow">
          <h2>{mode === 'evening' ? 'Tomorrow' : mode === 'morning' ? 'Today' : 'Today & tomorrow'}</h2>
          {guest ? <div className="guest-note">Guest view: plans are hidden.</div>
            : items.length ? items.map((u) => <div className="row" key={u.key}><span className="t">{u.when ? `${mode === 'home' ? (localDate(new Date(u.when), tz) === date ? 'Today ' : 'Tomorrow ') : ''}${fmtTime(u.when, tz)}` : 'To do'}</span><span>{u.title}</span></div>)
              : <div className="empty">Nothing planned. Add something from your phone.</div>}
        </div>
        <div className="card">
          <h2>For us</h2>
          {forUs ? <div><div className="dim small">{forUs.l}</div><div className="clamp2">{forUs.t}</div></div> : <div className="empty">A shared note or a small step will show up here.</div>}
        </div>
      </div>
    </div>
    <div className="strip">
      {appsOf(snap).slice(0, 6).map((a) => <Btn key={a.id} id={`app-${a.id}`} onClick={() => platform.launchApp(a.id)}>{a.label}</Btn>)}
    </div>
  </>
}

function Detail({ item, onClose }: { item: WatchItem; onClose: () => void }) {
  const { snap, platform } = useApp()
  useLayer('detail', true, onClose)
  const e = item.entry
  return (
    <div className="overlay"><div className="panel">
      <h2>{e.title}</h2>
      <div className="dim small">{e.type === 'series' ? 'Series' : 'Movie'} · {e.runtimeMin ? `${e.runtimeMin} min${e.type === 'series' ? ' / episode' : ''}` : 'Runtime unknown'} · {e.service ?? 'Service not set'}</div>
      <p>{e.summary}</p>
      <div className="presets">{snap.household.people.map((p) => <span key={p.id} className={`pill ${item.prefs[p.id] ?? ''}`}>{p.name}: {item.prefs[p.id] ?? 'no vote'}</span>)}</div>
      <div className="presets">
        <Btn id="d-open" scope="detail" initial className="primary" onClick={() => e.service && platform.launchApp(e.service.toLowerCase())}>Open app</Btn>
        <Btn id="d-close" scope="detail" className="ghost" onClick={onClose}>Back</Btn>
      </div>
      <div className="credit">Availability hints may be out of date. Data from TMDB · Provider data from JustWatch. This product uses the TMDB API but is not endorsed or certified by TMDB.</div>
    </div></div>
  )
}

const cyc = <T,>(arr: T[], cur: T) => arr[(arr.indexOf(cur) + 1) % arr.length]
export function Watch() {
  const { snap } = useApp()
  const members = snap.household.people.map((p) => p.id)
  const [f, setF] = useState<Filters>({})
  const [detail, setDetail] = useState<WatchItem | null>(null)
  const cands: Candidate[] = useMemo(() => snap.watch.map((w) => ({ entry: w.entry, prefs: w.prefs })), [snap.watch])
  const byId = (id: string) => snap.watch.find((w) => w.entry.id === id)!
  const matches = topMatches(cands, members, f)
  const moods = [undefined, ...new Set(snap.watch.map((w) => w.entry.mood).filter(Boolean))] as (string | undefined)[]
  return <>
    <div className="filters">
      <Btn id="f-type" className="chip" onClick={() => setF({ ...f, type: cyc([undefined, 'movie', 'series'] as const, f.type) })}>Type: {f.type ?? 'Any'}</Btn>
      <Btn id="f-time" className="chip" onClick={() => setF({ ...f, maxMinutes: cyc([undefined, 60, 90, 120, 180], f.maxMinutes) })}>Time: {f.maxMinutes ? `≤ ${f.maxMinutes} min` : 'Any'}</Btn>
      <Btn id="f-mood" className="chip" onClick={() => setF({ ...f, mood: cyc(moods, f.mood) })}>Mood: {f.mood ?? 'Any'}</Btn>
      <Btn id="f-pick" initial className="primary chip" onClick={() => { const p = pickForUs(cands, members, f); if (p) setDetail(byId(p.entry.id)) }}>Pick for us</Btn>
    </div>
    <div className="scroll-free">
      {matches.length ? <div className="grid3">{matches.map((m) => (
        <Btn key={m.entry.id} id={`w-${m.entry.id}`} className="tile" onClick={() => setDetail(byId(m.entry.id))}>
          <span className="st">{m.entry.type} · {m.entry.service}</span>
          <span className="h">{m.entry.title}</span>
          <span className="dim small">{m.entry.runtimeMin ? `${m.entry.runtimeMin} min` : 'Runtime unknown'}</span>
          <span className="presets">{members.map((id) => <span key={id} className={`pill ${m.prefs[id] ?? ''}`}>{snap.household.people.find((p) => p.id === id)?.name}: {m.prefs[id] ?? '–'}</span>)}</span>
        </Btn>))}</div>
        : <div className="card"><h2>Nothing matches</h2>{explainEmpty(cands, members, f).map((t) => <div key={t} className="small">{t}</div>)}</div>}
    </div>
    {detail && <Detail item={detail} onClose={() => setDetail(null)} />}
  </>
}

export function Us() {
  const { snap, guest, tz, toggleTask } = useApp()
  const tabs = ['This Week', 'Home Tasks', 'Our Dreams', 'Notes'] as const
  const [tab, setTab] = useState<(typeof tabs)[number]>('This Week')
  if (guest) return <div className="card"><div className="guest-note">Guest view: personal content is hidden.</div></div>
  return <>
    <div className="tabs">{tabs.map((t) => <Btn key={t} id={`tab-${t}`} initial={t === 'This Week'} className={`chip ${tab === t ? 'cur' : ''}`} onClick={() => setTab(t)}>{t}</Btn>)}</div>
    <div className="scroll-free list">
      {tab === 'This Week' && (snap.events.length ? snap.events.map((e) => <div className="card item" key={e.id}><span className="dim" style={{ width: 380, whiteSpace: 'nowrap' }}>{fmtDay(e.at, tz)}{e.allDay ? '' : ` · ${fmtTime(e.at, tz)}`}</span>{e.title}</div>) : <div className="empty">Nothing planned this week.</div>)}
      {tab === 'Home Tasks' && snap.tasks.map((t) => (
        <Btn key={t.id} id={`task-${t.id}`} className={`item ${t.done ? 'done' : ''}`} style={{ width: '100%' }} onClick={() => toggleTask(t.id)}>
          <span className="box">{t.done ? '✓' : ''}</span><span className="lbl">{t.title}</span><span className="dim small" style={{ marginLeft: 'auto' }}>{t.kind === 'grocery' ? 'Grocery · ' : ''}{personName(snap, t.owner)}</span>
        </Btn>))}
      {tab === 'Our Dreams' && <div className="grid3" style={{ gridTemplateColumns: '1fr 1fr' }}>{snap.dreams.map((d) => (
        <div key={d.id} className="card" style={{ padding: 0, overflow: 'hidden' }}><div style={{ height: 200 }}><DreamArt kind={d.art} /></div>
          <div style={{ padding: '18px 26px' }}><div className="serif" style={{ fontSize: 36 }}>{d.title}</div><div className="dim small">{d.why}</div><div className="small" style={{ marginTop: 8 }}>Next: {d.nextStep}</div></div></div>))}</div>}
      {tab === 'Notes' && snap.notes.map((n) => <div className="card item" key={n.id}><span>“{n.text}”</span><span className="dim small" style={{ marginLeft: 'auto' }}>{personName(snap, n.author)}</span></div>)}
    </div>
  </>
}

export function Ideas() {
  const { snap, guest } = useApp()
  const [page, setPage] = useState(0)
  const shown = snap.ideas.filter((i) => i.status !== 'archived').sort((a, b) => Number(!!b.pinned) - Number(!!a.pinned))
  const pages = Math.max(1, Math.ceil(shown.length / 6))
  if (guest) return <div className="card"><div className="guest-note">Guest view: ideas are hidden.</div></div>
  return <>
    <div className="scroll-free"><div className="grid3 fill">{shown.slice(page * 6, page * 6 + 6).map((i, k) => (
      <Btn key={i.id} id={`idea-${i.id}`} initial={k === 0} className="tile">
        <span className="st">{i.pinned ? '★ ' : ''}{i.status} · {personName(snap, i.author)}</span><span className="h clamp2">{i.title}</span><span className="dim small">{i.note}</span>
      </Btn>))}</div></div>
    {pages > 1 && <div className="presets">
      <Btn id="ideas-prev" className="chip ghost" onClick={() => setPage((p) => (p + pages - 1) % pages)}>Previous</Btn>
      <span className="dim small" style={{ alignSelf: 'center' }}>Page {page + 1} of {pages}</span>
      <Btn id="ideas-next" className="chip ghost" onClick={() => setPage((p) => (p + 1) % pages)}>Next</Btn>
    </div>}
  </>
}

export function Settings() {
  const { snap, ctrl, setOverlay, platform, live } = useApp()
  const [confirmUnpair, setConfirmUnpair] = useState(false)
  const rows: [string, string][] = [
    ['Household', `${snap.household.name} · ${snap.household.people.map((p) => p.name).join(', ')}`],
    ['Timezone', snap.household.tz],
    ['Timer path', `${ctrl.label}${ctrl.verified ? '' : ' (not yet verified on this TV)'}`],
    ['Weather', 'Weather by Open-Meteo'],
    ['Data', live ? `Household cloud · cache: ${live.cacheBackend || 'starting'}` : 'Sample data (simulation)'],
    ['Last sync', new Date(snap.syncedAt).toLocaleTimeString()],
    ['Volume, sound, picture', 'Not shown: only controls verified on this TV appear in Quick controls.'],
  ]
  return <>
    <div className="card">{rows.map(([a, b]) => <div className="row" key={a}><span className="t">{a}</span><span>{b}</span></div>)}</div>
    <div className="presets">
      {!confirmUnpair
        ? <Btn id="set-unpair" className="ghost" onClick={() => setConfirmUnpair(true)}>Unpair this TV</Btn>
        : <><span className="small dim" style={{ alignSelf: 'center' }}>This TV will forget the household.</span>
            <Btn id="set-unpair-no" initial className="ghost" onClick={() => setConfirmUnpair(false)}>Keep paired</Btn>
            <Btn id="set-unpair-yes" className="ghost" onClick={() => (live ? void live.unpair() : setOverlay('pairing'))}>Yes, unpair</Btn></>}
    </div>
  </>
}

const phoneUrl = (import.meta.env.VITE_PHONE_URL as string | undefined) ?? 'https://vhome.example'

function PairCard({ code, note, onBack }: { code: string; note: string; onBack?: () => void }) {
  const svg = useMemo(() => { const q = qrcode(0, 'M'); q.addData(`${phoneUrl}/?code=${code}`); q.make(); return q.createSvgTag({ cellSize: 6, margin: 0, scalable: true }) }, [code])
  return (
    <div className="panel" style={{ flexDirection: 'row', gap: 60, alignItems: 'center' }}>
      <div><h2>Pair this TV</h2><p className="dim">On your phone, open V/HOME, then Displays, and enter this code or scan the QR.</p><div className="code">{code || '…'}</div>
        <div className="dim small">{note}</div>
        {onBack && <div className="presets" style={{ marginTop: 16 }}><Btn id="pair-close" scope="pairing" initial onClick={onBack}>Back</Btn></div>}</div>
      <div className="qr" dangerouslySetInnerHTML={{ __html: svg }} />
    </div>
  )
}

/** Simulation preview opened from Settings. */
export function Pairing({ onClose }: { onClose: () => void }) {
  useLayer('pairing', true, onClose)
  return <div className="overlay"><PairCard code="K7M2QX" note="Simulation code. The real code expires after 10 minutes." onBack={onClose} /></div>
}

/** Live: shown whenever this TV is not paired (first run, revoked, or unpaired). */
export function PairingGate() {
  const { live } = useApp()
  return <div className="app" style={{ display: 'grid', placeItems: 'center' }}>
    <PairCard code={live?.code ?? ''} note={live?.status === 'booting' ? 'Connecting…' : live?.offline ? 'Cannot reach the household cloud. Retrying…' : 'The code expires after 10 minutes and refreshes on its own.'} />
  </div>
}
