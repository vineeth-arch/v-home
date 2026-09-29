import { useState, type ButtonHTMLAttributes, type ReactNode } from 'react'
import { useApp } from './state'
import { useFocusable } from './FocusProvider'
import type { Dream } from '../shared/model'

/** Focusable button. `id` must be unique within its scope. */
export function Btn({ id, scope, initial, className = '', children, ...rest }:
  { id: string; scope?: string; initial?: boolean; className?: string; children: ReactNode } & Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'id'>) {
  const f = useFocusable(id, { scope, initial })
  const { className: fc, ...fp } = f
  return <button {...fp} {...rest} className={`btn ${fc} ${className}`}>{children}</button>
}

/** Flat, gradient-free placeholder art until personal images arrive. Solid layered shapes; fills come from tokens (ui.css .da-*). */
export function DreamArt({ kind }: { kind: Dream['art'] }) {
  const halo = (cx: number, cy: number, r: number) => <>
    <circle className="da-a" cx={cx} cy={cy} r={r * 2.1} opacity=".06" />
    <circle className="da-a" cx={cx} cy={cy} r={r * 1.55} opacity=".1" />
    <circle className="da-a" cx={cx} cy={cy} r={r} />
  </>
  return (
    <svg viewBox="0 0 800 500" preserveAspectRatio="xMidYMid slice" className="dream-art" aria-hidden>
      <rect className="da-d" width="800" height="500" />
      {[[90, 70], [180, 40], [300, 90], [660, 60], [730, 120], [520, 36]].map(([x, y]) => <circle key={x} className="da-w" cx={x} cy={y} r="2.5" opacity=".35" />)}
      {kind === 'sea' && <>{halo(560, 230, 70)}<rect className="da-s" y="300" width="800" height="200" opacity=".55" /><rect className="da-a" x="490" y="312" width="140" height="8" rx="4" opacity=".55" /><rect className="da-w" x="120" y="350" width="560" height="10" rx="5" opacity=".22" /><rect className="da-w" x="220" y="400" width="420" height="8" rx="4" opacity=".16" /><rect className="da-w" x="80" y="445" width="300" height="6" rx="3" opacity=".12" /></>}
      {kind === 'hills' && <>{halo(210, 170, 60)}<path className="da-s" d="M0 500V300Q180 200 380 300T800 270V500Z" opacity=".35" /><path className="da-s" d="M0 500V340Q200 240 400 340T800 310V500Z" opacity=".65" /><path className="da-s" d="M0 500V410Q250 330 500 420T800 390V500Z" /></>}
      {kind === 'sun' && <>{halo(400, 215, 100)}<rect className="da-f" y="215" width="800" height="285" /><rect className="da-a" x="310" y="236" width="180" height="8" rx="4" opacity=".4" /><rect className="da-a" x="350" y="262" width="100" height="6" rx="3" opacity=".25" /></>}
      {kind === 'window' && <>{halo(400, 250, 70)}<rect className="da-f" x="250" y="80" width="300" height="340" rx="150" opacity=".55" /><rect x="250" y="80" width="300" height="340" rx="150" fill="none" className="da-stroke" strokeWidth="10" /><rect className="da-a" x="395" y="80" width="10" height="340" /><rect className="da-a" x="250" y="240" width="300" height="10" /><rect className="da-s" x="0" y="420" width="800" height="80" opacity=".6" /></>}
    </svg>
  )
}

/** The dream's own photo when it has one (and it loads), otherwise the flat art. Never a broken image. */
export function DreamPic({ imagePath, kind }: { imagePath?: string; kind: Dream['art'] }) {
  const { images } = useApp()
  const src = imagePath ? images[imagePath] : undefined
  const [failed, setFailed] = useState<string | null>(null)
  if (!src || failed === src) return <DreamArt kind={kind} />
  return <img className="dream-art dream-photo" src={src} alt="" onError={() => setFailed(src)} />
}

export const fmtTime = (iso: string | Date | number, tz: string) =>
  new Intl.DateTimeFormat('en-IN', { timeZone: tz, hour: 'numeric', minute: '2-digit', hour12: true }).format(new Date(iso)).toUpperCase()
export const fmtDay = (iso: string | Date | number, tz: string) =>
  new Intl.DateTimeFormat('en-IN', { timeZone: tz, weekday: 'short', day: 'numeric', month: 'short' }).format(new Date(iso))
