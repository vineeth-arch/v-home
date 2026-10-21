// Launcher catalog (contract: docs/contracts/catalog-v1.md). WS-B implements the bodies; signatures are fixed.
export type Capability = 'supported' | 'denied' | 'unavailable' | 'unverified'
export type LaunchOutcome = 'accepted' | 'failed' | 'unknown' // accepted != destination rendered
export type EntrySource = 'companion' | 'tv' | 'curated'

export interface CatalogEntry {
  id: string
  title: string
  kind: 'app' | 'input'
  icon: string | null // basename in tv-catalog/icons, or null
  source: EntrySource
  system: boolean
  unavailable?: boolean // was in a previous catalog, missing now; layout keeps it
}
export interface Catalog { schema: 1; generatedAt: string; tv: { model: string; firmware: string }; entries: CatalogEntry[] }

/** Validates a raw catalog.json value. Drops bad entries; null when the file itself is invalid. */
export function parseCatalog(_raw: unknown): Catalog | null { return null }

/** Catalog bundled into this build (tv-catalog/), else curated candidates. Never throws. */
export function bundledCatalog(): Catalog {
  return { schema: 1, generatedAt: '', tv: { model: '', firmware: '' }, entries: [] }
}

/** Refresh: keeps prev order, marks vanished entries unavailable, appends new ones, no duplicate ids. */
export function mergeEntries(prev: CatalogEntry[], next: CatalogEntry[]): CatalogEntry[] { return [...prev, ...next.filter((n) => !prev.some((p) => p.id === n.id))] }

/** URL usable in <img src> for the entry's bundled icon, or null (show lettered fallback). */
export function iconUrl(_e: CatalogEntry): string | null { return null }
