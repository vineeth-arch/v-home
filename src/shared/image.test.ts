import { expect, test } from 'vitest'
import { fitWithin } from './image'

test('fits the longest edge, keeps aspect, never upscales', () => {
  expect(fitWithin(4000, 3000)).toEqual({ w: 1920, h: 1440 })
  expect(fitWithin(3000, 4000)).toEqual({ w: 1440, h: 1920 })
  expect(fitWithin(800, 600)).toEqual({ w: 800, h: 600 })
  expect(fitWithin(1920, 1920)).toEqual({ w: 1920, h: 1920 })
  expect(fitWithin(10000, 1)).toEqual({ w: 1920, h: 1 })
})
