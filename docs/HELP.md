# V/HOME help

V/HOME is two things in one app on your LG TV: an ad-free launcher for your apps and inputs, and a shared household dashboard for two people (plans, tasks, dreams, notes, watch picks, photos). A phone app edits the household content. A small helper on your Mac makes the Home button return to V/HOME.

Anything marked **not yet checked on the TV** works in tests or the desktop preview but has not been tried on the real television. The full list is in [CAPABILITIES.md](CAPABILITIES.md).

## Contents

1. [Quick start](#quick-start)
2. [Using the remote](#using-the-remote)
3. [The Home screen (launcher)](#the-home-screen-launcher)
4. [Editing your layout and folders](#editing-your-layout-and-folders)
5. [Sleep timer](#sleep-timer)
6. [Home button on the TV (Mac helper)](#home-button-on-the-tv-mac-helper)
7. [Our Home](#our-home)
8. [Watch Together](#watch-together)
9. [Us and Idea Wall](#us-and-idea-wall)
10. [Studio (business numbers)](#studio-business-numbers)
11. [Photo frame](#photo-frame)
12. [Quick controls, guest view and modes](#quick-controls-guest-view-and-modes)
13. [Settings on the TV](#settings-on-the-tv)
14. [The phone app](#the-phone-app)
15. [Pairing the TV with the phone](#pairing-the-tv-with-the-phone)
16. [Troubleshooting](#troubleshooting)
17. [All features at a glance](#all-features-at-a-glance)
18. [Limits to know about](#limits-to-know-about)

## Quick start

1. Open V/HOME from the LG app bar (or press Home if the Mac helper is running). It opens on the launcher. You do not need to be paired, online or have the Mac running.
2. Move with the arrow keys, press OK to open an app, press Back to go back.
3. To see your household content (Our Home, Watch Together), pair the TV once with the phone app: [Pairing](#pairing-the-tv-with-the-phone).
4. To make the Home button open V/HOME, set up the Mac helper: [COMPANION.md](COMPANION.md).

## Using the remote

- **Arrow keys** move the highlight. The highlighted item grows slightly and gets a bright outline.
- **OK** opens or presses the highlighted item.
- **Back** closes the top panel first, then returns to the launcher. On the launcher itself, Back asks "Leave V/HOME?" so you do not bounce out by accident.
- **Magic Remote pointer:** moving the pointer over an item highlights it; clicking presses it.
- Holding an arrow key moves quickly. In long lists the page scrolls to keep the highlight in view.

## The Home screen (launcher)

From top to bottom:

- **Header:** time and date, a greeting, weather (once a location is set on the phone), the mode chip (Auto, Home, Morning, Evening) and Quick controls.
- **Personal card:** one short reflection or shared note. It is hidden when nobody is paired and in guest view.
- **Favorites:** up to 10 apps or inputs you chose, 5 per row. Netflix, YouTube, Prime Video, JioHotstar, Apple TV and so on.
- **Folders:** groups of apps you made. Each shows a 2 by 2 preview and how many apps it holds. Press OK to open one.
- **More apps:** every other app on the TV. Apps already in Favorites are not repeated here.
- **Inputs:** HDMI inputs, at the bottom. Scroll down to reach them.
- **Sleep timer panel (right side):** see below.
- **Bottom bar:** Home, Our Home, Watch Together, Settings, and Studio during work hours. It also shows the sleep timer status.

Each tile uses the colour of the app's own icon as its background, so tiles look like the apps. Apps that disappear from the TV stay in your layout greyed out as "Not on this TV" instead of silently vanishing.

The list of apps comes from the TV itself. When you install a new app, V/HOME finds it on the TV and adds it to More apps (with its own icon, if the TV allows V/HOME to list apps; see Settings, Diagnostics). For the matching tile colour and an icon bundled into V/HOME, refresh the list: [Refresh the app list](#refresh-the-app-list).

### Refresh the app list

On the Mac, in the V/HOME folder, one command:

```bash
./scripts/refresh-tv.sh
```

It reads the installed apps and inputs from the TV, downloads their icons, works out each tile colour, rebuilds V/HOME, installs it and opens it. Your layout and pairing are kept.

**Automatic:** the Mac helper checks the TV's app list every 30 minutes. When apps were installed or removed it sends you a Mac notification and shows the change in `status`. To let it refresh by itself:

```bash
PY="$HOME/Library/Application Support/vhome-companion/venv/bin/python"
"$PY" -m vhome_companion autorefresh on     # off to stop
```

With auto refresh on, it runs `scripts/refresh-tv.sh` only when the app list changed, only while V/HOME itself is on screen (it never interrupts another app), and at most once an hour. V/HOME restarts for a few seconds when it does.

## Editing your layout and folders

Open **Edit** (small button beside the Favorites heading), or Settings, Home screen, Edit layout.

**Quick way:** on the Home screen, hold OK on any app (about a second). The editor opens with that app already selected.

1. Pick an app from the list. Buttons appear: **Move earlier**, **Move later** (its place in the app list), **Favorite earlier**, **Favorite later** (its place among your favorites, shown for favorites only), **Add favorite** or **Remove favorite**, **Hide** or **Unhide**, and **Into folder** or **Out of folder**.
2. **New folder** and **Rename** open an on-screen keyboard: arrows move over the letters, OK types, **Space**, **Delete**, **Clear**, **Done**. The first letter of each word is capitalised for you. Leaving the name empty gives a default name (Streaming, Music, Kids, and so on). **Delete** removes the folder and returns its apps to the grid.
3. **Save** keeps your changes. **Cancel** or Back throws them away.

Favorites hold up to 10. Your layout lives on this TV only; the phone does not change it. On first run, favorites are copied once from the apps pinned on the phone.

### Wallpaper and motion

Settings, Home screen: pick one of five wallpapers (Dusk, Ocean, Forest, Ember, Graphite). They are still pictures, never animated. **Reduced motion** turns off the focus animation.

## Sleep timer

The right side of the Home screen has one-click timers: **15, 30, 45, 60 and 90 minutes**, and **Cancel timer**. The line above the buttons shows the timer in force, for example "TV off at 11:30, 24 min left".

How it works: V/TV Sleep is the only thing that actually turns the TV off. When you press a timer button, V/HOME asks V/TV Sleep to start it. V/TV Sleep flashes its own confirmation ("TV OFF IN 30 MIN") for about a second, then returns you to V/HOME with the confirmed time. The status line shows what V/TV Sleep confirmed.

- The same timers are in Quick controls.
- Under the buttons it says when V/TV Sleep last confirmed the timer. **Check timer** asks V/TV Sleep for the true state (it flashes "TV OFF AT …" or "NO TIMER SET" and returns). Use it if you changed the timer in the V/TV Sleep app or from an iPhone.
- V/HOME also checks by itself when you come back to it and it believes a timer is running but the last confirmation is more than 10 minutes old.
- If the status says "Timer status unavailable", the last request has not been confirmed yet. Press a timer button again or **Check timer**.
- Not yet checked on the TV: that the TV actually switches off at the set time.

## Home button on the TV (Mac helper)

LG does not let any app take over the Home button. Instead, a helper on your Mac watches which app is in front over your home network. When LG's Home screen appears, it opens V/HOME. LG Home flashes for under a second, then V/HOME is in front.

What to know:

- It only works while the Mac is on, awake, and on the same network as the TV.
- It never turns the TV on and never interrupts Netflix, YouTube or an HDMI input.
- **Safety limits:** if more than 5 redirects happen within 2 minutes, or 3 fail in a minute, it pauses itself and waits for you.
- **To use LG's own Home screen:** pause the helper. Then press Home as usual.

```bash
PY="$HOME/Library/Application Support/vhome-companion/venv/bin/python"
"$PY" -m vhome_companion pause      # observe only, LG Home stays
"$PY" -m vhome_companion resume     # Home returns to V/HOME again
"$PY" -m vhome_companion status     # connected? how many redirects?
```

Setup, uninstall and troubleshooting: [COMPANION.md](COMPANION.md).

## Our Home

The shared household screen. It fits one page without scrolling:

- A large picture with a quote or your featured dream's affirmation. In the morning: **Start our morning**, **Choose today's step**, **Skip**. In the evening: **Wind down together**. At other times: **Watch Together**. **Next reflection** shows another one.
- **Today and tomorrow:** up to 3 plans or tasks.
- **For us:** a shared note or the next small step toward a dream.
- A row of buttons: **Us**, **Idea Wall** and your first apps.

**Morning ritual:** Imagine, Intend, Act. Pick the one small step for today and who does it. **Evening ritual:** Appreciate, Connect, Imagine, Rest. Both are short card flows; you can skip any time.

Quotes keep their author where known. Affirmations are intentions and visualisation, never guaranteed outcomes. There are no scores or streaks.

## Watch Together

A shortlist for choosing what to watch.

- Filters: **Type** (movie or series), **Time** (up to 60, 90, 120 or 180 minutes), **Mood**.
- Up to 3 best matches for you both, based on each person's vote.
- **Pick for us** chooses one.
- The detail screen shows runtime, who voted what, and where it streams (subscription, rent, buy), then **Open app** launches that streaming app. It opens the app, not the specific title.
- Streaming data comes from TMDB and JustWatch and can be out of date.

Titles and votes are managed on the phone (Watch tab).

## Us and Idea Wall

Reach both from Our Home.

- **Us:** four tabs. **This Week** (this week's plan, task, dream step and date night, plus notes addressed to one of you), **Home Tasks** (press OK to tick one off), **Our Dreams**, **Notes**.
- **Idea Wall:** your ideas, six per page, pinned first, with a status (new, discuss, planned).

The TV can complete a task but cannot create or delete anything; editing happens on the phone.

## Studio (business numbers)

A screen with a few Design Innsaeit numbers (invoices, outreach, questionnaires). It appears in the bottom bar only on work days during work hours (default Monday to Friday, 09:00 to 18:00), never in guest view, and it never opens by itself. Setup and safety details: [STUDIO.md](STUDIO.md). Turn it on or off and set hours in the phone's Studio settings. Not yet checked on the TV.

## Photo frame

After a few idle minutes on Our Home (the delay is set on the phone, 0 means never), the screen becomes a photo frame. It shows "on this day" photos first, then cross-fades through the others. Press any key to leave. Open it yourself from Quick controls. It never fakes remote input, so LG's own auto power-off still applies. Not yet checked on the TV.

## Quick controls, guest view and modes

Quick controls (header chip) holds:

- Timer presets 15, 30, 45, 60 and 90 minutes, a custom time in 5-minute steps, **Cancel timer**.
- **Volume** (Vol −, Vol +, Mute) and **Picture mode** (Standard, Cinema, Vivid, Game, Eco). These appear only if a safe test shows this TV lets V/HOME use them. Settings, Diagnostics says which.
- **Open V/TV Sleep.**
- **Help.**
- Your first apps.
- **Photo frame.**
- **Guest view:** hides plans, notes, dreams and photos until you end it.
- **TV off now** (asks first).

**Modes:** the chip in the header cycles Auto, Home, Morning, Evening. Auto follows the morning and evening times you set on the phone. Morning and evening change the colours and the personal content; they never open anything over another app.

## Settings on the TV

- Household, timezone, timer path and last sync.
- **Unpair this TV** (asks first).
- **Home screen:** wallpaper, reduced motion, Edit layout, hidden apps count.
- **Help:** this guide in short form, readable with the remote.
- **Diagnostics:** how many apps came from where, when the catalog was made, hidden system apps, and what the TV allows (listing apps, timer, Home button). A launch the TV accepts does not prove the app opened.
- If the TV is not paired, Settings shows the pairing code.

## The phone app

Open the V/HOME web app on your phone and sign in. Tabs:

| Tab | What you do there |
|---|---|
| Plans | Events with date and time |
| Tasks | Household tasks and groceries, who owns them |
| Dreams | Dreams with why it matters, affirmation, next small step, art style, optional photo, show on TV |
| Notes | Notes for both of you or for one person (shows on the TV that day) |
| Photos | Add photos, set a date and caption, choose which play in the TV photo frame |
| Ideas | Ideas with status and pin |
| This week | One plan, one task, one dream step and a date night, chosen together |
| Reflections | Add your own, mark favourites, hide built-in ones |
| Watch | Titles, search TMDB, mood, votes |
| Displays | Pair TVs, see paired TVs |
| Settings | Household name and timezone, weather city, streaming region, TV launch pins, extra apps, TV layout, invite your partner, backup, sign out |

**TV layout (phone Settings):** featured dream, which big picture Our Home shows, morning and evening times, whether Today and For us show, the TV's starting mode, and the photo-frame delay. The pinned launch apps on the phone now only seed the launcher favorites the first time; after that the launcher layout is edited on the TV.

**Backup:** Settings, Backup, Export household (one JSON file) or Import.

## Pairing the TV with the phone

1. On the TV open Our Home or Settings. A 6-character code and a QR appear (the code lasts 10 minutes, then refreshes).
2. On the phone open V/HOME, Displays, and enter the code or scan the QR.
3. The household content appears on the TV within seconds. Reopening or upgrading V/HOME keeps the pairing.

To remove a TV: phone, Displays, or TV Settings, Unpair this TV. A removed TV keeps showing its last saved content until it reconnects.

## Troubleshooting

| What you see | What to do |
|---|---|
| Pressing Home does not open V/HOME | Run `status` (see above). Paused? run `resume`. Mac asleep or on another network? The helper only works when the Mac is on and on the TV's network. |
| LG Home stays on screen | The helper may be paused by its safety limit (pressing Home many times quickly). Run `resume`. |
| App tiles show letters, not icons | Run `./scripts/refresh-tv.sh` (see above). |
| An app is greyed "Not on this TV" | It was uninstalled or its id changed. Hide it or remove it in Edit. |
| Timer shows "unavailable" or looks wrong | Press **Check timer**. Make sure V/TV Sleep 0.1.2 or newer is installed. |
| TV shows "Pair this TV" on a household screen | Pair it ([above](#pairing-the-tv-with-the-phone)). The launcher still works unpaired. |
| The TV changed its IP address | Run `"$PY" -m vhome_companion pair --host NEW_IP` and update the saved device: `node_modules/.bin/ares-setup-device --modify tv -i "host=NEW_IP"`. Better: give the TV a fixed address in your router. |
| V/HOME and V/TV Sleep vanished | Developer Mode expired. See [DEV-MODE.md](DEV-MODE.md) and [RECOVERY.md](RECOVERY.md). Extend it in the Developer Mode app before it reaches 0 h. |

More: [RECOVERY.md](RECOVERY.md), [DEV-MODE.md](DEV-MODE.md), [LIMITATIONS.md](LIMITATIONS.md).

## All features at a glance

Launcher
- Hold OK on an app to edit it; type your own folder names with an on-screen keyboard; reorder favorites
- Built-in Help screen (Settings or Quick controls)
- Opens without pairing, internet or the Mac helper
- Colour-matched icon tiles, full scrolling app list, inputs at the bottom
- Up to 10 favorites, folders with previews, hide, reorder, greyed missing apps
- Five wallpapers, reduced motion, remembers where you were when you return from an app
- Real app list and icons taken from your own TV; new apps are found automatically, with an optional one-command (or fully automatic) refresh
- Back asks before leaving

Timer
- One-click 15, 30, 45, 60, 90 minute sleep timers and Cancel, always on screen
- Confirmed by V/TV Sleep, the only thing that turns the TV off
- Check timer asks V/TV Sleep for the true state, so changes made elsewhere show up

Home button
- Mac helper returns Home to V/HOME, with pause, resume and automatic safety limits

Household
- Our Home with morning and evening rituals, reflections, plans, a shared note or small step
- Watch Together with filters, Pick for us and streaming availability
- Us (week, tasks, dreams, notes) and Idea Wall
- Photo frame with "on this day"
- Guest view, modes, Quick controls
- Weather (Open-Meteo)
- Studio business numbers in work hours

Phone
- Plans, tasks, dreams, notes, photos, ideas, weekly check-in, reflections, watch list with TMDB search
- Pair and manage displays, invite your partner, backup and restore

Privacy
- No ads, no tracking, no recommendations, no autoplay
- Household data stays in your own Supabase project; launcher layout stays on the TV

## Limits to know about

- LG's Home screen cannot be replaced, only redirected. It flashes briefly and the redirect needs the Mac running.
- V/HOME cannot open automatically when the TV powers on (see [OPENING.md](OPENING.md)).
- It cannot appear on top of another app; Quick controls exist inside V/HOME only.
- Volume and picture buttons appear only if this TV allows V/HOME to use them. Sound output selection is not offered.
- Developer Mode expires; extend it regularly.
- Streaming availability may be out of date.
- Apple TV, Netflix and other apps show their own ads inside those apps. V/HOME itself has none.
