import { describe, expect, it } from 'vitest'
import { notesForToday, sharedNote } from './partnerNotes'

const now = new Date('2026-09-30T15:00:00Z') // 20:30 IST
const n = (id: string, to: string | undefined, at: string) => ({ id, text: id, author: 'a', to, at })

describe('partner notes', () => {
  it('shared slot skips addressed notes', () => {
    expect(sharedNote([n('x', 'p2', '2026-09-30T10:00:00Z'), n('y', undefined, '2026-09-30T09:00:00Z')])?.id).toBe('y')
  })
  it('keeps the newest note per recipient from today only (IST day boundary)', () => {
    const notes = [n('new', 'p2', '2026-09-30T14:00:00Z'), n('old', 'p2', '2026-09-30T12:00:00Z'), n('yday', 'p1', '2026-09-29T18:00:00Z'), n('early', 'p1', '2026-09-29T19:00:00Z')]
    // 2026-09-29T19:00Z is 00:30 IST on the 30th, so it counts; 18:00Z is 23:30 IST on the 29th, so it doesn't
    expect(notesForToday(notes, now, 'Asia/Kolkata').map((x) => x.id)).toEqual(['new', 'early'])
  })
})
