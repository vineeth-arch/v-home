import type { Pref, WatchEntry } from './picker'

export interface Person { id: string; name: string }
export interface PinnedApp { id: string; label: string; verified: boolean }
export interface EventItem { id: string; title: string; at: string; allDay?: boolean }
export interface TaskItem { id: string; title: string; owner: 'both' | string; kind: 'task' | 'grocery'; done: boolean }
export interface Dream { id: string; title: string; why: string; affirmation: string; nextStep: string; targetDate?: string; art: 'sun' | 'hills' | 'sea' | 'window' }
export interface NoteItem { id: string; text: string; author: string }
export interface Idea { id: string; title: string; note: string; status: 'new' | 'discuss' | 'planned' | 'archived'; author: string; pinned?: boolean }
export interface WatchItem { entry: WatchEntry & { summary?: string; providers?: { flatrate?: string[]; rent?: string[]; buy?: string[] }; providersUpdatedAt?: string }; prefs: Record<string, Pref | undefined> }

export interface Snapshot {
  household: { name: string; tz: string; people: Person[]; city?: string; lat?: number; lon?: number; region?: string; pinnedApps: PinnedApp[] }
  events: EventItem[]; tasks: TaskItem[]; dreams: Dream[]; notes: NoteItem[]; ideas: Idea[]; watch: WatchItem[]
  syncedAt: number
}
export const emptySnapshot = (tz = 'Asia/Kolkata'): Snapshot => ({
  household: { name: 'Our Home', tz, people: [], pinnedApps: [] },
  events: [], tasks: [], dreams: [], notes: [], ideas: [], watch: [], syncedAt: Date.now(),
})

// Shown until the household pins its own. IDs are unverified until the on-TV gate.
export const DEFAULT_APPS: PinnedApp[] = [
  { id: 'netflix', label: 'Netflix', verified: false }, { id: 'youtube.leanback.v4', label: 'YouTube', verified: false },
  { id: 'amazon', label: 'Prime Video', verified: false }, { id: 'com.webos.app.hdmi1', label: 'HDMI 1', verified: false },
  { id: 'com.webos.app.hdmi2', label: 'HDMI 2', verified: false }, { id: 'com.designinnsaeit.vtvsleep', label: 'V/TV Sleep', verified: false },
]
export const appsOf = (s: Snapshot): PinnedApp[] => (s.household.pinnedApps.length ? s.household.pinnedApps : DEFAULT_APPS)
