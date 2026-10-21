// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { emptySnapshot } from '../shared/model'
import { DEFAULT_LAUNCHER_PREFS, type LauncherPrefs } from '../shared/launcherPrefs'
import type { CatalogEntry } from '../shared/catalog'

const e = (id: string, title: string, kind: 'app' | 'input' = 'app', extra: Partial<CatalogEntry> = {}): CatalogEntry => ({ id, title, kind, icon: null, source: 'curated', system: false, ...extra })
const CATALOG = [e('netflix', 'Netflix'), e('youtube', 'YouTube'), e('spotify', 'Spotify'), e('prime', 'Prime Video'), e('hdmi1', 'HDMI 1', 'input'), e('helper', 'Helper', 'app', { system: true })]

const app = { catalog: CATALOG, launcherPrefs: DEFAULT_LAUNCHER_PREFS as LauncherPrefs, setLauncherPrefs: vi.fn(), launch: vi.fn(), snap: emptySnapshot(), guest: false, now: new Date('2026-10-21T08:00:00Z'), tz: 'Asia/Kolkata', mode: 'home', live: null, capabilities: {} }
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

beforeEach(() => { host = document.createElement('div'); document.body.append(host); root = createRoot(host); app.setLauncherPrefs.mockClear(); app.launcherPrefs = DEFAULT_LAUNCHER_PREFS })
afterEach(() => { act(() => root.unmount()); host.remove() })

describe('Launcher', () => {
  it('renders with the curated catalog and an empty household (no personal card)', () => {
    mount(<Launcher />)
    expect(host.querySelector('.launcher')?.getAttribute('data-wallpaper')).toBe('dusk')
    expect(host.querySelector('.l-card')).toBeNull()
    expect(host.querySelectorAll('.l-slot')).toHaveLength(6)
    expect(host.textContent).toContain('Netflix')
    expect(host.textContent).not.toContain('Helper')
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
    click('New folder')
    expect(host.textContent).toContain('Streaming (0)')
    click('Cancel')
    expect(host.querySelector('.l-edit')).toBeNull()
    expect(app.setLauncherPrefs).not.toHaveBeenCalled()
  })
  it('Save writes the draft', () => {
    mount(<Launcher />)
    click('Edit'); click('New folder'); click('Save')
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
