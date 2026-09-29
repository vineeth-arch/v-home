import { createClient, type SupabaseClient } from '@supabase/supabase-js'

// Publishable key only. Service-role and TMDB secrets never belong in a bundle.
const url = import.meta.env.VITE_SUPABASE_URL as string | undefined
const key = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY as string | undefined
export const supabaseConfigured = Boolean(url && key)

let client: SupabaseClient | null = null
export function getClient(): SupabaseClient {
  if (!url || !key) throw new Error('Supabase is not configured (see .env.example)')
  return (client ??= createClient(url, key, { auth: { persistSession: true, autoRefreshToken: true } }))
}
