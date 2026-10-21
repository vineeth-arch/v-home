// Layout editor for the launcher: edits a local draft; Save writes it, Back/Cancel discards it.
import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { useApp } from './state'
import { useFocusable, useFocusCtx, useLayer } from './FocusProvider'
import { iconUrl, type CatalogEntry } from '../shared/catalog'
import { MAX_FAVORITES, deleteFolder, moveToFolder, toggleFavorite, toggleHidden, type Folder, type LauncherPrefs } from '../shared/launcherPrefs'
import { fnv1a } from '../shared/daily'

export const FOLDER_NAMES = ['Streaming', 'Music', 'Kids', 'Games', 'Sports', 'Other']

// ---- draft mutations (local stand-ins for the shared layout helpers; tiny and pure) ----
export const folderOf = (p: LauncherPrefs, id: string) => p.folders.find((f) => f.apps.includes(id))
/** App ids (not system, not inputs) in grid order: p.order first, the rest in catalog order. */
export function orderedIds(entries: CatalogEntry[], p: LauncherPrefs): string[] {
  const ids = entries.filter((e) => e.kind === 'app' && !e.system).map((e) => e.id)
  const rank = (id: string) => { const i = p.order.indexOf(id); return i < 0 ? Infinity : i }
  return [...ids].sort((a, b) => rank(a) - rank(b) || ids.indexOf(a) - ids.indexOf(b))
}
export function moveStep(p: LauncherPrefs, entries: CatalogEntry[], id: string, dir: -1 | 1): LauncherPrefs {
  const ids = orderedIds(entries, p)
  const visible = ids.filter((i) => !p.hidden.includes(i) && !folderOf(p, i))
  const at = visible.indexOf(id), nb = visible[at + dir]
  if (at < 0 || nb === undefined) return p
  const a = ids.indexOf(id), b = ids.indexOf(nb)
  const next = [...ids]; next[a] = nb; next[b] = id
  return { ...p, order: next }
}
export function createFolder(p: LauncherPrefs): LauncherPrefs {
  const used = p.folders.map((f) => f.name)
  const name = FOLDER_NAMES.find((n) => !used.includes(n)) ?? `Folder ${p.folders.length + 1}`
  let n = p.folders.length + 1; while (p.folders.some((f) => f.id === `f${n}`)) n++
  return { ...p, folders: [...p.folders, { id: `f${n}`, name, apps: [] }] }
}
export function renameFolder(p: LauncherPrefs, folderId: string): LauncherPrefs {
  const f = p.folders.find((x) => x.id === folderId); if (!f) return p
  const at = FOLDER_NAMES.indexOf(f.name), others = p.folders.filter((x) => x.id !== folderId).map((x) => x.name)
  const cycle = FOLDER_NAMES.map((_, i) => FOLDER_NAMES[(at + 1 + i) % FOLDER_NAMES.length])
  const name = cycle.find((n) => !others.includes(n)) ?? cycle[0]
  return { ...p, folders: p.folders.map((x) => (x.id === folderId ? { ...x, name } : x)) }
}
// ---- shared bits ----
export function AppIcon({ entry, size = 64 }: { entry: CatalogEntry; size?: number }) {
  const url = iconUrl(entry)
  const [failed, setFailed] = useState(false)
  const style = { '--s': `${size}px`, '--h': fnv1a(entry.id) % 360 } as React.CSSProperties
  if (url && !failed) return <img className="l-ico" style={style} src={url} alt="" onError={() => setFailed(true)} />
  return <span className="l-ico letter" style={style} aria-hidden>{(entry.title.trim()[0] ?? '?').toUpperCase()}</span>
}

export function LBtn({ id, scope, initial, className = '', onClick, children, disabled }:
  { id: string; scope: string; initial?: boolean; className?: string; onClick: () => void; children: ReactNode; disabled?: boolean }) {
  const { className: fc, ...fp } = useFocusable(id, { scope, initial })
  return <button {...fp} className={`${fc} l-btn ${className}`} onClick={onClick} aria-disabled={disabled || undefined}>{children}</button>
}

const SCOPE = 'launcher-edit'

