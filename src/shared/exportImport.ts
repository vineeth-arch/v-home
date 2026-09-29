// Household export/import. Media bytes are not included yet (image_path values are dropped on import).
export const TABLES = ['events', 'tasks', 'notes', 'dreams', 'dream_steps', 'ideas', 'watch_entries', 'quotes'] as const
export type Table = (typeof TABLES)[number]
export interface ExportFile { version: 1; exportedAt: string; household: { name: string; timezone: string; settings: Record<string, unknown> }; rows: Record<Table, Record<string, unknown>[]> }

export const buildExport = (household: ExportFile['household'], rows: Partial<Record<Table, Record<string, unknown>[]>>, now = new Date()): ExportFile => ({
  version: 1, exportedAt: now.toISOString(), household,
  rows: Object.fromEntries(TABLES.map((t) => [t, rows[t] ?? []])) as ExportFile['rows'],
})

const DROP = ['id', 'household_id', 'author_id', 'created_at', 'updated_at', 'revision', 'image_path', 'poster_path']
/** New IDs, current household + author. dream_steps.dream_id is remapped; unknown parents drop the step. */
export function remapImport(f: ExportFile, hh: string, author: string, newId: () => string = () => crypto.randomUUID()) {
  if (f.version !== 1) throw new Error('Unsupported export version')
  const dreamIds = new Map<string, string>()
  const out: { table: Table; row: Record<string, unknown> }[] = []
  for (const t of TABLES) {
    for (const r of f.rows[t] ?? []) {
      const id = newId()
      if (t === 'dreams') dreamIds.set(String(r.id), id)
      const row: Record<string, unknown> = { ...Object.fromEntries(Object.entries(r).filter(([k]) => !DROP.includes(k))), id, household_id: hh, author_id: author }
      if (t === 'dream_steps') {
        const parent = dreamIds.get(String(r.dream_id)); if (!parent) continue
        row.dream_id = parent
      }
      out.push({ table: t, row })
    }
  }
  return out
}
export const previewCounts = (f: ExportFile) => Object.fromEntries(TABLES.map((t) => [t, f.rows[t]?.length ?? 0])) as Record<Table, number>
