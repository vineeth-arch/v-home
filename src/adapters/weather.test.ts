import { expect, test } from 'vitest'
import { fetchWeather, loadCached, saveCached, weatherView, WMO_LABEL, type Weather } from './weather'

const payload = { current: { temperature_2m: 30.4, weather_code: 2 }, daily: { temperature_2m_max: [33.2, 32], temperature_2m_min: [26.1, 25.5], precipitation_probability_max: [10, 60] } }
const ok = (b: unknown) => (async () => ({ ok: true, status: 200, json: async () => b })) as unknown as typeof fetch

test('fresh result maps and rounds', async () => {
  const w = await fetchWeather(19.07, 72.88, 'Asia/Kolkata', ok(payload), 1000)
  expect(w).toMatchObject({ tempC: 30, label: 'Partly cloudy', hiC: 33, loC: 26, rainPct: 10, tomorrow: { hiC: 32, loC: 26, rainPct: 60 }, fetchedAt: 1000 })
})
test('http error throws so caller keeps the cache', async () => {
  await expect(fetchWeather(1, 1, 'UTC', (async () => ({ ok: false, status: 500 })) as unknown as typeof fetch)).rejects.toThrow('500')
})
const w: Weather = { tempC: 30, label: 'Clear', hiC: 33, loC: 26, rainPct: 0, tomorrow: { hiC: 32, loC: 25, rainPct: 5 }, fetchedAt: 0 }
test('view: null without data, stale after failure, no current after 6h', () => {
  expect(weatherView(null, 0, false)).toBeNull()
  expect(weatherView(w, 60_000, false)).toMatchObject({ stale: false, showCurrent: true })
  expect(weatherView(w, 60_000, true)).toMatchObject({ stale: true, showCurrent: true })
  expect(weatherView(w, 6 * 3600_000 + 1, true)).toMatchObject({ stale: true, showCurrent: false })
})
test('cache is keyed by coordinates', () => {
  saveCached(19.07, 72.88, w)
  expect(loadCached(19.07, 72.88)).toEqual(w)
  expect(loadCached(28.6, 77.2)).toBeNull()
})
test('wmo labels', () => { expect([0, 2, 3, 61, 95].map(WMO_LABEL)).toEqual(['Clear', 'Partly cloudy', 'Overcast', 'Rain', 'Thunderstorm']) })
