import { fnv1a } from './daily'

export interface Reflection { id: string; slot: 'morning' | 'evening'; text: string; author?: string; source?: string }

const M = [
  'We are building a life that feels peaceful, connected, and ours.',
  'Today we choose one small step, and let it be enough.',
  'Our home is a place where we both can breathe.',
  'We begin the day with patience and end it with gratitude.',
  'What we tend with care grows. We tend each other first.',
  'There is room in today for something beautiful.',
  'We picture the life we want, then take one gentle step toward it.',
  'May our mornings be unhurried and our intentions kind.',
  'We do not need to do everything. We need to do the next kind thing.',
  'Together, we make ordinary days feel like ours.',
  'We start where we are, with what we have, side by side.',
  'Our dreams are worth a little time each day.',
  'We welcome today with open hands.',
  'Calm is something we can build together, one choice at a time.',
  'We are allowed to want good things for our life.',
  'Let today be steady, warm, and honest.',
  'We imagine it clearly, and we let it guide our next small action.',
  'A good day starts with a good word for each other.',
  'We hold our plans lightly and our people closely.',
  'This morning is a fresh page we write together.',
]
const E = [
  'We put the day down, and we are grateful for what it held.',
  'Rest is part of the work of building a good life.',
  'We are proud of the small things we did today.',
  'What was good today is enough to carry into sleep.',
  'We forgive the unfinished, and we sleep easy.',
  'Tonight we are simply together, and that is plenty.',
  'We let the day go, thanking it as it leaves.',
  'The life we picture is still ours, and tomorrow is another step.',
  'We thank each other for something small today.',
  'Quiet evenings are how we refill.',
  'We release what we cannot change tonight.',
  'Our home is safe, and we are safe in it.',
  'We close the day gently, the way we would like to begin the next.',
  'Whatever happened, we faced it together.',
  'We end the day by remembering one good moment.',
  'Peace is something we return to every evening.',
  'We let our minds rest on the life we are building.',
  'Tonight, nothing needs to be solved.',
  'We are grateful for the ordinary things that held us up.',
  'Rest well. The dream will still be here in the morning.',
]

export const BUNDLED: Reflection[] = [
  ...M.map((text, i) => ({ id: `m${i + 1}`, slot: 'morning' as const, text })),
  ...E.map((text, i) => ({ id: `e${i + 1}`, slot: 'evening' as const, text })),
]

/** One stable item per household-local date per slot. Hidden ids are skipped. Custom items join the pool. */
export function pickDaily(householdId: string, date: string, slot: 'morning' | 'evening', hidden: string[] = [], custom: Reflection[] = []): Reflection | null {
  const pool = [...BUNDLED, ...custom].filter((r) => r.slot === slot && !hidden.includes(r.id))
  if (!pool.length) return null
  return pool[fnv1a(`${householdId}|${date}|${slot}`) % pool.length]
}
