import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { BackStack, KEY_BACK, dirForKey, pickNext, type Box } from './focus'

interface Ctx {
  focusedId: string | null
  register(id: string, el: HTMLElement): () => void
  focus(id: string): void
  pushLayer(name: string, onClose?: () => void): () => void
}
const FocusCtx = createContext<Ctx | null>(null)
export const useFocusCtx = () => useContext(FocusCtx)!

export function FocusProvider({ children, onExitRoot = () => window.close() }: { children: ReactNode; onExitRoot?: () => void }) {
  const els = useRef(new Map<string, HTMLElement>())
  const stack = useRef(new BackStack())
  const [focusedId, setFocused] = useState<string | null>(null)
  const focusedRef = useRef<string | null>(null)
  const saved = useRef<string | null>(null)

  const focus = useCallback((id: string) => {
    focusedRef.current = id; setFocused(id)
    els.current.get(id)?.focus({ preventScroll: true })
  }, [])

  const register = useCallback((id: string, el: HTMLElement) => {
    els.current.set(id, el)
    if (focusedRef.current === null) focus(id)
    return () => { els.current.delete(id); if (focusedRef.current === id) { focusedRef.current = null; setFocused(null) } }
  }, [focus])

  const pushLayer = useCallback((name: string, onClose?: () => void) => {
    stack.current.push(name, onClose)
    return () => {}
  }, [])

  useEffect(() => {
    const boxes = (): Box[] => [...els.current].map(([id, el]) => { const r = el.getBoundingClientRect(); return { id, x: r.x, y: r.y, w: r.width, h: r.height } })
    const onKey = (e: KeyboardEvent) => {
      const dir = dirForKey(e.keyCode)
      if (dir) { const n = pickNext(boxes(), focusedRef.current, dir); if (n) focus(n); e.preventDefault(); return }
      if (e.keyCode === 13) { els.current.get(focusedRef.current ?? '')?.click(); return }
      if (KEY_BACK.includes(e.keyCode)) {
        e.preventDefault()
        if (stack.current.back() === 'exit') onExitRoot()
      }
    }
    const onVis = () => { // preserve focus when returning from another app
      if (document.hidden) saved.current = focusedRef.current
      else if (saved.current && els.current.has(saved.current)) focus(saved.current)
    }
    window.addEventListener('keydown', onKey)
    document.addEventListener('visibilitychange', onVis)
    return () => { window.removeEventListener('keydown', onKey); document.removeEventListener('visibilitychange', onVis) }
  }, [focus, onExitRoot])

  const value = useMemo(() => ({ focusedId, register, focus, pushLayer }), [focusedId, register, focus, pushLayer])
  return <FocusCtx.Provider value={value}>{children}</FocusCtx.Provider>
}

/** Focusable element props: pointer hover syncs to keyboard focus; focus is visible via .focusable[data-focused]. */
export function useFocusable(id: string) {
  const ctx = useFocusCtx()
  const ref = useRef<HTMLElement | null>(null)
  const setRef = useCallback((el: HTMLElement | null) => {
    ref.current = el
    if (el) ctx.register(id, el)
  }, [ctx, id])
  return {
    ref: setRef, tabIndex: -1, className: 'focusable',
    'data-focused': ctx.focusedId === id || undefined,
    onMouseEnter: () => ctx.focus(id),
  }
}
