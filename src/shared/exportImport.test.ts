import { expect, test } from 'vitest'
import { buildExport, previewCounts, remapImport, type ExportFile } from './exportImport'

const f = (): ExportFile => buildExport({ name: 'H', timezone: 'UTC', settings: {} }, {
  dreams: [{ id: 'd1', title: 'Sea', image_path: 'x/y.jpg', revision: 4, author_id: 'old' }],
  dream_steps: [{ id: 's1', dream_id: 'd1', title: 'Look' }, { id: 's2', dream_id: 'missing', title: 'Orphan' }],
  events: [{ id: 'e1', title: 'Dinner', starts_at: '2026-10-01T10:00:00Z' }],
}, new Date(0))

test('import gets new ids, target household/author, drops media and revision', () => {
  let n = 0
  const out = remapImport(f(), 'HH', 'ME', () => `id${++n}`)
  const dream = out.find((o) => o.table === 'dreams')!.row
  expect(dream).toMatchObject({ id: expect.stringMatching(/^id/), household_id: 'HH', author_id: 'ME', title: 'Sea' })
  expect(dream).not.toHaveProperty('image_path'); expect(dream).not.toHaveProperty('revision')
})
test('dream_steps follow remapped dream; orphans are dropped', () => {
  const out = remapImport(f(), 'HH', 'ME', (() => { let n = 0; return () => `id${++n}` })())
  const steps = out.filter((o) => o.table === 'dream_steps')
  expect(steps.length).toBe(1)
  expect(steps[0].row.dream_id).toBe(out.find((o) => o.table === 'dreams')!.row.id)
})
test('preview counts and version guard', () => {
  expect(previewCounts(f()).events).toBe(1)
  expect(() => remapImport({ ...f(), version: 2 as never }, 'H', 'M')).toThrow('Unsupported')
})
