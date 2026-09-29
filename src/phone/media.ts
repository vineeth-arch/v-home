import { getClient } from '../shared/supabase'
import { resizeToJpeg } from '../shared/image'

const BUCKET = 'household-media'
const c = () => getClient()

/** Resize, record the media row, then upload. If the upload fails the row is removed (nothing dangling). */
export async function uploadPhoto(hh: string, file: Blob, showOnTv: boolean, extra: { taken_on?: string | null; caption?: string | null } = {}): Promise<string> {
  const jpeg = await resizeToJpeg(file)
  const path = `${hh}/${crypto.randomUUID()}.jpg`
  const ins = await c().from('media').insert({ path, household_id: hh, show_on_tv: showOnTv, ...extra })
  if (ins.error) throw new Error(ins.error.message)
  const up = await c().storage.from(BUCKET).upload(path, jpeg, { contentType: 'image/jpeg' })
  if (up.error) { await c().from('media').delete().eq('path', path); throw new Error(up.error.message) }
  return path
}

/** Best effort: an orphan is harmless but wasteful, so failures are swallowed. */
export async function deletePhoto(path: string | null | undefined) {
  if (!path) return
  try { await c().storage.from(BUCKET).remove([path]); await c().from('media').delete().eq('path', path) } catch { /* ignore */ }
}

export async function setPhotoOnTv(path: string | null | undefined, show: boolean) {
  if (!path) return
  await c().from('media').update({ show_on_tv: show }).eq('path', path)
}

/** path -> 1 hour signed URL. Missing or forbidden files are simply absent from the map. */
export async function signedUrls(paths: string[]): Promise<Record<string, string>> {
  const uniq = [...new Set(paths.filter(Boolean))]
  if (!uniq.length) return {}
  const r = await c().storage.from(BUCKET).createSignedUrls(uniq, 3600)
  const out: Record<string, string> = {}
  for (const x of r.data ?? []) if (x.path && x.signedUrl) out[x.path] = x.signedUrl
  return out
}

export async function downloadPhoto(path: string): Promise<Blob | null> {
  const r = await c().storage.from(BUCKET).download(path); return r.data ?? null
}

/** Import: put already-encoded bytes at a chosen path (no re-encode) and record its media row. */
export async function restorePhoto(hh: string, path: string, blob: Blob, showOnTv: boolean) {
  const ins = await c().from('media').insert({ path, household_id: hh, show_on_tv: showOnTv })
  if (ins.error) throw new Error(ins.error.message)
  const up = await c().storage.from(BUCKET).upload(path, blob, { contentType: 'image/jpeg' })
  if (up.error) { await c().from('media').delete().eq('path', path); throw new Error(up.error.message) }
}
