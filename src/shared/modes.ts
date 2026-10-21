import { localMinutes } from './daily'

export type Mode = 'home' | 'morning' | 'evening'
export interface Windows { morning: [number, number]; evening: [number, number] } // minutes since midnight, [start, end)
export const DEFAULT_WINDOWS: Windows = { morning: [5 * 60, 11 * 60], evening: [18 * 60, 5 * 60] }

const inWindow = (m: number, [s, e]: [number, number]) => (s <= e ? m >= s && m < e : m >= s || m < e)

/** manual != null wins until user returns to Auto (manual = null). Evening wraps past midnight. */
export function resolveMode(now: Date, tz: string, w: Windows = DEFAULT_WINDOWS, manual: Mode | null = null): Mode {
  if (manual) return manual
  const m = localMinutes(now, tz)
  if (inWindow(m, w.morning)) return 'morning'
  if (inWindow(m, w.evening)) return 'evening'
  return 'home'
}

/** Scheduled changes apply only when idle on the launcher or Our Home with no ritual running. Never interrupts. */
export function shouldApplyScheduledMode(
  current: Mode, next: Mode,
  ctx: { screen: string; ritualActive: boolean; idleMs: number },
): boolean {
  return current !== next && (ctx.screen === 'home' || ctx.screen === 'launcher') && !ctx.ritualActive && ctx.idleMs >= 60_000
}