export function LauncherEdit({ onClose }: { onClose: () => void }) {
  const { catalog, launcherPrefs, setLauncherPrefs } = useApp()
  const { focus } = useFocusCtx()
  const [draft, setDraft] = useState<LauncherPrefs>(launcherPrefs) // snapshot; the saved prefs are untouched until Save
  const [sel, setSel] = useState<string | null>(null)
  const [msg, setMsg] = useState('')
  useLayer(SCOPE, true, onClose)
  const byId = useMemo(() => new Map(catalog.map((e) => [e.id, e])), [catalog])
  const ids = orderedIds(catalog, draft)
  const selEntry = sel ? byId.get(sel) : undefined
  const selFolder = sel ? folderOf(draft, sel) : undefined
  useEffect(() => { if (sel) focus('le-act-earlier') }, [sel, focus])

  const apply = (p: LauncherPrefs, m = '') => { setDraft(p); setMsg(m) }
  const save = () => { setLauncherPrefs(draft); onClose() }
  const done = () => { const s = sel; setSel(null); setMsg(''); if (s) focus(`le-app-${s}`) }

  return (
    <div className="overlay l-edit"><div className="panel">
      <div className="l-edit-top">
        <h2>Edit layout</h2>
        <LBtn id="le-save" scope={SCOPE} className="primary" onClick={save}>Save</LBtn>
        <LBtn id="le-cancel" scope={SCOPE} onClick={onClose}>Cancel</LBtn>
      </div>
      <div className="l-edit-acts">
        {selEntry ? <>
          <b className="l-edit-sel">{selEntry.title}</b>
          <LBtn id="le-act-earlier" scope={SCOPE} onClick={() => apply(moveStep(draft, catalog, selEntry.id, -1))}>Move earlier</LBtn>
          <LBtn id="le-act-later" scope={SCOPE} onClick={() => apply(moveStep(draft, catalog, selEntry.id, 1))}>Move later</LBtn>
          <LBtn id="le-act-fav" scope={SCOPE} onClick={() => apply(toggleFavorite(draft, selEntry.id), !draft.favorites.includes(selEntry.id) && draft.favorites.length >= MAX_FAVORITES ? 'Favorites are full (6).' : '')}>
            {draft.favorites.includes(selEntry.id) ? 'Remove favorite' : 'Add favorite'}</LBtn>
          <LBtn id="le-act-hide" scope={SCOPE} onClick={() => apply(toggleHidden(draft, selEntry.id))}>{draft.hidden.includes(selEntry.id) ? 'Unhide' : 'Hide'}</LBtn>
          {selFolder && <LBtn id="le-act-out" scope={SCOPE} onClick={() => apply(moveToFolder(draft, selEntry.id, null))}>Out of {selFolder.name}</LBtn>}
          {draft.folders.filter((f) => f.id !== selFolder?.id).map((f) => <LBtn key={f.id} id={`le-act-in-${f.id}`} scope={SCOPE} onClick={() => apply(moveToFolder(draft, selEntry.id, f.id))}>Into {f.name}</LBtn>)}
          <LBtn id="le-act-done" scope={SCOPE} className="ghost" onClick={done}>Done</LBtn>
        </> : <span className="l-dim">Choose an app below to move, hide or file it.</span>}
      </div>
      <div className="l-edit-folders">
        <span className="l-dim">Folders</span>
        {draft.folders.map((f: Folder) => <span key={f.id} className="l-edit-folder">
          <b>{f.name} ({f.apps.length})</b>
          <LBtn id={`le-fr-${f.id}`} scope={SCOPE} onClick={() => apply(renameFolder(draft, f.id))}>Rename</LBtn>
          <LBtn id={`le-fd-${f.id}`} scope={SCOPE} onClick={() => { apply(deleteFolder(draft, f.id), `${f.name} deleted; its apps are back in the grid.`) }}>Delete</LBtn>
        </span>)}
        <LBtn id="le-newfolder" scope={SCOPE} onClick={() => apply(createFolder(draft))}>New folder</LBtn>
      </div>
      <div className="l-edit-msg" role="status">{msg}</div>
      <div className="l-edit-list">
        {ids.map((id, i) => {
          const e = byId.get(id)!, f = folderOf(draft, id)
          const tags = [draft.favorites.includes(id) && 'Favorite', draft.hidden.includes(id) && 'Hidden', f?.name].filter(Boolean).join(' · ')
          return <LBtn key={id} id={`le-app-${id}`} scope={SCOPE} initial={i === 0} className={`l-edit-app${sel === id ? ' sel' : ''}${draft.hidden.includes(id) ? ' off' : ''}`} onClick={() => { setSel(id); setMsg('') }}>
            <AppIcon entry={e} size={44} /><span className="l-edit-name"><span className="ttl">{e.title}</span>{tags && <span className="l-dim tag">{tags}</span>}</span>
          </LBtn>
        })}
      </div>
    </div></div>
  )
}
