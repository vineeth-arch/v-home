import { expect, test } from 'vitest'
import { classifyUpdate, type Row } from './api'

const row = (revision: number): Row => ({ id: 'a', household_id: 'h', author_id: 'u', revision, visibility: 'shared', show_on_tv: true, created_at: '' })
test('one updated row is success', () => expect(classifyUpdate([row(2)], null)).toEqual({ ok: true, row: row(2) }))
test('zero updated but row exists is a conflict, not success', () => expect(classifyUpdate([], row(5))).toEqual({ conflict: row(5) }))
test('zero updated and row invisible is denied', () => expect(classifyUpdate([], null)).toEqual({ denied: true }))
test('null update result with existing row is conflict', () => expect(classifyUpdate(null, row(3))).toEqual({ conflict: row(3) }))
