// In-app help. Short on purpose (it is read from the sofa); the full guide is docs/HELP.md.
export interface HelpTopic { id: string; title: string; lines: string[] }

export const HELP: HelpTopic[] = [
  { id: 'remote', title: 'Using the remote', lines: [
    'Arrow keys move the highlight. OK opens it.',
    'Back closes the top panel, then returns to Home. On Home, Back asks before leaving.',
    'Magic Remote: point at an item to highlight it, click to press it.',
    'Hold OK on an app to edit it.',
  ] },
  { id: 'home', title: 'The Home screen', lines: [
    'Favorites (up to 9, in a 3x3 grid with a photo card to their right) sit at the top, then your folders, then every other app. HDMI inputs are at the bottom: scroll down.',
    'Each tile takes the colour of the app icon.',
    'An app greyed out as "Not on this TV" was uninstalled. Your layout keeps its place.',
  ] },
  { id: 'edit', title: 'Edit layout and folders', lines: [
    'Hold OK on an app, or press Edit. Choose an app, then move it, favorite it, hide it or put it in a folder.',
    'Favorite earlier and later change the order of your favorites.',
    'New folder and Rename open a keyboard so you can type any name.',
    'Save keeps your changes. Back or Cancel throws them away.',
  ] },
  { id: 'timer', title: 'Sleep timer', lines: [
    'Press 15, 30, 45, 60 or 90 min on the right of Home. V/TV Sleep sets the timer, shows a short confirmation, and brings you back here.',
    'Check timer asks V/TV Sleep for the true time left, in case it was changed elsewhere.',
    'V/TV Sleep is the only thing that turns the TV off.',
  ] },
  { id: 'homebtn', title: 'Home button', lines: [
    'A helper on your Mac reopens V/HOME when LG Home appears. LG Home flashes briefly first.',
    'To use LG Home normally, pause the helper on the Mac: python -m vhome_companion pause.',
    'It only works while the Mac is on and on the same network as the TV.',
  ] },
  { id: 'ourhome', title: 'Our Home', lines: [
    'A shared page for the two of you: a reflection, today and tomorrow, a note or a small step.',
    'Morning and evening rituals start from the big buttons. Us and Idea Wall are the buttons at the bottom of the page.',
    'Plans, notes and dreams are edited on the phone.',
  ] },
  { id: 'watch', title: 'Watch Together', lines: [
    'Filter by type, time and mood. Pick for us chooses one title.',
    'Open app launches the streaming app. It opens the app, not the specific title.',
    'Availability comes from TMDB and JustWatch and can be out of date.',
  ] },
  { id: 'quick', title: 'Quick controls', lines: [
    'Timers, Open V/TV Sleep, your first apps, Photo frame, Guest view, TV off now.',
    'Volume and picture controls appear only if this TV allows V/HOME to use them.',
    'Guest view hides plans, notes, dreams and photos until you end it.',
  ] },
  { id: 'frame', title: 'Photo frame', lines: [
    'After a few idle minutes on Our Home the screen shows your photos, "on this day" first.',
    'Press any key to leave. The delay is set on the phone (0 means never).',
  ] },
  { id: 'pair', title: 'Pairing with the phone', lines: [
    'Home works without pairing. Our Home and Watch Together need it.',
    'Open Our Home or Settings to see the 6-character code. On the phone open V/HOME, Displays, and enter it.',
    'Unpair this TV is in Settings.',
  ] },
  { id: 'apps', title: 'New apps on the TV', lines: [
    'V/HOME checks the TV for new apps each time it opens and adds them to More apps.',
    'For real icons and colours, run the refresh on the Mac: scripts/refresh-tv.sh.',
  ] },
  { id: 'trouble', title: 'If something is wrong', lines: [
    'Home button does nothing: the Mac helper may be paused, asleep or on another network.',
    'Timer says unavailable: press Check timer or press a timer button again.',
    'Apps and V/TV Sleep vanished: Developer Mode expired. Extend it in the Developer Mode app before 0 h.',
    'Settings, Diagnostics shows what this TV allows.',
  ] },
]
