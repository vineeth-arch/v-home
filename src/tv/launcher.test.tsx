// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { emptySnapshot } from '../shared/model'
import { DEFAULT_LAUNCHER_PREFS, type LauncherPrefs } from '../shared/launcherPrefs'
import type { CatalogEntry } from '../shared/catalog'

const e = (id: string, title: string, kind: 'app' | 'input' = 'app', extra: Partial<CatalogEntry> = {}): CatalogEntry => ({ id, title, kind, icon: null, source: 'curated', system: false, ...extra })
const CATALOG = [e('netflix', 'Netflix'), e('youtube', 'YouTube'), e('spotify', 'Spotify'), e('prime', 'Prime Video'), e('hdmi1', 'HDMI 1', 'input'), e('helper', 'Helper', 'app', { system: true })]

const app = { catalog: CATALOG as CatalogEntry[], launcherPrefs: DEFAULT_LAUNCHER_PREFS as LauncherPrefs, setLauncherPrefs: vi.fn(), launch: vi.fn(), snap: emptySnapshot(), guest: false, now: new Date('2026-10-21T08:00:00Z'), tz: 'Asia/Kolkata', mode: 'home', live: null, capabilities: {}, timerState: { scheduled: false } as const, ctrl: { verified: false, mutate: vi.fn(), label: 'test' }, refreshTimer: vi.fn(), timerAt: null as number | null, images: {} as Record<string, string>, setOverlay: vi.fn(), tvControls: { volume: { cap: 'unverified', volume: null, muted: null }, picture: { cap: 'unverified', mode: null } }, canCheckTimer: false, checkTimer: vi.fn() }
vi.mock('./state', () => ({ useApp: () => app }))

import { FocusProvider } from './FocusProvider'
import { Launcher, LauncherSettings, Diagnostics } from './Launcher'
import { createFolder, moveStep, orderedIds } from './LauncherEdit'
import { deleteFolder, moveToFolder } from '../shared/launcherPrefs'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
let host: HTMLDivElement, root: Root
const mount = (ui: React.ReactNode) => { act(() => { root.render(<FocusProvider>{ui}</FocusProvider>) }) }
const click = (text: string) => {
  const b = [...host.querySelectorAll('button')].find((x) => x.textContent?.trim() === text)
  if (!b) throw new Error(`no button "${text}"`)
  act(() => { b.click() })
}

beforeEach(() => { host = document.createElement('div'); document.body.append(host); root = createRoot(host); app.setLauncherPrefs.mockClear(); app.launcherPrefs = DEFAULT_LAUNCHER_PREFS; app.snap = emptySnapshot(); app.images = {}; app.guest = false; app.timerAt = null; app.setOverlay.mockClear() })
afterEach(() => { act(() => root.unmount()); host.remove() })

