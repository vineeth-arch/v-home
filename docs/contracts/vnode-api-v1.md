# VNode API v1

Local-only control API of the V/HOME node (Raspberry Pi). HTTPS on port **8443**, self-signed certificate. **Identity = SHA-256 of the certificate (DER), hex lowercase** ("node id"); the phone pins it at pairing. Discovery (`_vhome._tcp`, TXT `api=1`, `id=<first 16 hex>`) only finds candidates, it never establishes trust. No cloud, no internet needed. Python constants: `companion/vhome_companion/vnode/contracts.py`.

## Conventions
- JSON bodies, `Content-Type: application/json`, **max 4096 bytes** (413 otherwise). Unknown fields are rejected (422).
- Auth: `Authorization: Bearer <token>`; per-phone token from `/v1/pair`. The node stores only `sha256(token)`.
- Every state-changing call carries a **nonce** from `GET /v1/nonce`: single use, valid 30 s on the node's monotonic clock. Expired → 410, reused → 409 with the original result in `previous`. Clients never auto-retry a command; on `unknown` they refresh status.
- Command result: `{"outcome": "accepted"|"confirmed"|"failed"|"unknown", "detail": "..."}`.
  - `accepted`: the TV/OS took the command, the effect is not observed yet. `confirmed`: the effect was observed. `unknown`: timeout or link lost.
- Error body: `{"error": "<code>", "detail": "..."}`. Codes: 400 `bad_json`, 401 `unauthorized`, 404, 409 `duplicate`|`busy`, 410 `expired`, 413 `too_large`, 422 `invalid`, 426 `api_mismatch` (client sent `X-VNode-Api` with a major ≠ 1), 429 `rate_limited`, 503 `not_ready`.
- `age_s` is computed on the node (seconds since that thing was observed; `null` = never). Clients add their own fetch age and **must not** compare node and phone wall clocks.

## Unauthenticated
`GET /v1/info` → `{"api": 1, "node_id": "<64 hex>", "name": "vnode", "version": "0.2.0+abc1234", "capabilities": {...}}`.
Capabilities: `launch, pause, tv_pair, diagnostics, device_controls, leds` = `supported|unavailable`. `timer` = `unavailable` (V/TV Sleep stays the only timer; use the TV's own controls). `catalog_sync` = `unavailable` (app builds stay on the Mac/CI). `power_on_launch` = `disabled|unverified`.

`POST /v1/pair` `{"code": "K7QM29XD", "name": "Pixel 8"}` → 200 `{"phone_id": "p_3f9a1c", "token": "<43 chars>"}`.
- The code comes only from `vnode pair-phone` on the Pi: 8 chars of Crockford base32, single use, valid 5 min.
- 5 wrong tries burn the code (401 `unauthorized` each time, then 429 until a new code exists).
- The phone must show the node id (first 24 hex chars in 6 groups of 4, same as `pair-phone` prints) and get the owner's "matches" **before** sending the code.

## Authenticated (Bearer)
`GET /v1/nonce` → `{"nonce": "<22 chars>", "ttl_s": 30}`

`GET /v1/status` →
```json
{
  "api": 1,
  "node": {"id": "…", "version": "…", "uptime_s": 5231, "service": "ok"},
  "headline": "connected",
  "tv": {
    "state": "connected", "host": "192.168.29.225", "paired": true, "power": "Active",
    "foreground": "com.webos.app.livetv", "age_s": 2.1, "last_error": null,
    "pairing": {"state": "idle", "detail": ""}
  },
  "watcher": {
    "state": "watching", "enabled": true, "paused": false, "pause_reason": null,
    "paused_until": null, "redirects": 12, "ok": 12, "failed": 0,
    "last_latency_s": 1.84, "last_failure": null, "last_redirect_age_s": 310.0
  }
}
```
- `tv.state`: `connected | standby | unreachable | pairing_required | certificate_mismatch | permission_denied | launcher_missing | unknown`.
  - `standby` is used only when the TV itself reported Active Standby, Suspend or Power Off. A network failure is `unreachable`.
- `tv.pairing.state`: `idle | waiting_prompt | done | failed`.
- `watcher.state`: `watching | user_paused | safety_paused | disabled | not_ready`.
  - `disabled` = handed to the phone. It never re-enables by itself.
- `headline` = `contracts.headline(tv.state, watcher.state)`.
- `paused_until`: ISO-8601 UTC, or null (until resumed).

`POST /v1/pause` `{"nonce", "minutes": 60}` (`minutes` 1–1440 or omitted = until resume) → `confirmed` once persisted.
`POST /v1/resume` `{"nonce"}` → `confirmed`.
`POST /v1/watcher` `{"nonce", "enabled": false}` → `confirmed` once persisted. A pending launch or recovery is cancelled first.
`POST /v1/tv/launch` `{"nonce"}` → waits ≤ 11 s. Result is `confirmed` (V/HOME seen in front), `accepted`, `failed` or `unknown`. One launch at a time (409 `busy`).
`POST /v1/tv/pair` `{"nonce", "host": "192.168.29.225", "repin": false}` → `accepted`; progress in `tv.pairing`.
- A different certificate than the pinned one fails unless `repin: true`.
- `host` must be an IPv4/IPv6 literal or a `.local` name, ≤ 253 chars.

`GET /v1/tv/discover` → `{"tvs": [{"host": "192.168.29.225", "pinned": true}]}` (≤ 4 s).
`GET /v1/diagnostics` → ≤ 64 KB, redacted: `{"checks": {...}, "log": ["…"], "counters": {...}, "system": {...}}`.
`GET /v1/phones` → `{"phones": [{"id", "name", "created", "this": true}]}`.
`DELETE /v1/phones/{id}` → `{"outcome": "confirmed"}`. Revoking yourself is allowed; the next call gets 401.

### Device controls (Raspberry Pi)
`GET /v1/device` → `{"temp_c": 45.1, "throttled": "0x0", "mem_used_mb": 61, "mem_total_mb": 426, "disk_free_mb": 820, "uptime_s": 9000, "wifi": {"dbm": -69, "bars": 2}, "leds": {"enabled": true, "brightness": 2, "bars": 2, "thermal_off": false, "age_s": 4.0}, "age_s": 0.0}`. `leds` is `null` when the LED service isn't running.
`POST /v1/device/leds` `{"nonce", "enabled": true, "brightness": 2}`. Brightness 1–4 maps to APA102 global brightness 1–4 of 31. → `accepted`; the LED service applies it within 10 s.
`POST /v1/device/restart-service` `{"nonce"}` → `accepted` (restart 1 s after the reply).
`POST /v1/device/reboot` `{"nonce", "confirm": "reboot"}`; `POST /v1/device/shutdown` `{"nonce", "confirm": "shutdown"}` → `accepted`.
- A missing or wrong `confirm` → 422.
- One power action (restart-service, reboot or shutdown) per 60 s, otherwise 429.
- After a shutdown the Pi only comes back after its power is unplugged and plugged in again.

## Local admin socket (Pi only)
`$RUNTIME_DIRECTORY/admin.sock` (`/run/vhome-vnode/admin.sock`, 0600, user `vhome`) serves the same routes without a Bearer token, plus:
- `POST /admin/pairing-code` → `{"code", "node_id", "expires_in_s"}`
- `GET /admin/phones`, `DELETE /admin/phones/{id}`

Access is local file permission only. The `vnode` CLI wrapper uses it via `sudo -u vhome`.

## Not in v1 (on purpose)
Arbitrary SSAP forwarding, shell, file access, timer control, catalog sync, multiple nodes, plugins.
