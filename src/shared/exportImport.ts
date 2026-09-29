// Household export/import. Photos travel inside the file (base64) and are re-uploaded under the new household on import.
export const TABLES = ['events', 'tasks', 'notes', 'dreams', 'dream_steps', 'ideas', 'watch_entries', 'quotes'] as const
export type Table = (typeof TABLES)[number]
export interface ExportedPhoto { path: string; base64: string; showOnTv: boolean }
export interface ExportFile { version: 1; exportedAt: string; media?: ExportedPhoto[]; household: { name: string; timezone: string; settings: Record<string, unknown> }; rows: Record<Table, Record<string, unknown>[]> }

export const buildExport = (household: ExportFile['household'], rows: Partial<Record<Table, Record<string, unknown>[]>>, now = new Date(), media: ExportedPhoto[] = []): ExportFile => ({
  version: 1, exportedAt: now.toISOString(), household, media,
  rows: Object.fromEntries(TABLES.map((t) => [t, rows[t] ?? []])) as ExportFile['rows'],
})

const DROP = ['id', 'household_id', 'author_id', 'created_at', 'updated_at', 'revision', 'poster_path']
/** New IDs, current household + author. dream_steps.dream_id is remapped; unknown parents drop the step. */
export function remapImport(f: ExportFile, hh: string, author: string, newId: () => string = () => crypto.randomUUID()) {
  if (f.version !== 1) throw new Error('Unsupported export version')
  const dreamIds = new Map<string, string>()
  const out: { table: Table; row: Record<string, unknown> }[] = []
  const photos: (ExportedPhoto & { newPath: string })[] = []
  const byPath = new Map((f.media ?? []).map((m) => [m.path, m]))
  for (const t of TABLES) {
    for (const r of f.rows[t] ?? []) {
      const id = newId()
      if (t === 'dreams') dreamIds.set(String(r.id), id)
      const row: Record<string, unknown> = { ...Object.fromEntries(Object.entries(r).filter(([k]) => !DROP.includes(k))), id, household_id: hh, author_id: author }
      // a photo is kept only when its bytes are in the file; otherwise the row imports without one
      const old = typeof r.image_path === 'string' ? byPath.get(r.image_path) : undefined
      if (old) { const newPath = `${hh}/${newId()}.jpg`; row.image_path = newPath; photos.push({ ...old, newPath }) } else delete row.image_path
      if (t === 'dream_steps') {
        const parent = dreamIds.get(String(r.dream_id)); if (!parent) continue
        row.dream_id = parent
      }
      out.push({ table: t, row })
    }
  }
  return { items: out, photos }
}
export const previewCounts = (f: ExportFile) => Object.fromEntries(TABLES.map((t) => [t, f.rows[t]?.length ?? 0])) as Record<Table, number>

export const blobToBase64 = (b: Blob) => new Promise<string>((res, rej) => { const r = new FileReader(); r.onload = () => res(String(r.result).split(',')[1] ?? ''); r.onerror = () => rej(r.error); r.readAsDataURL(b) })
export const base64ToBlob = (b64: string, type = 'image/jpeg') => { const bin = atob(b64); const u = new Uint8Array(bin.length); for (let i = 0; i < bin.length; i++) u[i] = bin.charCodeAt(i); return new Blob([u], { type }) }
