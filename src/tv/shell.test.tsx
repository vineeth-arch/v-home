import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'

const h = vi.hoisted(() => ({ configured: false, status: 'pairing' as 'pairing' | 'ready' }))
vi.mock('../shared/supabase', () => ({ get supabaseConfigured() { return h.configured }, getClient: () => { throw new Error('no client in tests') } }))
vi.mock('./live', () => ({
  useLive: (enabled: boolean) => ({
    status: enabled ? h.status : 'booting', code: 'ABC123', snapshot: null, offline: false, cacheBackend: 'test', images: {},
    syncStudio: async () => {}, unpair: async () => {}, completeTask: async () => {}, markWatched: async () => {},
  }),
}))
vi.mock('./Launcher', () => ({ Launcher: () => <div data-testid="launcher">LAUNCHER</div>, LauncherSettings: () => null, Diagnostics: () => null }))

import { FocusProvider } from './FocusProvider'
import { AppProvider } from './state'
import { App } from './App'

let root: Root, host: HTMLElement
const back = () => act(() => { window.dispatchEvent(new KeyboardEvent('keydown', { keyCode: 461, bubbles: true })) })
const click = (id: string) => act(() => { [...host.querySelectorAll('button')].find((b) => b.textContent === id)!.click() })
const mount = async () => {
  host = document.createElement('div'); document.body.appendChild(host); root = createRoot(host)
  await act(async () => { root.render(<FocusProvider><AppProvider><App /></AppProvider></FocusProvider>) })
}
beforeEach(() => { h.configured = false; (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true; localStorage.clear(); history.replaceState(null, '', '/') })
afterEach(() => { act(() => root.unmount()); host.remove(); vi.restoreAllMocks() })

test('starts on the launcher; Back from Our Home returns to it', async () => {
  await mount()
  expect(host.querySelector('[data-testid=launcher]')).not.toBeNull()
  click('Our Home')
  expect(host.querySelector('[data-testid=launcher]')).toBeNull()
  expect(host.textContent).toMatch(/Start our|Wind down|Watch Together|Skip/) // Our Home hero actions; which one depends on the time of day
  back()
  expect(host.querySelector('[data-testid=launcher]')).not.toBeNull()
})

test('root Back shows the exit dialog; Back again closes it without leaving', async () => {
  const close = vi.spyOn(window, 'close').mockImplementation(() => {})
  await mount()
  back()
  expect(host.textContent).toContain('Leave V/HOME?')
  expect(host.textContent).toContain('python -m vhome_companion pause')
  back()
  expect(host.textContent).not.toContain('Leave V/HOME?')
  expect(close).not.toHaveBeenCalled()
  back(); click('Leave')
  expect(close).toHaveBeenCalledTimes(1)
})

test('unpaired live: launcher and Settings render, Our Home shows the pairing card', async () => {
  h.configured = true; h.status = 'pairing'
  await mount()
  expect(host.querySelector('[data-testid=launcher]')).not.toBeNull()
  expect(host.textContent).not.toContain('Pair this TV')
  click('Our Home')
  expect(host.textContent).toContain('Pair this TV')
  expect(host.textContent).toContain('ABC123')
  click('Settings')
  expect(host.textContent).toContain('Pair this TV')
  expect(host.textContent).toContain('Timezone')
  click('Home')
  expect(host.querySelector('[data-testid=launcher]')).not.toBeNull()
})

test('navHidesTimerLineOnLauncher', async () => {
  await mount()
  expect(host.querySelector('[data-testid=launcher]')).not.toBeNull()
  expect(host.querySelector('.timer-line')).toBeNull()
  click('Our Home')
  expect(host.querySelector('.timer-line')).not.toBeNull()
})
