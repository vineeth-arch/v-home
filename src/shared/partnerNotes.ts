import type { NoteItem } from './model'
import { localDate } from './daily'

/** The shared "A note" slot on Our Home: newest note that isn't addressed to one person. Notes arrive newest first. */
export const sharedNote = (notes: NoteItem[]) => notes.find((n) => !n.to)

/** "A note for you" cards: newest note per recipient, written today (household timezone). */
export function notesForToday(notes: NoteItem[], now: Date, tz: string): NoteItem[] {
  const today = localDate(now, tz), seen = new Set<string>(), out: NoteItem[] = []
  for (const n of notes) {
    if (!n.to || !n.at || seen.has(n.to) || localDate(new Date(n.at), tz) !== today) continue
    seen.add(n.to); out.push(n)
  }
  return out
}
