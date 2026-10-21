import { expect, test } from 'vitest'
import { bundledCatalog, iconUrl, isSystemApp, mergeEntries, parseCatalog, withRemembered, type CatalogEntry } from './catalog'

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
test('bundled catalog is the exported tv-catalog when present, else curated candidates', () => {
  const c = bundledCatalog()
  expect(c.entries.length).toBeGreaterThan(0)
  expect(c.entries.find((e) => e.id === 'com.webos.app.hdmi1')?.kind).toBe('input') // curated and exported both
  expect(new Set(c.entries.map((e) => e.id)).size).toBe(c.entries.length)
  if (c.entries.every((e) => e.source === 'curated')) expect(c.entries.every((e) => e.icon === null)).toBe(true)
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

test('system rule matches the companion: helpers and V/HOME hidden, user apps and inputs kept', () => {
  expect(isSystemApp('com.webos.app.discovery', 'app')).toBe(true)
  expect(isSystemApp('com.webos.app.livetv', 'app')).toBe(false)
  expect(isSystemApp('com.designinnsaeit.vhome', 'app')).toBe(true)
  expect(isSystemApp('com.webos.app.browser', 'app')).toBe(false)
  expect(isSystemApp('com.webos.app.hdmi1', 'input')).toBe(false)
  expect(isSystemApp('netflix', 'app', true)).toBe(true)
  expect(isSystemApp('netflix', 'app')).toBe(false)
})
test('remembered catalog keeps a vanished app only while the layout uses it', () => {
  localStorage.clear()
  withRemembered([E('netflix'), E('gone'), E('unused')], () => false)
  const next = withRemembered([E('netflix')], (id) => id === 'gone')
  expect(next.map((e) => [e.id, !!e.unavailable])).toEqual([['netflix', false], ['gone', true]])
  localStorage.setItem('vhomeLauncher.catalog.v1', '{bad')
  expect(withRemembered([E('x')], () => true).map((e) => e.id)).toEqual(['x'])
})
