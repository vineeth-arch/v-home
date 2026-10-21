import { afterEach, expect, test, vi } from 'vitest'
import type { CatalogEntry } from './catalog'
import {
  DEFAULT_LAUNCHER_PREFS as D, LAUNCHER_KEY, MAX_FAVORITES, applyLayout, createFolder, deleteFolder, loadPrefs, moveId, moveToFolder,
  renameFolder, resolveLauncherPrefs, savePrefs, toggleFavorite, toggleHidden, type LauncherPrefs,
} from './launcherPrefs'

const E = (id: string, extra: Partial<CatalogEntry> = {}): CatalogEntry => ({ id, title: id, kind: 'app', icon: null, source: 'tv', system: false, ...extra })
const P = (extra: Partial<LauncherPrefs> = {}): LauncherPrefs => ({ ...D, ...extra })
afterEach(() => vi.unstubAllGlobals())

test('garbage and wrong types resolve to defaults', () => {
  for (const raw of [null, undefined, 'x', 5, [], { favorites: 'a', order: 3, hidden: {}, folders: 'x', wallpaper: 9, reducedMotion: 'yes' }]) expect(resolveLauncherPrefs(raw)).toEqual(D)
})
test('invalid ids dropped, deduped; favorites capped; unknown wallpaper -> dusk', () => {
  const many = Array.from({ length: 20 }, (_, i) => 'app' + i)
  const r = resolveLauncherPrefs({ favorites: [...many, 'app1', 'a', 5], order: ['aa', 'aa', 'b'], wallpaper: 'neon' })
  expect(r.favorites).toEqual(many.slice(0, MAX_FAVORITES))
  expect(r.order).toEqual(['aa'])
  expect(r.wallpaper).toBe('dusk')
  expect(resolveLauncherPrefs({ wallpaper: 'ocean', reducedMotion: true }).wallpaper).toBe('ocean')
})
test('folders are validated; an app lives in one folder only', () => {
  const r = resolveLauncherPrefs({ folders: [
    { id: 'f1', name: ' Kids ', apps: ['aa', 'bb', 'aa', 'x'] }, { id: 'f2', name: 'More', apps: ['bb', 'cc'] },
    { id: 'f1', name: 'Dup', apps: [] }, { id: '', name: 'n', apps: [] }, { id: 'f3', name: '', apps: [] }, { id: 'f4', name: 'x'.repeat(31), apps: [] }, null,
  ] })
  expect(r.folders).toEqual([{ id: 'f1', name: 'Kids', apps: ['aa', 'bb'] }, { id: 'f2', name: 'More', apps: ['cc'] }])
})
test('loadPrefs survives corrupt JSON and throwing storage; savePrefs never throws', () => {
  const boom = () => { throw new Error('denied') }
  vi.stubGlobal('localStorage', { getItem: () => '{not json', setItem: boom })
  expect(loadPrefs()).toEqual(D)
  expect(() => savePrefs(D)).not.toThrow()
  vi.stubGlobal('localStorage', { getItem: boom, setItem: boom })
  expect(loadPrefs()).toEqual(D)
})
test('save then load round-trips', () => {
  const store: Record<string, string> = {}
  vi.stubGlobal('localStorage', { getItem: (k: string) => store[k] ?? null, setItem: (k: string, v: string) => { store[k] = v } })
  const p = P({ favorites: ['aa'], wallpaper: 'ember' })
  savePrefs(p)
  expect(store[LAUNCHER_KEY]).toBeTruthy()
  expect(loadPrefs()).toEqual(p)
})
test('applyLayout: hides system/hidden, respects order, folders leave the grid', () => {
  const entries = [E('aa'), E('bb'), E('cc'), E('dd', { system: true }), E('ee'), E('hdmi1', { kind: 'input' }), E('hdmi2', { kind: 'input', system: true })]
  const l = applyLayout(entries, P({ order: ['ee', 'aa'], hidden: ['bb'], favorites: ['hdmi1', 'bb', 'gone', 'cc'], folders: [{ id: 'f1', name: 'F', apps: ['cc', 'zz'] }] }))
  expect(l.grid.map((e) => e.id)).toEqual(['ee', 'aa'])
  expect(l.dock.map((e) => e.id)).toEqual(['hdmi1', 'cc'])
  expect(l.inputs.map((e) => e.id)).toEqual(['hdmi1'])
  expect(l.folders).toHaveLength(1)
  expect(l.folders[0].apps.map((e) => e.id)).toEqual(['cc'])
})
test('applyLayout: empty folders stay; unavailable apps stay greyed in grid and are listed', () => {
  const entries = [E('aa'), E('bb', { unavailable: true }), E('cc', { unavailable: true })]
  const l = applyLayout(entries, P({ order: ['bb'], folders: [{ id: 'f1', name: 'Empty', apps: ['gone'] }] }))
  expect(l.folders[0].apps).toEqual([])
  expect(l.grid.map((e) => e.id)).toEqual(['bb', 'aa', 'cc'])
  expect(l.unavailable.map((e) => e.id)).toEqual(['bb'])
})
test('deleteFolder returns its apps to the grid', () => {
  const entries = [E('aa'), E('bb')]
  let p = createFolder(P(), 'Fun', ['aa'])
  expect(applyLayout(entries, p).grid.map((e) => e.id)).toEqual(['bb'])
  p = deleteFolder(p, p.folders[0].id)
  expect(applyLayout(entries, p).grid.map((e) => e.id)).toEqual(['aa', 'bb'])
})
test('helpers: moveId, favorites cap, hidden toggle, folder moves', () => {
  expect(moveId(['a', 'b', 'c'], 'c', -1)).toEqual(['a', 'c', 'b'])
  expect(moveId(['a', 'b', 'c'], 'a', -5)).toEqual(['a', 'b', 'c'])
  expect(moveId(['a', 'b', 'c'], 'a', 9)).toEqual(['b', 'c', 'a'])
  expect(moveId(['a'], 'zz', 1)).toEqual(['a'])
  let p = P()
  for (let i = 0; i < MAX_FAVORITES + 2; i++) p = toggleFavorite(p, 'app' + i)
  expect(p.favorites).toHaveLength(MAX_FAVORITES)
  expect(toggleFavorite(p, 'app0').favorites).not.toContain('app0')
  expect(toggleHidden(toggleHidden(P(), 'aa'), 'aa').hidden).toEqual([])
  let q = createFolder(P(), 'One', ['aa'])
  q = createFolder(q, 'Two', [])
  q = moveToFolder(q, 'aa', q.folders[1].id)
  expect(q.folders.map((f) => f.apps)).toEqual([[], ['aa']])
  expect(moveToFolder(q, 'aa', null).folders.map((f) => f.apps)).toEqual([[], []])
  expect(renameFolder(q, q.folders[0].id, '  Renamed ').folders[0].name).toBe('Renamed')
  expect(renameFolder(q, q.folders[0].id, '  ')).toBe(q)
  expect(createFolder(P(), '  ', ['aa']).folders).toEqual([])
})
