// Pure helpers shared by the Edge Function and the phone app. No Deno or browser APIs here.
export interface Providers { flatrate: string[]; rent: string[]; buy: string[] }
export type MediaType = 'movie' | 'series'
export interface TmdbHit { id: number; type: MediaType; title: string; year: number | null; summary: string; posterPath: string | null }

const names = (v: unknown): string[] => (Array.isArray(v) ? v.map((p) => (p as { provider_name?: string })?.provider_name).filter((n): n is string => typeof n === 'string') : [])

/** TMDB watch/providers response, narrowed to one region. A missing region gives empty lists. */
export function splitProviders(raw: unknown, region: string): Providers {
  const r = ((raw as { results?: Record<string, Record<string, unknown>> })?.results ?? {})[region.toUpperCase()] ?? {}
  return { flatrate: names(r.flatrate), rent: names(r.rent), buy: names(r.buy) }
}

/** Movies: runtime. Series: first episode_run_time, else the last aired episode's runtime, else unknown (never 0). */
export function runtimeOf(d: any, type: MediaType): number | null {
  const pos = (n: unknown) => (typeof n === 'number' && n > 0 ? Math.round(n) : null)
  if (type === 'movie') return pos(d?.runtime)
  return pos(Array.isArray(d?.episode_run_time) ? d.episode_run_time[0] : undefined) ?? pos(d?.last_episode_to_air?.runtime)
}

const yearOf = (s: unknown) => (typeof s === 'string' && /^\d{4}/.test(s) ? Number(s.slice(0, 4)) : null)

/** search/multi result to a hit; people and other media types are dropped. */
export function toHit(r: any): TmdbHit | null {
  if (r?.media_type !== 'movie' && r?.media_type !== 'tv') return null
  const type: MediaType = r.media_type === 'tv' ? 'series' : 'movie'
  const title = type === 'series' ? r.name : r.title
  if (typeof r.id !== 'number' || typeof title !== 'string' || !title) return null
  return { id: r.id, type, title, year: yearOf(type === 'series' ? r.first_air_date : r.release_date), summary: typeof r.overview === 'string' ? r.overview : '', posterPath: typeof r.poster_path === 'string' ? r.poster_path : null }
}

/** details response + providers to watch_entries columns. */
export function toEntry(d: any, type: MediaType, providers: Providers, now = new Date()) {
  const title = type === 'series' ? d?.name : d?.title
  return {
    tmdb_id: d?.id as number, type, title: String(title ?? ''), summary: typeof d?.overview === 'string' ? d.overview : null,
    runtime_min: runtimeOf(d, type), poster_path: typeof d?.poster_path === 'string' ? d.poster_path : null,
    service: providers.flatrate[0] ?? null, providers, providers_updated_at: now.toISOString(),
    metadata: { year: yearOf(type === 'series' ? d?.first_air_date : d?.release_date) },
  }
}
