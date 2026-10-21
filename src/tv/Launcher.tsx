// Launcher home. Reads catalog/prefs from useApp(); never needs pairing or network.
import { useEffect, useMemo, useState, type ReactNode } from 'react'
import './launcher.css'
import { useApp } from './state'
import { useFocusable, useFocusCtx, useLayer } from './FocusProvider'
import { Btn } from './ui'
import { AppIcon, LauncherEdit } from './LauncherEdit'
import { applyLayout, MAX_FAVORITES, WALLPAPERS, type Folder } from '../shared/launcherPrefs'
import { bundledCatalog, type CatalogEntry } from '../shared/catalog'
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
  const { focusedId } = useFocusCtx()
  useEffect(() => { if (focusedId === id) (ref as { current: HTMLElement | null }).current?.scrollIntoView?.({ block: 'nearest' }) }, [focusedId, id, ref])
  return <button ref={ref} {...fp} className={`${fc} l-tile ${className}`} onClick={onClick}>{children}</button>
}

function AppTile({ entry, idPrefix, scope, initial, compact, onOpen }: { entry: CatalogEntry; idPrefix: string; scope?: string; initial: boolean; compact?: boolean; onOpen: (e: CatalogEntry) => void }) {
  return <Tile id={`${idPrefix}-${entry.id}`} scope={scope} initial={initial} className={`${compact ? 'compact ' : ''}${entry.unavailable ? 'off' : ''}`} onClick={() => onOpen(entry)}>
    <AppIcon entry={entry} size={compact ? 52 : 64} />
    <span className="l-lbl"><span className="ttl">{entry.title}</span>{entry.unavailable && <span className="sub">Not on this TV</span>}</span>
  </Tile>
}

function FolderTile({ folder, apps, initial, onOpen }: { folder: Folder; apps: CatalogEntry[]; initial: boolean; onOpen: () => void }) {
  return <Tile id={`l-folder-${folder.id}`} initial={initial} onClick={onOpen}>
    <span className="l-mini">{apps.slice(0, 4).map((a) => <AppIcon key={a.id} entry={a} size={28} />)}</span>
    <span className="l-lbl"><span className="ttl">{folder.name}</span></span>
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

export function Launcher() {
  const { catalog, launcherPrefs: prefs, launch } = useApp()
  const { focusedId } = useFocusCtx()
  const [editing, setEditing] = useState(false)
  const [openFolder, setOpenFolder] = useState<string | null>(null)
  const layout = useMemo(() => applyLayout(catalog, prefs), [catalog, prefs])
  const { dock, grid, inputs, folders } = layout

  useEffect(() => { // wallpaper is painted on <html> so it fills the screen behind the shell's header and nav
    document.documentElement.dataset.lWall = prefs.wallpaper
    return () => { delete document.documentElement.dataset.lWall }
  }, [prefs.wallpaper])
  useEffect(() => { if (focusedId && /^l-(dock|app|folder|input)-/.test(focusedId)) writeFocus(focusedId) }, [focusedId])

  const open = (e: CatalogEntry) => { if (!e.unavailable) void launch(e.id, e.title) }
  const order = [...dock.map((e) => `l-dock-${e.id}`), ...folders.map((f) => `l-folder-${f.folder.id}`), ...grid.map((e) => `l-app-${e.id}`), ...inputs.map((e) => `l-input-${e.id}`)]
  const saved = readFocus()
  const initialId = saved && order.includes(saved) ? saved : order[0]
  const dockSlots = Array.from({ length: MAX_FAVORITES }, (_, i) => dock[i])
  const folder = folders.find((f) => f.folder.id === openFolder)

  return <div className="launcher" data-wallpaper={prefs.wallpaper} data-motion={prefs.reducedMotion ? 'reduced' : 'full'}>
    <PersonalCard />
    <section className="l-sec">
      <div className="l-h"><span>Favorites</span><Tile id="l-edit" className="chip" onClick={() => setEditing(true)}>Edit</Tile></div>
      <div className="l-grid">{dockSlots.map((e, i) => e
        ? <AppTile key={e.id} entry={e} idPrefix="l-dock" compact initial={`l-dock-${e.id}` === initialId} onOpen={open} />
        : <div key={`s${i}`} className="l-slot" aria-hidden />)}</div>
    </section>
    <section className="l-sec l-apps">
      <div className="l-h"><span>Apps</span></div>
      <div className="l-scroll"><div className="l-grid">
        {folders.map((f) => <FolderTile key={f.folder.id} folder={f.folder} apps={f.apps} initial={`l-folder-${f.folder.id}` === initialId} onOpen={() => setOpenFolder(f.folder.id)} />)}
        {grid.map((e) => <AppTile key={e.id} entry={e} idPrefix="l-app" initial={`l-app-${e.id}` === initialId} onOpen={open} />)}
        {!grid.length && !folders.length && <div className="l-dim">No apps yet. They appear once this TV's list is read.</div>}
      </div></div>
    </section>
    {inputs.length > 0 && <section className="l-sec">
      <div className="l-h"><span>Inputs</span></div>
      <div className="l-grid">{inputs.map((e) => <AppTile key={e.id} entry={e} idPrefix="l-input" compact initial={`l-input-${e.id}` === initialId} onOpen={open} />)}</div>
    </section>}
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
  return <div className="l-set">
    <h3>Diagnostics</h3>
    <div className="small">Catalog: {catalog.length} entries{bySource.length ? ` (${bySource.map(([s, n]) => `${s} ${n}`).join(', ')})` : ''}. Generated: {generatedAt || 'unknown'}.</div>
    <div className="small dim">Hidden helpers: {system.length ? system.map((e) => e.title).join(', ') : 'none'}.</div>
    <div className="small">{caps.length ? caps.map(([k, v]) => `${k}: ${CAP_LABEL[v] ?? v}`).join(' · ') : 'Capabilities: none checked yet.'}</div>
    <div className="small dim">A launch the TV accepts does not prove the app opened. Check on the screen.</div>
  </div>
}
