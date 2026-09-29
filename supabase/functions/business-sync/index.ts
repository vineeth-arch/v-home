// Studio sync. Reads aggregate numbers from each Design Innsaeit source project through a read-only role that can only
// call public.di_studio_summary() there, and stores them in business_metrics for the one household named in
// STUDIO_HOUSEHOLD_ID. Connection strings live only in Supabase secrets. Deployed with --no-verify-jwt; auth checked here.
import postgres from 'npm:postgres@3.4.5'
import { createClient } from 'npm:@supabase/supabase-js@2'
import { resolveStudio, sanitizeMetrics, shouldFetch, SOURCES, type MetricRow } from '../_shared/studio.ts'

const CORS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Headers': 'authorization, apikey, content-type, x-client-info',
  'Access-Control-Allow-Methods': 'POST, OPTIONS',
}
const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { ...CORS, 'Content-Type': 'application/json' } })

async function readSource(url: string): Promise<unknown> {
  const sql = postgres(url, { max: 1, prepare: false, connect_timeout: 8, idle_timeout: 2, ssl: url.includes('127.0.0.1') || url.includes('host.docker.internal') ? false : 'require' })
  try {
    const rows = await Promise.race([
      sql`select public.di_studio_summary() as s`,
      new Promise<never>((_, no) => setTimeout(() => no(new Error('timeout')), 8000)),
    ])
    return rows[0]?.s
  } finally { await sql.end({ timeout: 1 }).catch(() => {}) }
}

Deno.serve(async (req) => {
  if (req.method === 'OPTIONS') return new Response(null, { status: 204, headers: CORS })
  if (req.method !== 'POST') return json(405, { error: 'method_not_allowed' })
  const auth = req.headers.get('Authorization')
  if (!auth) return json(401, { error: 'unauthorized' })
  const url = Deno.env.get('SUPABASE_URL')!
  const apikey = Deno.env.get('SUPABASE_ANON_KEY') ?? req.headers.get('apikey') ?? ''
  const u = await fetch(`${url}/auth/v1/user`, { headers: { apikey, Authorization: auth } })
  if (!u.ok) return json(401, { error: 'unauthorized' })
  const user = await u.json()

  const hh = Deno.env.get('STUDIO_HOUSEHOLD_ID')
  const admin = createClient(url, Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!, { auth: { persistSession: false } })
  const { data: m, error: me } = hh ? await admin.from('members').select('role').eq('household_id', hh).eq('user_id', user.id).maybeSingle() : { data: null, error: null }
  if (me) { console.error('studio members lookup:', me.message); return json(500, { error: 'lookup_failed' }) }
  if (!m) return json(403, { error: 'not_studio_household' }) // also covers "Studio not set up"

  let body: { op?: string } = {}
  try { body = await req.json() } catch { /* empty body = sync */ }
  const configured = Object.fromEntries(SOURCES.map((s) => [s.key, !!Deno.env.get(s.secret)]))
  if (body.op === 'status') return json(200, { studio: true, configured })

  const { data: h } = await admin.from('households').select('settings').eq('id', hh).single()
  const st = resolveStudio((h?.settings as Record<string, unknown> | null)?.studio)
  if (!st.enabled) return json(200, { skipped: 'disabled' })
  const { data: last } = await admin.from('business_metrics').select('fetched_at').eq('household_id', hh).order('fetched_at', { ascending: false }).limit(1).maybeSingle()
  if (!shouldFetch(last ? Date.parse(last.fetched_at) : null, Date.now(), m.role === 'member' ? 'member' : 'display')) return json(200, { skipped: 'fresh' })

  const now = new Date().toISOString()
  const report: Record<string, string> = {}
  await Promise.all(SOURCES.map(async (s) => {
    const conn = Deno.env.get(s.secret)
    if (!st.sources[s.key] || !conn) {
      report[s.key] = conn ? 'off' : 'not_configured'
      await admin.from('business_metrics').delete().eq('household_id', hh).eq('source', s.key) // a turned-off source disappears from the TV
      return
    }
    try {
      const rows: MetricRow[] = sanitizeMetrics(s.key, await readSource(conn), st.showNames)
      if (!rows.length) throw new Error('empty')
      const { error } = await admin.from('business_metrics').upsert(rows.map((r) => ({ household_id: hh, ...r, fetched_at: now })))
      if (error) throw error
      await admin.from('business_metrics').delete().eq('household_id', hh).eq('source', s.key).lt('fetched_at', now) // metrics the source no longer returns
      report[s.key] = 'ok'
    } catch (e) {
      // keep the last good numbers; mark them stale so the TV says "as of"
      await admin.from('business_metrics').update({ ok: false }).eq('household_id', hh).eq('source', s.key)
      report[s.key] = 'failed'
      console.error(`studio ${s.key}:`, String(e).slice(0, 200)) // never the connection string
    }
  }))
  return json(200, { synced: report })
})
