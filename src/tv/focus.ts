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
    if (main <= 0) continue
    const score = main + 2 * Math.abs(cross)
    if (!best || score < best.score) best = { id: b.id, score }
  }
  return best?.id ?? null
}

export const KEY_BACK = [461, 27, 8]
export const dirForKey = (code: number): Dir | null =>
  code === 37 ? 'left' : code === 39 ? 'right' : code === 38 ? 'up' : code === 40 ? 'down' : null

/** Layers: root screen, then screens/overlays pushed on top. Back pops; at root returns 'exit'. */
export class BackStack {
  private layers: { name: string; onClose?: () => void }[] = []
  push(name: string, onClose?: () => void) { this.layers.push({ name, onClose }) }
  get depth() { return this.layers.length }
  back(): 'closed' | 'exit' {
    const top = this.layers.pop()
    if (!top) return 'exit'
    top.onClose?.()
    return 'closed'
  }
}
