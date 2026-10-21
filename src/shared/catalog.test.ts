import { expect, test } from 'vitest'
import { bundledCatalog, iconUrl, mergeEntries, parseCatalog, type CatalogEntry } from './catalog'

const good = { id: 'netflix', title: ' Netflix ', kind: 'app', icon: 'netflix.png', source: 'companion', system: false }
const file = (entries: unknown[]) => ({ schema: 1, generatedAt: 'x', tv: { model: 'm', firmware: 'f' }, entries })
const E = (id: string, extra: Partial<CatalogEntry> = {}): CatalogEntry => ({ id, title: id, kind: 'app', icon: null, source: 'tv', system: false, ...extra })

test('corrupt catalog files give null, never throw', () => {
  for (const raw of [null, undefined, 'x', 5, [], {}, { schema: 2, entries: [] }, { schema: 1 }, { schema: 1, entries: 'a' }]) expect(parseCatalog(raw)).toBeNull()
})
test('bad entries are dropped individually; good ones trimmed', () => {
  const c = parseCatalog(file([
    good, null, 'x', { ...good, id: 'a' }, { ...good, id: 'ok1', title: '   ' }, { ...good, id: 'ok2', title: 'x'.repeat(61) },
    { ...good, id: 'ok3', kind: 'tv' }, { ...good, id: 'ok4', source: 'web' }, { ...good, id: 'ok5', icon: '../x.png' },
    { ...good, id: 'ok6', icon: 'x.gif' }, { ...good, id: 'ok7', system: 'yes' },
  ]))!
  expect(c.entries.map((e) => e.id)).toEqual(['netflix', 'ok7'])
  expect(c.entries[0].title).toBe('Netflix')
  expect(c.entries[1].system).toBe(false)
})
test('duplicate ids: first wins; capped at 200', () => {
  const c = parseCatalog(file([good, { ...good, title: 'Other' }]))!
  expect(c.entries).toHaveLength(1)
  expect(c.entries[0].title).toBe('Netflix')
  const many = Array.from({ length: 250 }, (_, i) => ({ ...good, id: 'app' + i }))
  expect(parseCatalog(file(many))!.entries).toHaveLength(200)
})
test('null icon (download failed) keeps the entry', () => {
  expect(parseCatalog(file([{ ...good, icon: null }]))!.entries[0].icon).toBeNull()
})
test('bundled catalog falls back to curated candidates when tv-catalog is absent', () => {
  const c = bundledCatalog()
  expect(c.entries.length).toBeGreaterThan(0)
  expect(c.entries.every((e) => e.source === 'curated' && e.icon === null)).toBe(true)
  expect(c.entries.find((e) => e.id === 'com.webos.app.hdmi1')?.kind).toBe('input')
  expect(c.entries.find((e) => e.id === 'netflix')?.kind).toBe('app')
  expect(bundledCatalog()).toBe(c)
})
test('iconUrl is null without a bundled icon', () => {
  expect(iconUrl(E('a'))).toBeNull()
  expect(iconUrl(E('a', { icon: 'missing.png' }))).toBeNull()
})
test('merge keeps order, marks removed unavailable, appends new, updates survivors', () => {
  const prev = [E('a'), E('b', { unavailable: true }), E('c')]
  const out = mergeEntries(prev, [E('d'), E('b', { title: 'B2' }), E('a'), E('d')])
  expect(out.map((e) => e.id)).toEqual(['a', 'b', 'c', 'd'])
  expect(out[1]).toMatchObject({ title: 'B2' })
  expect(out[1].unavailable).toBeUndefined()
  expect(out[2].unavailable).toBe(true)
  expect(out[3].unavailable).toBeUndefined()
})
