// Launcher home. Reads catalog/prefs from useApp(); never needs pairing or network.
import { useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from 'react'
import './launcher.css'
import { useApp } from './state'
import { useFocusable, useFocusCtx, useLayer } from './FocusProvider'
import { Btn, fmtTime } from './ui'
import { useTimerActions } from './timerActions'
import { AppIcon, LauncherEdit } from './LauncherEdit'
import { fnv1a } from '../shared/daily'
import { applyLayout, MAX_FAVORITES, WALLPAPERS, type Folder } from '../shared/launcherPrefs'
import { bundledCatalog, iconUrl, type CatalogEntry } from '../shared/catalog'
import { pickDaily } from '../shared/reflections'
import { localDate } from '../shared/daily'
import { sharedNote } from '../shared/partnerNotes'

// Ids match the shared WALLPAPERS list (WS-B); kept here so this file compiles on its own.
export const WALLPAPER_PRESETS = WALLPAPERS.map((id) => ({ id, label: id[0].toUpperCase() + id.slice(1) }))
const FOCUS_KEY = 'vhomeLauncher.lastFocus'
const readFocus = () => { try { return sessionStorage.getItem(FOCUS_KEY) } catch { return null } }
const writeFocus = (id: string) => { try { sessionStorage.setItem(FOCUS_KEY, id) } catch { /* private mode */ } }

function Tile({ id, scope, initial, className = '', onClick, children }: { id: string; scope?: string; initial?: boolean; className?: string; onClick: () => void; children: ReactNode }) {
  const { className: fc, ref, ...fp } = useFocusable(id, { scope, initial })
  return <button ref={ref} {...fp} className={`${fc} l-tile ${className}`} onClick={onClick}>{children}</button>
}

const tint = (e: CatalogEntry) => e.color ?? `hsl(${fnv1a(e.id) % 360} 30% 28%)`

/** Big colour-filled square: the icon's own edge colour is the background, so the tile looks like the app. */
function Art({ entry, small }: { entry: CatalogEntry; small?: boolean }) {
  const url = iconUrl(entry)
  const [failed, setFailed] = useState(false)
  return <span className={`l-art${small ? ' small' : ''}`} style={{ '--c': tint(entry) } as CSSProperties}>
    {url && !failed ? <img src={url} alt="" onError={() => setFailed(true)} />
      : <span className="l-letter" aria-hidden>{(entry.title.trim()[0] ?? '?').toUpperCase()}</span>}
  </span>
}

function AppTile({ entry, idPrefix, scope, initial, onOpen }: { entry: CatalogEntry; idPrefix: string; scope?: string; initial: boolean; onOpen: (e: CatalogEntry) => void }) {
  return <Tile id={`${idPrefix}-${entry.id}`} scope={scope} initial={initial} className={entry.unavailable ? 'off' : ''} onClick={() => onOpen(entry)}>
    <Art entry={entry} />
    <span className="l-lbl"><span className="ttl">{entry.title}</span>{entry.unavailable && <span className="sub">Not on this TV</span>}</span>
  </Tile>
}

function FolderTile({ folder, apps, initial, onOpen }: { folder: Folder; apps: CatalogEntry[]; initial: boolean; onOpen: () => void }) {
  return <Tile id={`l-folder-${folder.id}`} initial={initial} onClick={onOpen}>
    <span className="l-art l-folder-art"><span className="l-mini">{[0, 1, 2, 3].map((i) => apps[i]
      ? <span key={apps[i].id} className="l-mini-ico"><Art entry={apps[i]} small /></span>
      : <span key={i} className="l-mini-ico empty" />)}</span></span>
    <span className="l-lbl"><span className="ttl">{folder.name}</span><span className="sub">{apps.length === 1 ? '1 app' : `${apps.length} apps`}</span></span>
  </Tile>
}

function FolderOverlay({ folder, apps, onClose, onOpen }: { folder: Folder; apps: CatalogEntry[]; onClose: () => void; onOpen: (e: CatalogEntry) => void }) {
  useLayer('launcher-folder', true, onClose)
  return <div className="overlay l-folder"><div className="panel">
    <h2>{folder.name}</h2>
    {apps.length ? <div className="l-grid">{apps.map((a, i) => <AppTile key={a.id} entry={a} idPrefix="lf" scope="launcher-folder" initial={i === 0} onOpen={onOpen} />)}</div>
      : <div className="l-dim">Nothing in this folder yet. Use Edit to add apps.</div>}
    <div className="presets"><Btn id="lf-back" scope="launcher-folder" className="ghost" onClick={onClose}>Back</Btn></div>
  </div></div>
}

/** Today's reflection (same pick as Our Home) plus the shared note or next small step. Hidden for guests and unpaired TVs. */
function PersonalCard() {
  const { snap, now, tz, mode, guest } = useApp()
  const empty = !snap.household.people.length && !snap.dreams.length && !snap.notes.length
  if (guest || empty) return null
  const refl = pickDaily(snap.household.id || snap.household.name, localDate(now, tz), mode === 'evening' ? 'evening' : 'morning', snap.household.hiddenReflections, snap.quotes)
  const note = sharedNote(snap.notes), step = snap.dreams[0]
  const side = note ? { l: 'A note', t: note.text } : step ? { l: 'A small step', t: step.nextStep } : null
  if (!refl && !side) return null
  const cap = refl ? (refl.author ? `${refl.author}${refl.source ? `, ${refl.source}` : ''}` : /^[me]\d+$/.test(refl.id) ? 'Original reflection' : 'Ours') : ''
  return <div className="l-card">
    {refl && <div className="l-quote"><p>{refl.text}</p><div className="l-dim">{cap}</div></div>}
    {side && <div className="l-side"><div className="l-dim">{side.l}</div><div className="clamp2">{side.t}</div></div>}
  </div>
}

const PRESETS = [15, 30, 45, 60, 90]
/** Sleep-timer shortcuts, always on screen at the right. Uses the same adapter and honest messages as Quick controls. */
function TimerPanel() {
  const { timerState, now, tz } = useApp()
  const { msg, run, verified } = useTimerActions()
  const status = timerState === 'unavailable' ? 'Timer status unavailable'
    : timerState.scheduled ? `TV off at ${fmtTime(timerState.shutdownAt, tz)} · ${Math.max(0, Math.ceil((timerState.shutdownAt - now.getTime()) / 60000))} min left` : 'No timer set'
  return <aside className="l-timer" aria-label="Sleep timer">
    <div className="l-h"><span>Sleep timer</span></div>
    <div className="l-tstatus">{status}</div>
    <div className="l-tbtns">
      {PRESETS.map((m) => <Tile key={m} id={`l-t-${m}`} className="l-tbtn" onClick={() => void run((a) => a.schedule(m))}><b>{m}</b><span>min</span></Tile>)}
    </div>
    <Tile id="l-t-cancel" className="l-tbtn wide ghost" onClick={() => void run((a) => a.cancel())}>Cancel timer</Tile>
    <div className={`l-tmsg${msg?.warn ? ' warn' : ''}`} role="status">{msg?.text ?? (verified ? '' : 'Not yet verified on this TV')}</div>
  </aside>
}

export function Launcher() {
  const { catalog, launcherPrefs: prefs, launch } = useApp()
  const { focusedId } = useFocusCtx()
  const [editing, setEditing] = useState(false)
  const [openFolder, setOpenFolder] = useState<string | null>(null)
  const layout = useMemo(() => applyLayout(catalog, prefs), [catalog, prefs])
  const { dock, inputs, folders } = layout
  const grid = useMemo(() => layout.grid.filter((e) => !dock.some((d) => d.id === e.id)), [layout.grid, dock]) // favorites are already shown above

  useEffect(() => { // wallpaper is painted on <html> so it fills the screen behind the shell's header and nav
    document.documentElement.dataset.lWall = prefs.wallpaper
    return () => { delete document.documentElement.dataset.lWall }
  }, [prefs.wallpaper])
  useEffect(() => { if (focusedId && /^l-(dock|app|folder|input)-/.test(focusedId)) writeFocus(focusedId) }, [focusedId])

  const open = (e: CatalogEntry) => { if (!e.unavailable) void launch(e.id, e.title) }
  const order = [...dock.map((e) => `l-dock-${e.id}`), ...folders.map((f) => `l-folder-${f.folder.id}`), ...grid.map((e) => `l-app-${e.id}`), ...inputs.map((e) => `l-input-${e.id}`)]
  // decided once per mount: a changing `initial` re-registers tiles and steals focus mid-navigation
  const [saved] = useState(readFocus)
  const [initialId] = useState(() => (saved && order.includes(saved) ? saved : order[0]))
  const dockSlots = Array.from({ length: Math.min(MAX_FAVORITES, Math.max(5, dock.length)) }, (_, i) => dock[i])
  const folder = folders.find((f) => f.folder.id === openFolder)

  const scroller = useRef<HTMLDivElement>(null)
  useEffect(() => { // moving up into a section's first row brings its heading (or the very top) into view
    const el = document.querySelector<HTMLElement>('.launcher [data-focused]'), sc = scroller.current
    const sec = el?.closest<HTMLElement>('section')
    if (!el || !sc || !sec) return
    if (sec.dataset.first) { if (el.offsetTop - sec.offsetTop < 240) sc.scrollTop = 0; return }
    if (el.offsetTop - sec.offsetTop < 240 && sc.scrollTop > sec.offsetTop - 12) sc.scrollTop = Math.max(0, sec.offsetTop - 12)
  }, [focusedId])

  return <div className="launcher" data-wallpaper={prefs.wallpaper} data-motion={prefs.reducedMotion ? 'reduced' : 'full'}>
    <div className="l-scroll" ref={scroller}>
      <PersonalCard />
      <section className="l-sec" data-first="1">
        <div className="l-h"><span>Favorites</span><Tile id="l-edit" className="chip" onClick={() => setEditing(true)}>Edit</Tile></div>
        <div className="l-grid">{dockSlots.map((e, i) => e
          ? <AppTile key={e.id} entry={e} idPrefix="l-dock" initial={`l-dock-${e.id}` === initialId} onOpen={open} />
          : <div key={`s${i}`} className="l-slot" aria-hidden />)}</div>
      </section>
      {folders.length > 0 && <section className="l-sec">
        <div className="l-h"><span>Folders</span><span className="l-count">{folders.length}</span></div>
        <div className="l-grid">{folders.map((f) => <FolderTile key={f.folder.id} folder={f.folder} apps={f.apps} initial={`l-folder-${f.folder.id}` === initialId} onOpen={() => setOpenFolder(f.folder.id)} />)}</div>
      </section>}
      <section className="l-sec">
        <div className="l-h"><span>{dock.length ? 'More apps' : 'Apps'}</span><span className="l-count">{grid.length}</span></div>
        <div className="l-grid">
          {grid.map((e) => <AppTile key={e.id} entry={e} idPrefix="l-app" initial={`l-app-${e.id}` === initialId} onOpen={open} />)}
          {!grid.length && <div className="l-dim">{folders.length ? 'Everything else is in your folders.' : 'No apps yet. They appear once this TV\'s list is read.'}</div>}
        </div>
      </section>
      {inputs.length > 0 && <section className="l-sec">
        <div className="l-h"><span>Inputs</span></div>
        <div className="l-grid">{inputs.map((e) => <AppTile key={e.id} entry={e} idPrefix="l-input" initial={`l-input-${e.id}` === initialId} onOpen={open} />)}</div>
      </section>}
    </div>
    <TimerPanel />
    {folder && <FolderOverlay folder={folder.folder} apps={folder.apps} onClose={() => setOpenFolder(null)} onOpen={open} />}
    {editing && <LauncherEdit onClose={() => setEditing(false)} />}
  </div>
}

/** Settings section: appearance + layout editing entry point. */
export function LauncherSettings() {
  const { launcherPrefs: p, setLauncherPrefs, catalog } = useApp()
  const [editing, setEditing] = useState(false)
  const hidden = p.hidden.filter((id) => catalog.some((e) => e.id === id)).length
  return <div className="l-set">
    <h3>Home screen</h3>
    <div className="presets">
      {WALLPAPER_PRESETS.map((w) => <Btn key={w.id} id={`ls-wall-${w.id}`} className={`chip ${p.wallpaper === w.id ? 'on' : 'ghost'}`} onClick={() => setLauncherPrefs({ ...p, wallpaper: w.id })}>{w.label}</Btn>)}
    </div>
    <div className="presets">
      <Btn id="ls-motion" className={`chip ${p.reducedMotion ? 'on' : 'ghost'}`} onClick={() => setLauncherPrefs({ ...p, reducedMotion: !p.reducedMotion })}>Reduced motion: {p.reducedMotion ? 'On' : 'Off'}</Btn>
      <Btn id="ls-edit" className="chip" onClick={() => setEditing(true)}>Edit layout</Btn>
      <span className="dim small">Hidden apps: {hidden}</span>
      {hidden > 0 && <Btn id="ls-unhide" className="chip ghost" onClick={() => setLauncherPrefs({ ...p, hidden: [] })}>Show hidden apps</Btn>}
    </div>
    {editing && <LauncherEdit onClose={() => setEditing(false)} />}
  </div>
}

const CAP_LABEL = { supported: 'Supported', denied: 'Denied', unavailable: 'Unavailable', unverified: 'Not verified' } as const
/** Settings section: catalog version/source, system apps, capability states. */
export function Diagnostics() {
  const { catalog, capabilities } = useApp()
  const generatedAt = useMemo(() => bundledCatalog().generatedAt, [])
  const bySource = (['companion', 'tv', 'curated'] as const).map((s) => [s, catalog.filter((e) => e.source === s).length] as const).filter(([, n]) => n > 0)
  const system = catalog.filter((e) => e.system)
  const caps = Object.entries(capabilities)
  const fp = useFocusable('set-diag') // focusable so the remote can scroll Settings down to this read-only panel
  return <div {...fp} className={`${fp.className} l-set l-diag`}>
    <h3>Diagnostics</h3>
    <div className="small">Catalog: {catalog.length} entries{bySource.length ? ` (${bySource.map(([s, n]) => `${s} ${n}`).join(', ')})` : ''}. Generated: {generatedAt || 'unknown'}.</div>
    <div className="small dim">Hidden helpers: {system.length ? system.map((e) => e.title).join(', ') : 'none'}.</div>
    <div className="small">{caps.length ? caps.map(([k, v]) => `${k}: ${CAP_LABEL[v] ?? v}`).join(' · ') : 'Capabilities: none checked yet.'}</div>
    <div className="small dim">A launch the TV accepts does not prove the app opened. Check on the screen.</div>
  </div>
}
