import { createContext, useCallback, useContext, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { BackStack, KEY_BACK, dirForKey, pickNext, type Box } from './focus'

interface Entry { el: HTMLElement; scope: string }
interface Ctx {
  focusedId: string | null
  register(id: string, el: HTMLElement, scope: string, initial: boolean): () => void
  focus(id: string): void
  pushLayer(name: string, onClose?: () => void): () => void
}
const FocusCtx = createContext<Ctx | null>(null)
export const useFocusCtx = () => useContext(FocusCtx)!

/** Back at the root asks the app to show its exit dialog (AppProvider listens). */
export const EXIT_EVENT = 'vhome:exit-root'
export const requestExit = () => window.dispatchEvent(new Event(EXIT_EVENT))

export const LONG_PRESS_MS = 650
const scrollerOf = (el: HTMLElement): HTMLElement | null => {
  for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
    const oy = getComputedStyle(p).overflowY
    if (oy === 'auto' || oy === 'scroll') return p
  }
  return null
}
/** Scrolls only the nearest overflow-y:auto/scroll list so `el` is visible. Never scrolls the page or
 *  overflow:hidden boxes (scrollIntoView does, which can shift the whole 1920x1080 stage on the TV). */
function revealInScroller(el: HTMLElement) {
  const p = scrollerOf(el)
  if (!p) return
  const a = el.getBoundingClientRect(), b = p.getBoundingClientRect(), pad = 16
  const k = p.offsetHeight ? b.height / p.offsetHeight : 1 // desktop preview scales the stage; TV k = 1
  if (a.top < b.top) p.scrollTop -= (b.top - a.top) / k + pad
  else if (a.bottom > b.bottom) p.scrollTop += (a.bottom - b.bottom) / k + pad
}

export function FocusProvider({ children, onExitRoot = requestExit }: { children: ReactNode; onExitRoot?: () => void }) {
  const els = useRef(new Map<string, Entry>())
  const stack = useRef(new BackStack())
  const [focusedId, setFocused] = useState<string | null>(null)
  const focusedRef = useRef<string | null>(null)
  const hiddenFocus = useRef<string | null>(null)
  const ok = useRef<{ el: HTMLElement; timer: ReturnType<typeof setTimeout>; long: boolean } | null>(null) // OK held on a data-longpress element

  const focus = useCallback((id: string) => {
    focusedRef.current = id; setFocused(id)
    const el = els.current.get(id)?.el
    if (!el) return
    el.focus({ preventScroll: true })
    revealInScroller(el)
  }, [])

  const register = useCallback((id: string, el: HTMLElement, scope: string, initial: boolean) => {
    els.current.set(id, { el, scope })
    const cur = focusedRef.current ? els.current.get(focusedRef.current) : undefined
    if (scope === stack.current.scope && (initial || !cur || cur.scope !== scope)) focus(id)
    return () => {
      els.current.delete(id)
      if (focusedRef.current === id) { focusedRef.current = null; setFocused(null) }
    }
  }, [focus])

  const pushLayer = useCallback((name: string, onClose?: () => void) => {
    const layer = stack.current.push(name, onClose, focusedRef.current)
    return () => {
      stack.current.remove(layer)
      if (layer.saved && els.current.has(layer.saved)) focus(layer.saved)
    }
  }, [focus])

  useEffect(() => {
    // scroller=true: only targets in the focused element's scrolling list (so Down scrolls the list before leaving it)
    const boxes = (scroller = false): Box[] => {
      const sc = stack.current.scope
      const cur = els.current.get(focusedRef.current ?? '')?.el
      const list = cur && scroller ? scrollerOf(cur) : null
      return [...els.current].filter(([, e]) => e.scope === sc && (!list || list.contains(e.el) || e.el === cur)).map(([id, e]) => { const r = e.el.getBoundingClientRect(); return { id, x: r.x, y: r.y, w: r.width, h: r.height } })
    }
    const onKey = (e: KeyboardEvent) => {
      const dir = dirForKey(e.keyCode)
      if (dir) { const n = pickNext(boxes(true), focusedRef.current, dir) ?? pickNext(boxes(), focusedRef.current, dir); if (n) focus(n); e.preventDefault(); return }
      if (e.keyCode === 13) {
        const el = els.current.get(focusedRef.current ?? '')?.el
        if (!el) return
        if (!el.dataset.longpress) { el.click(); return }
        // long-press capable: a tap clicks on key-up; holding OK fires 'longpress' instead
        if (ok.current) return // key repeat
        const st = { el, long: false, timer: setTimeout(() => { st.long = true; el.dispatchEvent(new CustomEvent('longpress')) }, LONG_PRESS_MS) }
        ok.current = st
        return
      }
      if (KEY_BACK.includes(e.keyCode)) {
        e.preventDefault()
        if (stack.current.back() === 'exit') onExitRoot()
      }
    }
    const onKeyUp = (e: KeyboardEvent) => {
      if (e.keyCode !== 13 || !ok.current) return
      const st = ok.current; ok.current = null; clearTimeout(st.timer)
      if (!st.long && st.el.isConnected) st.el.click()
    }
    const onVis = () => { // preserve focus when returning from another app
      if (document.hidden) hiddenFocus.current = focusedRef.current
      else if (hiddenFocus.current && els.current.has(hiddenFocus.current)) focus(hiddenFocus.current)
    }
    window.addEventListener('keydown', onKey); window.addEventListener('keyup', onKeyUp)
    document.addEventListener('visibilitychange', onVis)
    return () => { window.removeEventListener('keydown', onKey); window.removeEventListener('keyup', onKeyUp); document.removeEventListener('visibilitychange', onVis) }
  }, [focus, onExitRoot])

  const value = useMemo(() => ({ focusedId, register, focus, pushLayer }), [focusedId, register, focus, pushLayer])
  return <FocusCtx.Provider value={value}>{children}</FocusCtx.Provider>
}

/** Focusable props. Pointer hover syncs to keyboard focus; ring shown via [data-focused]. */
export function useFocusable(id: string, opts: { scope?: string; initial?: boolean } = {}) {
  const { focusedId, register, focus } = useFocusCtx()
  const ref = useRef<HTMLElement | null>(null)
  const scope = opts.scope ?? 'main', initial = !!opts.initial
  useEffect(() => register(id, ref.current!, scope, initial), [register, id, scope, initial])
  return {
    ref: ref as never, tabIndex: -1, className: 'focusable',
    'data-focused': focusedId === id || undefined,
    onMouseEnter: () => focus(id),
  }
}

/** Register a Back-stack layer while `active`. Layout effect so it exists before children register. */
export function useLayer(name: string, active: boolean, onClose: () => void) {
  const { pushLayer } = useFocusCtx()
  const cb = useRef(onClose); cb.current = onClose
  useLayoutEffect(() => (active ? pushLayer(name, () => cb.current()) : undefined), [name, active, pushLayer])
}
