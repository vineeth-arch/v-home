import { useEffect, useMemo, useState } from 'react'
import { listRows, removeRow, saveRow, type Row } from './api'
import { missingRequired, toPayload, type Entity } from './entities'
import { deletePhoto, setPhotoOnTv, signedUrls, uploadPhoto } from './media'

const draftKey = (t: string, id: string | null) => `vhome.draft.${t}.${id ?? 'new'}`
const readDraft = (k: string): Record<string, unknown> | null => { try { const r = localStorage.getItem(k); return r ? JSON.parse(r) : null } catch { return null } }
const writeDraft = (k: string, v: Record<string, unknown> | null) => { try { v ? localStorage.setItem(k, JSON.stringify(v)) : localStorage.removeItem(k) } catch { /* private mode */ } }

function initialValues(e: Entity, r: Row | null, extra: Record<string, string[]>) {
  const v: Record<string, unknown> = {}
  for (const f of e.fields) v[f.key] = r ? (f.type === 'datetime' && r[f.key] ? String(r[f.key]).slice(0, 16) : r[f.key]) : f.defaultValue ?? (f.type === 'checkbox' ? false : '')
  return { ...v, __extra: extra }
}

function Form({ e, hh, me, row, extraOptions, onDone, onCancel, onDelete }: { e: Entity; hh: string; me: string; row: Row | null; extraOptions: Record<string, string[]>; onDone: () => void; onCancel: () => void; onDelete?: () => void }) {
  const key = draftKey(e.table, row?.id ?? null)
  const saved = useMemo(() => readDraft(key), [key])
  const [v, setV] = useState<Record<string, unknown>>(() => (saved as Record<string, unknown>) ?? initialValues(e, row, extraOptions))
  const [visibility, setVis] = useState<'draft' | 'shared'>(row?.visibility ?? 'shared')
  const [tv, setTv] = useState(row?.show_on_tv ?? !e.tvToggle)
  const [err, setErr] = useState('')
  const [conflict, setConflict] = useState<Row | null>(null)
  const [busy, setBusy] = useState(false)
  const oldPath = (row?.image_path as string | null | undefined) ?? null
  const [file, setFile] = useState<File | null>(null)
  const [removePhoto, setRemovePhoto] = useState(false)
  const [preview, setPreview] = useState<string | null>(null)
  useEffect(() => { if (!file) { setPreview(null); return } const u = URL.createObjectURL(file); setPreview(u); return () => URL.revokeObjectURL(u) }, [file])
  useEffect(() => { if (oldPath && !file) void signedUrls([oldPath]).then((m) => setPreview(m[oldPath] ?? null)) }, [oldPath, file])
  const set = (k: string, x: unknown) => { const n = { ...v, [k]: x }; setV(n); writeDraft(key, n) }

  const submit = async (base: Row | null) => {
    const miss = missingRequired(e, v)
    if (miss.length) return setErr(`Fill in: ${miss.join(', ')}`)
    setBusy(true); setErr('')
    try {
      // Photo first: a failed upload must not lose the text edit, so it stops before saving.
      const wantTv = visibility === 'shared' && tv
      let image_path: string | null | undefined
      let uploaded: string | null = null
      if (e.photo && file) { uploaded = await uploadPhoto(hh, file, wantTv); image_path = uploaded }
      else if (e.photo && removePhoto) image_path = null
      const r = await saveRow(e.table, hh, base, { ...toPayload(e, v), visibility, show_on_tv: tv, ...(image_path !== undefined ? { image_path } : {}), ...(base ? {} : { author_id: me }) })
      if ('ok' in r) {
        writeDraft(key, null)
        if (e.photo) {
          if (uploaded || removePhoto) await deletePhoto(oldPath)                    // replaced or removed: drop the old file
          else await setPhotoOnTv(oldPath, wantTv)                                   // kept: follow the Show on TV switch
        }
        onDone()
      }
      else if (uploaded) { await deletePhoto(uploaded); if ('conflict' in r) setConflict(r.conflict); else setErr('You no longer have access to this item.') }
      else if ('conflict' in r) setConflict(r.conflict)
      else setErr('You no longer have access to this item.')
    } catch (x) { setErr((x as Error).message) } finally { setBusy(false) }
  }
  const options = (f: (typeof e.fields)[number]) => (f.key === 'owner' ? ['both', ...(extraOptions.people ?? [])] : f.options ?? [])
  return (
    <div className="sheet"><div>
      <h1>{row ? `Edit ${e.label.toLowerCase()}` : `New ${e.label.toLowerCase()}`}</h1>
      {saved && <div className="dim">Draft, not saved yet. Restored from this phone.</div>}
      {e.fields.map((f) => (
        f.type === 'checkbox'
          ? <label className="chk" key={f.key}><input type="checkbox" checked={Boolean(v[f.key])} onChange={(ev) => set(f.key, ev.target.checked)} />{f.label}</label>
          : <div key={f.key}><label>{f.label}</label>
            {f.type === 'textarea' ? <textarea value={String(v[f.key] ?? '')} onChange={(ev) => set(f.key, ev.target.value)} />
              : f.type === 'select' ? <select value={String(v[f.key] ?? '')} onChange={(ev) => set(f.key, ev.target.value)}>{options(f).map((o) => <option key={o} value={o}>{o}</option>)}</select>
                : <input type={f.type === 'datetime' ? 'datetime-local' : f.type === 'date' ? 'date' : f.type === 'number' ? 'number' : 'text'} value={String(v[f.key] ?? '')} onChange={(ev) => set(f.key, ev.target.value)} />}</div>
      ))}
      {e.photo && <div><label>Photo</label>
        {preview && !removePhoto && <img src={preview} alt="" style={{ width: '100%', maxHeight: 220, objectFit: 'cover', borderRadius: 12 }} />}
        <div className="row" style={{ marginTop: 8 }}>
          <label className="pbtn" style={{ margin: 0 }}>{oldPath || file ? 'Change photo' : 'Add photo'}<input type="file" accept="image/*" hidden onChange={(ev) => { setFile(ev.target.files?.[0] ?? null); setRemovePhoto(false) }} /></label>
          {(oldPath || file) && !removePhoto && <button className="pbtn danger" onClick={() => { setFile(null); setRemovePhoto(true) }}>Remove photo</button>}
        </div>{removePhoto && <div className="dim">The photo will be removed when you save.</div>}</div>}
      <label className="chk"><input type="checkbox" checked={visibility === 'draft'} onChange={(ev) => setVis(ev.target.checked ? 'draft' : 'shared')} />Keep as my private draft</label>
      {e.tvToggle && <label className="chk"><input type="checkbox" checked={tv} disabled={visibility === 'draft'} onChange={(ev) => setTv(ev.target.checked)} />Show on TV</label>}
      {err && <div className="err">{err}</div>}
      <div className="row" style={{ marginTop: 16 }}>
        <button className="pbtn primary" disabled={busy} onClick={() => submit(row)}>{busy ? 'Saving…' : 'Save'}</button>
        <button className="pbtn" onClick={onCancel}>Cancel</button>
        {onDelete && <button className="pbtn danger" onClick={onDelete}>Delete</button>}
      </div>
      {conflict && (
        <div className="sheet"><div>
          <h1>Changed by someone else</h1>
          <div className="dim">Review before you overwrite. Nothing was lost.</div>
          <div className="diff"><div className="h">Theirs now</div><div className="h">Yours</div>
            {e.fields.map((f) => <><div key={`t${f.key}`}>{String(conflict[f.key] ?? '')}</div><div key={`m${f.key}`}>{String(v[f.key] ?? '')}</div></>)}</div>
          <div className="row"><button className="pbtn primary" onClick={() => { setConflict(null); void submit(conflict) }}>Overwrite with mine</button>
            <button className="pbtn" onClick={() => { writeDraft(key, null); onDone() }}>Use theirs</button></div>
        </div></div>
      )}
    </div></div>
  )
}

