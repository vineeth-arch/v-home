// TMDB proxy. The TMDB token lives only in Supabase secrets (never in a bundle).
// Deployed with --no-verify-jwt and verified here: the gateway check is unreliable with the new signing keys.
import { splitProviders, toEntry, toHit, type MediaType } from '../_shared/tmdb.ts'

const CORS = {
  'Access-Control-Allow-Origin': '*', // auth is by token, so a wildcard origin is safe
  'Access-Control-Allow-Headers': 'authorization, apikey, content-type, x-client-info',
  'Access-Control-Allow-Methods': 'POST, OPTIONS',
}
const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { ...CORS, 'Content-Type': 'application/json' } })

async function caller(req: Request): Promise<{ ok: true } | { ok: false; status: number }> {
  const auth = req.headers.get('Authorization')
  if (!auth) return { ok: false, status: 401 }
  const url = Deno.env.get('SUPABASE_URL')!
  const apikey = Deno.env.get('SUPABASE_ANON_KEY') ?? req.headers.get('apikey') ?? ''
  const r = await fetch(`${url}/auth/v1/user`, { headers: { apikey, Authorization: auth } })
  if (!r.ok) return { ok: false, status: 401 }
  const u = await r.json()
  return u?.is_anonymous ? { ok: false, status: 403 } : { ok: true } // TVs (anonymous) never search
}

const path = (type: MediaType) => (type === 'series' ? 'tv' : 'movie')

Deno.serve(async (req) => {
  if (req.method === 'OPTIONS') return new Response(null, { status: 204, headers: CORS })
  if (req.method !== 'POST') return json(405, { error: 'method_not_allowed' })
  const who = await caller(req)
  if (!who.ok) return json(who.status, { error: who.status === 403 ? 'members_only' : 'unauthorized' })
  const token = Deno.env.get('TMDB_TOKEN')
  if (!token) return json(503, { error: 'tmdb_not_configured' })

  let body: { op?: string; q?: string; id?: number; type?: MediaType; region?: string }
  try { body = await req.json() } catch { return json(400, { error: 'bad_json' }) }
  const get = async (p: string) => {
    const r = await fetch(`https://api.themoviedb.org/3${p}`, { headers: { Authorization: `Bearer ${token}`, Accept: 'application/json' }, signal: AbortSignal.timeout(8000) })
    if (!r.ok) throw new Error(`tmdb ${r.status}`)
    return r.json()
  }
  try {
    if (body.op === 'search') {
      const q = (body.q ?? '').trim()
      if (q.length < 2) return json(200, { results: [] })
      const d = await get(`/search/multi?include_adult=false&language=en-US&query=${encodeURIComponent(q)}`)
      return json(200, { results: (d.results ?? []).map(toHit).filter(Boolean).slice(0, 10) })
    }
    const type: MediaType = body.type === 'series' ? 'series' : 'movie'
    const id = Number(body.id)
    if (!Number.isInteger(id) || id <= 0) return json(400, { error: 'bad_id' })
    const region = (body.region ?? 'IN').toUpperCase().slice(0, 2)
    if (body.op === 'providers') return json(200, { providers: splitProviders(await get(`/${path(type)}/${id}/watch/providers`), region), updatedAt: new Date().toISOString() })
    if (body.op === 'pick') { // details + providers in one round trip
      const [d, p] = await Promise.all([get(`/${path(type)}/${id}?language=en-US`), get(`/${path(type)}/${id}/watch/providers`)])
      return json(200, { entry: toEntry(d, type, splitProviders(p, region)) })
    }
    return json(400, { error: 'unknown_op' })
  } catch (e) {
    return json(502, { error: 'tmdb_unavailable', detail: String(e).slice(0, 120) })
  }
})
