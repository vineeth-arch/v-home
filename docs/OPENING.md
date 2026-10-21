# Opening V/HOME instead of LG's ad-filled Home

**What is not possible:** V/HOME cannot replace the Home button, and it cannot force itself to open at power-on. LG's Home is a system app. Doing either would need root or a boot hook, which this project does not do.

**What is possible (settings only, no code)** — on the TV: Settings, General, System, Additional Settings, Home Settings (menu names vary a little by firmware):

1. **Home Promotion: Off** and **Content Recommendation: Off.** This removes the sponsored carousel and recommendation rows from LG Home. ([Pocket-lint](https://www.pocket-lint.com/secret-lg-tv-setting/))
2. **Power On Screen: Recent Input** (older menus: **Home Auto Launch: Off**), so the TV comes back to where you were instead of LG Home. ([Home Assistant thread](https://community.home-assistant.io/t/force-lg-webos-tv-to-start-on-the-home-screen/904090), [LG help](https://www.lg.com/africa/support/product-help/CT20080005-20153711388678))
3. **Quick Start+: On**, so the TV sleeps instead of shutting down and resumes the last app. ([Pocket-lint](https://www.pocket-lint.com/your-lg-tv-could-be-faster-and-all-it-takes-is-turning-off-this-setting/))
4. **Quick Access:** open V/HOME, then long-press a number key (for example 1) and assign it. From then on one press of that key opens V/HOME from anywhere.
5. In LG Home's app bar, move V/HOME to the first position and remove apps you never use (edit mode on the bar).

## Tests (fill in from what actually happens)
| Test | Expected | Result |
|---|---|---|
| A. V/HOME open, power off, power on (after 1 minute) | V/HOME is back | not run |
| A2. Same, after overnight standby | V/HOME is back | not run |
| B. Netflix open, power off, power on | Netflix returns, not V/HOME (known gap; also after a sleep-timer shutdown) | not run |
| C. Power On Screen = Recent Input | TV does not jump to HDMI or Live TV instead | not run |
| Quick Access key opens V/HOME | yes | not run |

## If V/HOME does not come back reliably
A Mac helper now exists (V/HOME 2.0): it watches which app is in front over LG's remote-control connection and opens V/HOME when LG Home appears. LG Home still flashes briefly, and it only works while the Mac is awake and on the same Wi-Fi. It is not verified on this TV yet. Setup, pause and removal: [COMPANION.md](COMPANION.md).