export function Crud({ e, hh, me, extraOptions = {}, decorate }: { e: Entity; hh: string; me: string; extraOptions?: Record<string, string[]>; decorate?: (r: Row) => React.ReactNode }) {
  const [rows, setRows] = useState<Row[] | null>(null)
  const [editing, setEditing] = useState<Row | 'new' | null>(null)
  const [err, setErr] = useState('')
  const [thumbs, setThumbs] = useState<Record<string, string>>({})
  const load = () => listRows(e.table).then(async (r) => { setRows(r); if (e.photo) setThumbs(await signedUrls(r.map((x) => x.image_path as string).filter(Boolean)).catch(() => ({}))) }).catch((x) => setErr(x.message))
  useEffect(() => { setRows(null); void load() }, [e.table]) // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div>
      <div className="row" style={{ justifyContent: 'space-between' }}><h1>{e.plural}</h1><button className="pbtn primary" onClick={() => setEditing('new')}>Add</button></div>
      {err && <div className="err">{err}</div>}
      {rows === null && !err && <div className="dim">Loading…</div>}
      {rows?.length === 0 && <div className="dim">Nothing here yet.</div>}
      {rows?.map((r) => (
        <div key={r.id}>
          <button className="item" onClick={() => setEditing(r)}>
            <span className={`badge ${r.visibility}`}>{r.visibility === 'draft' ? 'Private draft' : e.tvToggle ? (r.show_on_tv ? 'Shared · on TV' : 'Shared · phone only') : 'Shared'}</span>
            {e.photo && !!r.image_path && !!thumbs[r.image_path as string] && <img src={thumbs[r.image_path as string]} alt="" style={{ width: '100%', height: 120, objectFit: 'cover', borderRadius: 10, marginBottom: 6 }} />}
            <span>{e.title(r)}</span>{e.sub && <span className="sub">{e.sub(r)}</span>}
          </button>
          {decorate?.(r)}
        </div>
      ))}
      {editing && <Form e={e} hh={hh} me={me} row={editing === 'new' ? null : editing} extraOptions={extraOptions} onCancel={() => setEditing(null)} onDone={() => { setEditing(null); void load() }}
        onDelete={editing === 'new' ? undefined : async () => { if (confirm(`Delete this ${e.label.toLowerCase()}?`)) { try { await removeRow(e.table, editing.id); if (e.photo) await deletePhoto(editing.image_path as string | undefined); setEditing(null); void load() } catch (x) { setErr((x as Error).message) } } }} />}
    </div>
  )
}
