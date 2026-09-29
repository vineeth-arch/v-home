import type { LunaResult } from '../adapters/platform'
import { CANDIDATE_APPS, type PinnedApp } from './model'

/** Human message for a failed or unconfirmed launch, or null on success. Never silent. */
export function launchFailure(r: LunaResult, label: string): string | null {
  if ('unknown' in r) return `No answer from the TV while opening ${label}. Try again.`
  if (!r.ok) return `Couldn't open ${label}.`
  return null
}

/** Watch-list "service" text to a known launcher, by label ("Prime Video", "netflix"). */
export const appForService = (service: string | undefined, apps: PinnedApp[] = CANDIDATE_APPS): PinnedApp | undefined =>
  service ? apps.find((a) => a.label.toLowerCase() === service.trim().toLowerCase()) : undefined
