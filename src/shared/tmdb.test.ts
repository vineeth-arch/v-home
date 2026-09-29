import { expect, test } from 'vitest'
import { runtimeOf, splitProviders, toEntry, toHit } from '../../supabase/functions/_shared/tmdb'

const prov = { results: { IN: { flatrate: [{ provider_name: 'Netflix' }, { provider_name: 'JioHotstar' }], rent: [{ provider_name: 'Apple TV' }] }, US: { buy: [{ provider_name: 'Vudu' }] } } }
test('providers are narrowed to the region; missing region is empty', () => {
  expect(splitProviders(prov, 'in')).toEqual({ flatrate: ['Netflix', 'JioHotstar'], rent: ['Apple TV'], buy: [] })
  expect(splitProviders(prov, 'FR')).toEqual({ flatrate: [], rent: [], buy: [] })
  expect(splitProviders(null, 'IN')).toEqual({ flatrate: [], rent: [], buy: [] })
})
test('runtime: movies use runtime, series fall back through episode lengths, unknown stays null', () => {
  expect(runtimeOf({ runtime: 148 }, 'movie')).toBe(148)
  expect(runtimeOf({ runtime: 0 }, 'movie')).toBeNull()
  expect(runtimeOf({ episode_run_time: [42, 50] }, 'series')).toBe(42)
  expect(runtimeOf({ episode_run_time: [], last_episode_to_air: { runtime: 55 } }, 'series')).toBe(55)
  expect(runtimeOf({ episode_run_time: [] }, 'series')).toBeNull()
})
test('search hits: movie and tv kept, people dropped, series use name and first_air_date', () => {
  expect(toHit({ media_type: 'movie', id: 1, title: 'Inception', release_date: '2010-07-16', overview: 'x', poster_path: '/p.jpg' })).toEqual({ id: 1, type: 'movie', title: 'Inception', year: 2010, summary: 'x', posterPath: '/p.jpg' })
  expect(toHit({ media_type: 'tv', id: 2, name: 'Dark', first_air_date: '2017-12-01' })).toMatchObject({ type: 'series', title: 'Dark', year: 2017, posterPath: null })
  expect(toHit({ media_type: 'person', id: 3, name: 'Someone' })).toBeNull()
  expect(toHit({ media_type: 'movie', id: 4 })).toBeNull()
})
test('entry maps runtime, first subscription service and a timestamp', () => {
  const e = toEntry({ id: 9, title: 'Film', runtime: 96, overview: 'o', release_date: '2020-01-01', poster_path: '/a.jpg' }, 'movie', splitProviders(prov, 'IN'), new Date('2026-09-30T00:00:00Z'))
  expect(e).toMatchObject({ tmdb_id: 9, title: 'Film', runtime_min: 96, service: 'Netflix', poster_path: '/a.jpg', providers_updated_at: '2026-09-30T00:00:00.000Z', metadata: { year: 2020 } })
  expect(toEntry({ id: 1, name: 'S' }, 'series', { flatrate: [], rent: [], buy: [] }).service).toBeNull()
})
