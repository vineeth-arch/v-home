# Third-party notices

V/HOME includes or adapts material from the projects below. Inspection date for the licence statements: 2026-10-21.

## Code adapted from MIT-licensed projects

### OmkarK97/webos-vibehack

- Source: https://github.com/OmkarK97/webos-vibehack
- Licence: MIT. Copyright (c) 2026 Gathin, Copyright (c) 2026 OmkarK97. (GitHub's licence detector labels the repo "NOASSERTION" because the LICENSE file also carries a separate font notice; the MIT text itself is intact.)
- Used by: the Mac companion (SSAP session setup and registration shape, foreground-app subscription, launch-point and HDMI input sync). The watcher is a rewrite; the notice applies to the portions adapted from the original.
- The design of its launcher UI comes from tv-vibehack by Gathin (https://github.com/Gathin23/tv-vibehack). V/HOME does not use that UI.
- Not used: the Outfit font (SIL Open Font License 1.1) bundled in that project. If it is ever bundled with V/HOME, add its OFL notice here.

### zzeppieri/webos-custom-home

- Source: https://github.com/zzeppieri/webos-custom-home
- Licence: MIT. Copyright (c) 2026 zzeppieri.
- Used by: the launch-point parsing idea in `src/shared/apps.ts` (`parseLaunchPoints`, reading `launchPoints` from `listLaunchPoints`), as credited in the code comment. No files are copied. The project's root-only parts (Home key takeover, boot autostart) are not used.

## MIT licence text

The MIT licence applies to the two projects above with the copyright lines shown, reproduced once here:

```
MIT License

Copyright (c) 2026 Gathin
Copyright (c) 2026 OmkarK97
Copyright (c) 2026 zzeppieri

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Projects consulted, no code used

These informed the design (protocol facts, behaviour reports, ideas). No source was copied or adapted, so no notice is required. They are listed for credit and so the licence status is on record.

| Project | Licence | How it was used |
|---|---|---|
| home-assistant-libs/aiowebostv | Apache-2.0 | Reference for the unsigned registration shape, endpoint names, and issue reports about newer firmware |
| chros73/bscpylgtv | MIT | Reference for endpoint and button names |
| belikh/ha-lg-webos-tv | MIT | Idea: liveness probe and reconnect lock |
| partridgeworks/webos-launcher | MIT | Reference for which Luna calls a sideloaded web app may use; input list shape |
| NoriginMedia/Norigin-Spatial-Navigation | MIT | Compared against the built-in focus system; not used |
| motiondivision/motion | MIT | Evaluated; not used |
| TanStack/virtual | MIT | Evaluated; not used |
| foridpathan/smart-tv-starter | MIT | Read; not used |
| nitesh-k-sahu/tv-spatial-navigation-monorepo | MIT | Read; not used |
| home-assistant/frontend | Apache-2.0 | Design ideas only |
| jellyfin/jellyfin-webos | MPL-2.0 | Reference for webOS packaging conventions only; no files copied |
| mariotaku/moonlight-tv | GPL-3.0 | Reference only (confirms an LG Home app id as a fact); no code |
| immich-app/immich | AGPL-3.0 | Ideas only (slideshow settings); no code |
| Shantil-K/OpenLauncher | GPL-3.0 (source headers say another licence; treated as GPL-3.0) | Concept only, independent implementation; no code |
| spydey74/lg-webos-bsc | none stated | Not used. Without a licence, no reuse is permitted |

Product and app names (LG, webOS, Netflix, YouTube and others) are trademarks of their owners. V/HOME is not affiliated with or endorsed by them.
