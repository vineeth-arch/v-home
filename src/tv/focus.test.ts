import { expect, test } from 'vitest'
import { BackStack, pickNext, type Box } from './focus'

const boxes: Box[] = [
  { id: 'a', x: 0, y: 0, w: 100, h: 100 }, { id: 'b', x: 200, y: 0, w: 100, h: 100 },
  { id: 'c', x: 0, y: 200, w: 100, h: 100 }, { id: 'd', x: 200, y: 220, w: 100, h: 100 },
]
test('moves to nearest in direction', () => {
  expect(pickNext(boxes, 'a', 'right')).toBe('b')
  expect(pickNext(boxes, 'a', 'down')).toBe('c')
  expect(pickNext(boxes, 'd', 'left')).toBe('c')
  expect(pickNext(boxes, 'd', 'up')).toBe('b')
})
test('edge returns null, no current picks first', () => {
  expect(pickNext(boxes, 'a', 'left')).toBeNull()
  expect(pickNext(boxes, null, 'right')).toBe('a')
})
test('back closes top layer first then exits at root', () => {
  const s = new BackStack(); const log: string[] = []
  s.push('screen', () => log.push('screen')); s.push('overlay', () => log.push('overlay'))
  expect(s.back()).toBe('closed'); expect(s.back()).toBe('closed'); expect(s.back()).toBe('exit')
  expect(log).toEqual(['overlay', 'screen'])
})
