// Open-Meteo (no key). Never guesses a location; caller supplies coordinates from household settings.
export interface Weather { tempC: number; label: string; hiC: number; loC: number; rainPct: number; tomorrow: { hiC: number; loC: number; rainPct: number }; fetchedAt: number }
export interface WeatherView extends Weather { stale: boolean; showCurrent: boolean }

export const WMO_LABEL = (c: number): string =>
  c === 0 ? 'Clear' : c <= 2 ? 'Partly cloudy' : c === 3 ? 'Overcast' : c <= 48 ? 'Fog' : c <= 57 ? 'Drizzle' : c <= 67 ? 'Rain' : c <= 77 ? 'Snow' : c <= 82 ? 'Showers' : c <= 86 ? 'Snow showers' : 'Thunderstorm'

export async function fetchWeather(lat: number, lon: number, tz: string, fetchFn: typeof fetch = fetch, now = Date.now()): Promise<Weather> {
  const u = `https://api.open-meteo.com/v1/forecast?latitude=${lat}&longitude=${lon}&current=temperature_2m,weather_code&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max&forecast_days=2&timezone=${encodeURIComponent(tz)}`
  const r = await fetchFn(u)
  if (!r.ok) throw new Error(`weather ${r.status}`)
  const d = await r.json()
  const day = (i: number) => ({ hiC: Math.round(d.daily.temperature_2m_max[i]), loC: Math.round(d.daily.temperature_2m_min[i]), rainPct: Math.round(d.daily.precipitation_probability_max[i] ?? 0) })
  return { tempC: Math.round(d.current.temperature_2m), label: WMO_LABEL(d.current.weather_code), ...day(0), tomorrow: day(1), fetchedAt: now }
}

export const STALE_CURRENT_MS = 6 * 3600_000
/** null when nothing to show. After 6h the reading is no longer called "current". `failed` marks a failed refresh. */
export function weatherView(w: Weather | null, now: number, failed: boolean): WeatherView | null {
  if (!w) return null
  const age = now - w.fetchedAt
  return { ...w, stale: failed || age > 15 * 60_000 * 2, showCurrent: age <= STALE_CURRENT_MS }
}

const KEY = 'vhome.weather.v1'
export const loadCached = (lat: number, lon: number, ls: Storage = localStorage): Weather | null => {
  try { const r = JSON.parse(ls.getItem(KEY) ?? 'null'); return r && r.lat === lat && r.lon === lon ? (r.w as Weather) : null } catch { return null }
}
export const saveCached = (lat: number, lon: number, w: Weather, ls: Storage = localStorage) => { try { ls.setItem(KEY, JSON.stringify({ lat, lon, w })) } catch { /* private mode */ } }