describe('Launcher', () => {
  it('typing a folder name with the on-screen keyboard', () => {
    mount(<Launcher />)
    click('Edit'); click('New folder')
    for (const c of ['K', 'I', 'D', 'S']) click(c)
    click('Space'); click('A')
    expect(host.querySelector('.l-kbd-text')?.textContent).toBe('Kids A') // auto capital after a space
    click('Done')
    expect(host.textContent).toContain('Kids A (0)')
  })
  it('shows the sleep-timer shortcuts on the right', () => {
    mount(<Launcher />)
    const labels = [...host.querySelectorAll('.l-timer button')].map((b) => b.textContent)
    expect(labels).toEqual(['15min', '30min', '45min', '60min', '90min', 'Cancel timer'])
  })
  it('renders with the curated catalog and an empty household (no personal card)', () => {
    mount(<Launcher />)
    expect(host.querySelector('.launcher')?.getAttribute('data-wallpaper')).toBe('dusk')
    expect(host.querySelector('.l-card')).toBeNull()
    expect(host.querySelectorAll('.l-slot')).toHaveLength(9)
    expect(host.textContent).toContain('Netflix')
    expect(host.textContent).not.toContain('Helper')
  })
  it('favoritesGridHasNineSlots', () => {
    mount(<Launcher />)
    expect(host.querySelector('.l-fav3')?.children).toHaveLength(9)
    expect(readFileSync('src/tv/launcher.css', 'utf8')).toMatch(/\.l-fav3\s*\{[^}]*repeat\(3,\s*1fr\)/)
  })
  it('tenSavedFavoritesRenderNine', () => {
    const many = Array.from({ length: 10 }, (_, i) => e('a' + i, 'App' + i))
    const cat = [...CATALOG, ...many]
    app.catalog = cat
    app.launcherPrefs = { ...DEFAULT_LAUNCHER_PREFS, favorites: many.map((x) => x.id) }
    mount(<Launcher />)
    expect(host.querySelectorAll('.l-fav3 > button')).toHaveLength(9)
    expect(host.querySelector('.l-fav3')?.textContent).not.toContain('App9')
    app.catalog = CATALOG
  })
  it('photoCardShowsFirstPhoto', () => {
    app.snap = { ...emptySnapshot(), moments: [{ path: 'p1', caption: 'Beach' }] } as never
    app.images = { p1: 'blob:x' }
    mount(<Launcher />)
    expect(host.querySelector('.l-photos img[src="blob:x"]')).not.toBeNull()
    act(() => { (host.querySelector('.l-photos') as HTMLElement).click() })
    expect(app.setOverlay).toHaveBeenCalledWith('ambient')
  })
  it('photoCardEmptyHint', () => {
    mount(<Launcher />)
    expect(host.querySelector('.l-photos')?.textContent).toContain('Add photos on your phone: Photos → Show on TV')
  })
  it('photoCardHiddenForGuest', () => {
    app.snap = { ...emptySnapshot(), moments: [{ path: 'p1' }] } as never
    app.images = { p1: 'blob:x' }; app.guest = true
    mount(<Launcher />)
    expect(host.querySelector('.l-photos')).toBeNull()
  })
  it('timerConfirmedHidesUnverified', () => {
    mount(<Launcher />)
    expect(host.querySelector('.l-tmsg')?.textContent).toContain('Not yet verified')
    app.timerAt = Date.now()
    mount(<Launcher />)
    expect(host.querySelector('.l-tmsg')?.textContent).not.toContain('Not yet verified')
  })
  it('settings and diagnostics render', () => {
    mount(<><LauncherSettings /><Diagnostics /></>)
    expect(host.textContent).toContain('Dusk')
    expect(host.textContent).toContain('does not prove the app opened')
  })
})

describe('layout editor', () => {
  it('Cancel discards the draft: setLauncherPrefs is not called', () => {
    mount(<Launcher />)
    click('Edit')
    click('New folder'); click('Done') // the keyboard opens; Done with no typing keeps the default name
    expect(host.textContent).toContain('Streaming (0)')
    click('Cancel')
    expect(host.querySelector('.l-edit')).toBeNull()
    expect(app.setLauncherPrefs).not.toHaveBeenCalled()
  })
  it('Save writes the draft', () => {
    mount(<Launcher />)
    click('Edit'); click('New folder'); click('Done'); click('Save')
    expect(app.setLauncherPrefs).toHaveBeenCalledTimes(1)
    expect(app.setLauncherPrefs.mock.calls[0][0].folders).toHaveLength(1)
  })
  it('deleting a folder returns its apps to the grid in the draft', () => {
    let p = createFolder(DEFAULT_LAUNCHER_PREFS)
    p = moveToFolder(p, 'netflix', p.folders[0].id)
    expect(p.folders[0].apps).toEqual(['netflix'])
    p = deleteFolder(p, p.folders[0].id)
    expect(p.folders).toHaveLength(0)
    expect(orderedIds(CATALOG, p)).toContain('netflix')
  })
  it('moves within the visible grid, skipping hidden and foldered apps', () => {
    const p: LauncherPrefs = { ...DEFAULT_LAUNCHER_PREFS, hidden: ['youtube'] }
    expect(moveStep(p, CATALOG, 'spotify', -1).order.slice(0, 3)).toEqual(['spotify', 'youtube', 'netflix'])
  })
})
