// Labelled sample data. Used only by the simulation data source (never shipped as household content).
import type { Snapshot } from './model'
import { DEFAULT_PREFS } from './prefs'

const day = (offset: number, hhmm: string) => {
  const d = new Date(); d.setDate(d.getDate() + offset)
  return `${d.toISOString().slice(0, 10)}T${hhmm}:00+05:30`
}

export const fixtureSnapshot = (): Snapshot => ({
  household: {
    name: 'Our Home', tz: 'Asia/Kolkata', city: 'Sample City', prefs: DEFAULT_PREFS,
    people: [{ id: 'p1', name: 'Vineeth' }, { id: 'p2', name: 'Partner' }],
    pinnedApps: [
      { id: 'netflix', label: 'Netflix', verified: false }, { id: 'youtube.leanback.v4', label: 'YouTube', verified: false },
      { id: 'amazon', label: 'Prime Video', verified: false }, { id: 'com.webos.app.hdmi1', label: 'HDMI 1', verified: false },
      { id: 'com.webos.app.hdmi2', label: 'HDMI 2', verified: false }, { id: 'com.designinnsaeit.vtvsleep', label: 'V/TV Sleep', verified: false },
    ],
  },
  events: [
    { id: 'e1', title: 'Dinner with the family', at: day(0, '20:00') },
    { id: 'e2', title: 'Plumber visit', at: day(1, '10:30') },
    { id: 'e3', title: 'Date night', at: day(2, '19:30') },
    { id: 'e4', title: 'Anniversary weekend', at: day(9, '09:00'), allDay: true },
  ],
  tasks: [
    { id: 't1', title: 'Order the balcony plants', owner: 'p2', kind: 'task', done: false },
    { id: 't2', title: 'Pay electricity bill', owner: 'p1', kind: 'task', done: false },
    { id: 't3', title: 'Fix the bedroom curtain rod', owner: 'both', kind: 'task', done: true },
    { id: 't4', title: 'Milk, eggs, bread', owner: 'both', kind: 'grocery', done: false },
    { id: 't5', title: 'Coffee beans', owner: 'p1', kind: 'grocery', done: false },
  ],
  dreams: [
    { id: 'd1', title: 'A slow morning by the sea', why: 'We want a day with no clock in it.', affirmation: 'We are building a life that feels peaceful, connected, and ours.', nextStep: 'Look at three coastal stays for next spring', targetDate: '2027-03-15', art: 'sea' },
    { id: 'd2', title: 'A reading corner with a window', why: 'Somewhere quiet that is ours.', affirmation: 'Our home makes room for rest.', nextStep: 'Measure the corner and pick a chair', art: 'window' },
  ],
  notes: [
    { id: 'n1', text: 'Thank you for handling the morning rush this week.', author: 'p2' },
    { id: 'n2', text: 'Dinner tonight is on me.', author: 'p1' },
  ],
  ideas: [
    { id: 'i1', title: 'Paint the hallway a warm sand', note: 'Try two test patches first.', status: 'discuss', author: 'p2', pinned: true },
    { id: 'i2', title: 'Weekend trip to the hills', note: 'Maybe October, three nights.', status: 'planned', author: 'p1', pinned: true },
    { id: 'i3', title: 'Anniversary gift ideas', note: 'Something handmade.', status: 'new', author: 'p1' },
    { id: 'i4', title: 'Balcony herb garden', note: 'Basil, mint, curry leaf.', status: 'new', author: 'p2' },
    { id: 'i5', title: 'Movie night projector', note: 'Check budget.', status: 'discuss', author: 'p1' },
    { id: 'i6', title: 'Cooking class together', note: 'Something regional.', status: 'new', author: 'p2' },
    { id: 'i7', title: 'Bookshelf by the window', note: 'Build or buy?', status: 'new', author: 'p2' },
    { id: 'i8', title: 'Old sofa', note: 'Donate.', status: 'archived', author: 'p1' },
  ],
  watch: [
    { entry: { id: 'w1', title: 'A Quiet Harbor', type: 'movie', runtimeMin: 96, service: 'Netflix', mood: 'calm', summary: 'A fisherman and a stranger share one winter.' }, prefs: { p1: 'want', p2: 'want' } },
    { entry: { id: 'w2', title: 'Kitchen Diaries', type: 'series', runtimeMin: 42, service: 'Prime Video', mood: 'light', summary: 'A gentle series about a family restaurant.' }, prefs: { p1: 'maybe', p2: 'want' } },
    { entry: { id: 'w3', title: 'The Long Night', type: 'movie', runtimeMin: 148, service: 'Netflix', mood: 'intense', summary: 'A thriller across a single night.' }, prefs: { p1: 'want', p2: 'pass' } },
    { entry: { id: 'w4', title: 'Hills of Home', type: 'movie', runtimeMin: null, service: 'YouTube', mood: 'calm', summary: 'A documentary about mountain villages.' }, prefs: { p1: 'want', p2: 'maybe' } },
    { entry: { id: 'w5', title: 'Sunday Table', type: 'series', runtimeMin: 30, service: 'Netflix', mood: 'light', summary: 'Short episodes about cooking together.' }, prefs: { p1: 'want', p2: 'want' } },
  ],
  syncedAt: Date.now(),
})

export const fixtureWeather = { tempC: 27, hiC: 31, loC: 24, rainPct: 20, tomorrow: { hiC: 30, loC: 24, rainPct: 40 }, label: 'Partly cloudy' }
