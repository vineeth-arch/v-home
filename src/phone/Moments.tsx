import { useEffect, useState } from 'react'
import { getClient } from '../shared/supabase'
import { exifDate } from '../shared/exif'
import { UnsupportedImageError } from '../shared/image'
import { deletePhoto, setPhotoOnTv, signedUrls, uploadPhoto } from './media'

interface MediaRow { path: string; show_on_tv: boolean; taken_on: string | null; caption: string | null; created_at: string }

/** Standalone photos. With Show on TV they appear in the TV's Ambient photo frame; the date drives "On this day". */
export function Moments({ hh }: { hh: string }) {
  const [rows, setRows] = useState<MediaRow[]>([]); const [urls, setUrls] = useState<Record<string, string>>({})
  const [file, setFile] = useState<File | null>(null); const [date, setDate] = useState(''); const [caption, setCaption] = useState(''); const [tv, setTv] = useState(true)
  const [busy, setBusy] = useState(false); const [err, setErr] = useState('')
  const c = getClient()
  const load = async () => {
    const [m, d, i] = await Promise.all([
      c.from('media').select('path,show_on_tv,taken_on,caption,created_at').order('created_at', { ascending: false }),
      c.from('dreams').select('image_path'), c.from('ideas').select('image_path')])
    const attached = new Set([...(d.data ?? []), ...(i.data ?? [])].map((x) => x.image_path).filter(Boolean))
    const mine = ((m.data ?? []) as MediaRow[]).filter((x) => !attached.has(x.path))
    setRows(mine); setUrls(await signedUrls(mine.map((x) => x.path)))
  }
  useEffect(() => { void load().catch((x) => setErr(x.message)) }, [])

  const pick = async (f: File | null) => {
    setFile(f); setDate('')
    if (f) { try { setDate(exifDate(await f.arrayBuffer()) ?? '') } catch { /* no date: leave empty */ } }
  }
  const add = async () => {
    if (!file) return
    setBusy(true); setErr('')
    try {
      await uploadPhoto(hh, file, tv, { taken_on: date || null, caption: caption.trim() || null })
      setFile(null); setDate(''); setCaption(''); await load()
    } catch (x) { setErr(x instanceof UnsupportedImageError ? 'This photo format is not supported.' : (x as Error).message) } finally { setBusy(false) }
  }
  return <div><h1>Photos</h1><div className="dim">Photos marked Show on TV play in the TV's photo frame when it's idle. The date lets it show "a year ago today".</div>
    <label className="pbtn" style={{ display: 'inline-block', marginTop: 12 }}>{file ? 'Change photo' : 'Add a photo'}<input type="file" accept="image/*" hidden onChange={(e) => void pick(e.target.files?.[0] ?? null)} /></label>
    {file && <>
      <label>Photo date {date ? '(from the photo)' : '(optional)'}</label><input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
      <label>Caption (optional)</label><input value={caption} onChange={(e) => setCaption(e.target.value)} />
      <label className="chk"><input type="checkbox" checked={tv} onChange={(e) => setTv(e.target.checked)} />Show on TV</label>
      <div className="row"><button className="pbtn primary" disabled={busy} onClick={() => void add()}>{busy ? 'Uploading…' : 'Save photo'}</button></div></>}
    {err && <div className="err">{err}</div>}
    <div className="grid2" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginTop: 16 }}>{rows.map((r) => (
      <div key={r.path} className="card" style={{ padding: 8 }}>
        {urls[r.path] && <img src={urls[r.path]} alt={r.caption ?? ''} style={{ width: '100%', aspectRatio: '4/3', objectFit: 'cover', borderRadius: 10 }} />}
        <div className="dim" style={{ fontSize: 13 }}>{r.taken_on ?? 'No date'}{r.caption ? ` · ${r.caption}` : ''}</div>
        <label className="chk"><input type="checkbox" checked={r.show_on_tv} onChange={(e) => void setPhotoOnTv(r.path, e.target.checked).then(load)} />On TV</label>
        <button className="pbtn danger" onClick={() => { if (confirm('Delete this photo?')) void deletePhoto(r.path).then(load) }}>Delete</button>
      </div>))}</div>
    {rows.length === 0 && <div className="dim" style={{ marginTop: 12 }}>No photos yet.</div>}
  </div>
}
