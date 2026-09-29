import type { Pref, WatchEntry } from './picker'
import { DEFAULT_PREFS, type TvPrefs } from './prefs'
import type { Reflection } from './reflections'
import type { WeeklyPayload } from './week'

export interface Person { id: string; name: string }
export interface PinnedApp { id: string; label: string; verified: boolean }
export interface EventItem { id: string; title: string; at: string; allDay?: boolean }
export interface TaskItem { id: string; title: string; owner: 'both' | string; kind: 'task' | 'grocery'; done: boolean }
export interface Dream { id: string; title: string; why: string; affirmation: string; nextStep: string; targetDate?: string; art: 'sun' | 'hills' | 'sea' | 'window' }
export interface NoteItem { id: string; text: string; author: string }
export interface Idea { id: string; title: string; note: string; status: 'new' | 'discuss' | 'planned' | 'archived'; author: string; pinned?: boolean }
export interface WatchItem { entry: WatchEntry & { summary?: string; providers?: { flatrate?: string[]; rent?: string[]; buy?: string[] }; providersUpdatedAt?: string }; prefs: Record<string, Pref | undefined> }

export interface Snapshot {
  household: { id: string; name: string; tz: string; hiddenReflections: string[]; people: Person[]; city?: string; lat?: number; lon?: number; region?: string; pinnedApps: PinnedApp[]; prefs: TvPrefs }
  events: EventItem[]; tasks: TaskItem[]; dreams: Dream[]; notes: NoteItem[]; ideas: Idea[]; watch: WatchItem[]
  quotes: Reflection[]; weekly?: { day: string } & WeeklyPayload
  syncedAt: number
}
export const emptySnapshot = (tz = 'Asia/Kolkata'): Snapshot => ({
  household: { id: '', name: 'Our Home', tz, hiddenReflections: [], people: [], pinnedApps: [], prefs: DEFAULT_PREFS },
  events: [], tasks: [], dreams: [], notes: [], ideas: [], watch: [], quotes: [], syncedAt: Date.now(),
})

// Shown until the household pins its own. IDs are unverified until the on-TV gate.
export const CANDIDATE_APPS: PinnedApp[] = [
  { id: 'netflix', label: 'Netflix', verified: false }, { id: 'youtube.leanback.v4', label: 'YouTube', verified: false },
  { id: 'amazon', label: 'Prime Video', verified: false }, { id: 'com.webos.app.hdmi1', label: 'HDMI 1', verified: false },
  { id: 'com.webos.app.hdmi2', label: 'HDMI 2', verified: false }, { id: 'com.designinnsaeit.vtvsleep', label: 'V/TV Sleep', verified: false },
]
/** The launch strip shows at most 6 (design-system.md). Until the household chooses, the first 6 candidates. */
export const DEFAULT_STRIP = (): PinnedApp[] => CANDIDATE_APPS.slice(0, 6)
export const appsOf = (s: Snapshot): PinnedApp[] => (s.household.pinnedApps.length ? s.household.pinnedApps : DEFAULT_STRIP())
