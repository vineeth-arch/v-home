// Spatial focus + Back stack. Pure logic here; React glue in FocusProvider.tsx.
export type Dir = 'left' | 'right' | 'up' | 'down'
export interface Box { id: string; x: number; y: number; w: number; h: number }

const center = (b: Box) => ({ cx: b.x + b.w / 2, cy: b.y + b.h / 2 })

/** Nearest candidate in direction: primary-axis distance + 2x cross-axis offset (LGTV app.js idea, from boxes). */
export function pickNext(boxes: Box[], currentId: string | null, dir: Dir): string | null {
  const cur = boxes.find((b) => b.id === currentId)
  if (!cur) return boxes[0]?.id ?? null
  const c = center(cur)
  let best: { id: string; score: number } | null = null
  for (const b of boxes) {
    if (b.id === cur.id) continue
    const o = center(b)
    const dx = o.cx - c.cx, dy = o.cy - c.cy
    const [main, cross] = dir === 'left' ? [-dx, dy] : dir === 'right' ? [dx, dy] : dir === 'up' ? [-dy, dx] : [dy, dx]
    // must lie beyond the current box's edge, so a neighbour shifted a few px (focus lift) is not "below"
    const beyond = dir === 'left' ? o.cx < cur.x : dir === 'right' ? o.cx > cur.x + cur.w : dir === 'up' ? o.cy < cur.y : o.cy > cur.y + cur.h
    if (main <= 0 || !beyond) continue
    const score = main + 2 * Math.abs(cross)
    if (!best || score < best.score) best = { id: b.id, score }
  }
  return best?.id ?? null
}

export const KEY_BACK = [461, 27, 8]
export const dirForKey = (code: number): Dir | null =>
  code === 37 ? 'left' : code === 39 ? 'right' : code === 38 ? 'up' : code === 40 ? 'down' : null

/** Layers: screens/overlays pushed on top of root. Back pops; at root returns 'exit'.
 *  Names starting "nav:" are screen layers (do not change focus scope); others are overlays that trap focus. */
export interface Layer { name: string; onClose?: () => void; saved: string | null }
export class BackStack {
  private layers: Layer[] = []
  push(name: string, onClose?: () => void, saved: string | null = null): Layer {
    const l = { name, onClose, saved }; this.layers.push(l); return l
  }
  remove(l: Layer) { const i = this.layers.indexOf(l); if (i >= 0) this.layers.splice(i, 1) }
  get depth() { return this.layers.length }
  /** Current focus scope: topmost overlay name, else 'main'. */
  get scope() { for (let i = this.layers.length - 1; i >= 0; i--) if (!this.layers[i].name.startsWith('nav:')) return this.layers[i].name; return 'main' }
  back(): 'closed' | 'exit' {
    const top = this.layers.pop()
    if (!top) return 'exit'
    top.onClose?.()
    return 'closed'
  }
}
