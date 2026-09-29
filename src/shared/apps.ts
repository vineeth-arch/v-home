import { CANDIDATE_APPS, type PinnedApp } from './model'

export const MAX_CUSTOM_APPS = 20
export const isValidAppId = (id: unknown): id is string => typeof id === 'string' && /^[a-zA-Z0-9._-]{2,100}$/.test(id)

/** Custom apps from settings: drops malformed entries and duplicates, caps at 20. Never throws. */
export function sanitizeCustomApps(raw: unknown): PinnedApp[] {
  if (!Array.isArray(raw)) return []
  const seen = new Set<string>(); const out: PinnedApp[] = []
  for (const a of raw) {
    const id = (a as PinnedApp | null)?.id, label = typeof (a as PinnedApp | null)?.label === 'string' ? (a as PinnedApp).label.trim() : ''
    if (!isValidAppId(id) || !label || label.length > 40 || seen.has(id)) continue
    seen.add(id); out.push({ id, label, verified: false })
    if (out.length >= MAX_CUSTOM_APPS) break
  }
  return out
}

/** listLaunchPoints response -> {id,label}, A–Z. Malformed entries dropped. Parsing idea from webos-custom-home (MIT). */
export function parseLaunchPoints(data: Record<string, unknown>): PinnedApp[] {
  const lp = Array.isArray(data.launchPoints) ? data.launchPoints : []
  return lp.flatMap((x) => {
    const id = (x as { id?: unknown }).id, title = (x as { title?: unknown }).title
    return isValidAppId(id) && typeof title === 'string' && title.trim() ? [{ id, label: title.trim(), verified: false }] : []
  }).sort((a, b) => a.label.localeCompare(b.label))
}

/** Everything the Apps screen lists: built-in candidates, the household's own, then apps found on the TV; no duplicate ids. */
export function allApps(custom: PinnedApp[], installed: PinnedApp[] = []): PinnedApp[] {
  const seen = new Set<string>(); const out: PinnedApp[] = []
  for (const a of [...CANDIDATE_APPS, ...custom, ...installed]) if (!seen.has(a.id)) { seen.add(a.id); out.push(a) }
  return out
}
