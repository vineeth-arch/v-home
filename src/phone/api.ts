import { getClient } from '../shared/supabase'

export interface Row { id: string; household_id: string; author_id: string; revision: number; visibility: 'draft' | 'shared'; show_on_tv: boolean; created_at: string; [k: string]: unknown }
export type SaveResult = { ok: true; row: Row } | { conflict: Row } | { denied: true }

/** Zero updated rows is ambiguous: a newer revision exists (conflict) or RLS hid the row (denied). */
export function classifyUpdate(updated: Row[] | null, latest: Row | null): SaveResult {
  if (updated && updated.length === 1) return { ok: true, row: updated[0] }
  return latest ? { conflict: latest } : { denied: true }
}

const c = () => getClient()
const unwrap = <T,>(r: { data: T | null; error: { message: string } | null }): T => { if (r.error) throw new Error(r.error.message); return r.data as T }

export async function saveRow(table: string, hh: string, existing: Row | null, values: Record<string, unknown>): Promise<SaveResult> {
  if (!existing) {
    const row = unwrap(await c().from(table).insert({ household_id: hh, ...values }).select().single()) as Row
    return { ok: true, row }
  }
  const up = await c().from(table).update(values).eq('id', existing.id).eq('revision', existing.revision).select()
  if (up.error) throw new Error(up.error.message)
  if ((up.data ?? []).length === 1) return classifyUpdate(up.data as Row[], null)
  const latest = await c().from(table).select('*').eq('id', existing.id).maybeSingle()
  return classifyUpdate(null, (latest.data as Row | null) ?? null)
}
export const listRows = async (table: string) => unwrap(await c().from(table).select('*').order('created_at', { ascending: false })) as Row[]
export const removeRow = async (table: string, id: string) => { const r = await c().from(table).delete().eq('id', id); if (r.error) throw new Error(r.error.message) }

export const signUp = async (email: string, password: string) => { const r = await c().auth.signUp({ email, password }); if (r.error) throw r.error; if (!r.data.session) await signIn(email, password) }
export const signIn = async (email: string, password: string) => { const r = await c().auth.signInWithPassword({ email, password }); if (r.error) throw r.error }
export const signOut = () => c().auth.signOut()

export interface Me { userId: string; email: string; householdId: string | null; displayName: string }
export async function getMe(): Promise<Me | null> {
  const { data: { user } } = await c().auth.getUser()
  if (!user || user.is_anonymous) return null
  const m = await c().from('members').select('household_id,display_name').eq('user_id', user.id).eq('role', 'member').maybeSingle()
  return { userId: user.id, email: user.email ?? '', householdId: (m.data?.household_id as string) ?? null, displayName: (m.data?.display_name as string) ?? '' }
}
export const createHousehold = async (name: string, me: string) => unwrap(await c().rpc('create_household', { p_name: name, p_display_name: me })) as string
export const createInvite = async (hh: string) => unwrap(await c().rpc('create_invite', { p_hh: hh })) as string
export const acceptInvite = async (token: string, name: string) => unwrap(await c().rpc('accept_invite', { p_token: token, p_display_name: name })) as string
export const approvePairing = async (code: string, hh: string) => { const r = await c().rpc('approve_pairing', { p_code: code, p_hh: hh }); if (r.error) throw new Error(r.error.message) }
export const revokeDisplay = async (hh: string, tv: string) => { const r = await c().rpc('revoke_display', { p_hh: hh, p_tv: tv }); if (r.error) throw new Error(r.error.message) }
export const listMembers = async () => unwrap(await c().from('members').select('user_id,role,display_name,created_at')) as { user_id: string; role: string; display_name: string; created_at: string }[]
export const getHousehold = async () => unwrap(await c().from('households').select('*').single()) as { id: string; name: string; timezone: string; settings: Record<string, unknown>; revision: number }
export async function saveHousehold(h: { id: string; revision: number }, patch: Record<string, unknown>) {
  const r = await c().from('households').update(patch).eq('id', h.id).eq('revision', h.revision).select()
  if (r.error) throw new Error(r.error.message)
  if ((r.data ?? []).length !== 1) throw new Error('Household changed elsewhere. Reload and try again.')
}
export const listPrefs = async () => unwrap(await c().from('watch_prefs').select('entry_id,user_id,pref')) as { entry_id: string; user_id: string; pref: 'want' | 'maybe' | 'pass' }[]
export async function setPref(entry: string, hh: string, user: string, pref: 'want' | 'maybe' | 'pass') {
  const r = await c().from('watch_prefs').upsert({ entry_id: entry, household_id: hh, user_id: user, pref, updated_at: new Date().toISOString() })
  if (r.error) throw new Error(r.error.message)
}
