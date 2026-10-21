// Volume and picture mode through webOS Luna services. Nothing is shown in the UI until a read-only probe succeeds on the
// actual TV (see Quick controls and Settings > Diagnostics). Response shapes differ between webOS versions, so parsing is defensive.
import type { Capability } from '../shared/catalog'
import type { LunaResult, Platform } from './platform'

export const AUDIO = 'luna://com.webos.service.audio/master/'
export const SETTINGS = 'luna://com.webos.settingsservice/'
export const PICTURE_MODES = ['standard', 'cinema', 'vivid', 'game', 'eco'] as const

/** Result of a read-only probe -> capability. A timeout is "unverified", a refusal is "denied". */
export function classify(r: LunaResult): Capability {
  if ('unknown' in r) return 'unverified'
  if (r.ok) return 'supported'
  return /denied|permission|not allowed|security|category/i.test(r.error) ? 'denied' : 'unavailable'
}

const num = (v: unknown) => (typeof v === 'number' && Number.isFinite(v) ? Math.round(v) : null)
export function parseVolume(d: Record<string, unknown>): { volume: number | null; muted: boolean | null } {
  const s = (d.volumeStatus && typeof d.volumeStatus === 'object' ? d.volumeStatus : d) as Record<string, unknown>
  const m = s.muted ?? s.mute ?? s.muteStatus
  return { volume: num(s.volume), muted: typeof m === 'boolean' ? m : null }
}
export function parsePictureMode(d: Record<string, unknown>): string | null {
  const s = (d.settings && typeof d.settings === 'object' ? d.settings : d) as Record<string, unknown>
  return typeof s.pictureMode === 'string' ? s.pictureMode : null
}

export const probeVolume = async (p: Platform) => { const r = await p.call(AUDIO + 'getVolume', {}); return { cap: classify(r), ...('ok' in r && r.ok ? parseVolume(r.data) : { volume: null, muted: null }) } }
export const probePicture = async (p: Platform) => { const r = await p.call(SETTINGS + 'getSystemSettings', { category: 'picture', keys: ['pictureMode'] }); return { cap: classify(r), mode: 'ok' in r && r.ok ? parsePictureMode(r.data) : null } }
export const volumeStep = (p: Platform, up: boolean) => p.call(AUDIO + (up ? 'volumeUp' : 'volumeDown'), {})
export const setMuted = (p: Platform, muted: boolean) => p.call(AUDIO + 'setMuted', { muted })
export const setPictureMode = (p: Platform, mode: string) => p.call(SETTINGS + 'setSystemSettings', { category: 'picture', settings: { pictureMode: mode } })
