import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { useFocusable } from './FocusProvider'
import type { Dream } from '../shared/model'

/** Focusable button. `id` must be unique within its scope. */
export function Btn({ id, scope, initial, className = '', children, ...rest }:
  { id: string; scope?: string; initial?: boolean; className?: string; children: ReactNode } & Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'id'>) {
  const f = useFocusable(id, { scope, initial })
  const { className: fc, ...fp } = f
  return <button {...fp} {...rest} className={`btn ${fc} ${className}`}>{children}</button>
}

/** Flat, gradient-free placeholder art until personal images arrive (Phase 4). */
export function DreamArt({ kind }: { kind: Dream['art'] }) {
  const A = '#e0a458', S = '#9caf88', D = '#36302c', W = '#f5efe6'
  return (
    <svg viewBox="0 0 800 500" preserveAspectRatio="xMidYMid slice" className="dream-art" aria-hidden>
      <rect width="800" height="500" fill={D} />
      {kind === 'sea' && <><circle cx="560" cy="200" r="70" fill={A} /><rect y="300" width="800" height="200" fill={S} opacity=".55" /><rect y="340" width="800" height="12" fill={W} opacity=".25" /><rect y="390" width="800" height="8" fill={W} opacity=".2" /></>}
      {kind === 'hills' && <><circle cx="200" cy="150" r="60" fill={A} /><path d="M0 500V330Q200 220 400 330T800 300V500Z" fill={S} opacity=".7" /><path d="M0 500V400Q250 320 500 410T800 380V500Z" fill={S} /></>}
      {kind === 'sun' && <><circle cx="400" cy="300" r="120" fill={A} /><rect y="300" width="800" height="200" fill="#292524" /></>}
      {kind === 'window' && <><rect x="250" y="80" width="300" height="340" rx="150" fill="#292524" stroke={A} strokeWidth="10" /><rect x="395" y="80" width="10" height="340" fill={A} /><rect x="250" y="240" width="300" height="10" fill={A} /><rect x="0" y="420" width="800" height="80" fill={S} opacity=".6" /></>}
    </svg>
  )
}

export const fmtTime = (iso: string | Date | number, tz: string) =>
  new Intl.DateTimeFormat('en-IN', { timeZone: tz, hour: 'numeric', minute: '2-digit', hour12: true }).format(new Date(iso)).toUpperCase()
export const fmtDay = (iso: string | Date | number, tz: string) =>
  new Intl.DateTimeFormat('en-IN', { timeZone: tz, weekday: 'short', day: 'numeric', month: 'short' }).format(new Date(iso))
