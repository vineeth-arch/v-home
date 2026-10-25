# VNode integrations API v1 (contract)

Constants, enums, limits and validators: `companion/vhome_companion/integrations/contracts.py`. This file is the wire shape. Agents do not edit either; they report needed changes.

All errors use the v1 envelope `{"error": code, "detail": str, ...}` with codes from `contracts.Err`.

## Transport

```
phone --TLS pin + phone Bearer--> vhome-vnode :8443 --(intproxy)--> unix socket --> vhome-integrations
Mac worker --TLS pin + worker Bearer--> vhome-vnode :8443 /v1/int/worker/* --(intproxy)--> same socket
Pi worker (vhome-int-deliver) --worker Bearer--> same unix socket directly (no TLS, no proxy); same routes and bodies
```

### Proxy (inside vhome-vnode, `vnode/intproxy.py`)
- Routes: any method on `/v1/inbox/{tail}` and `/v1/int/worker/{tail}`.
- Phone routes: the existing `auth` middleware has already checked the phone token. Proxy drops any client `X-VNode-Phone`, sets `X-VNode-Phone: <phone_id>`, never forwards `Authorization`.
- Phone POSTs need `X-VNode-Nonce` (from `GET /v1/nonce`); proxy consumes it with `api._consume` (409 `duplicate`, 410 `expired`) **before** forwarding.
- Worker routes: exempt from phone auth. Proxy requires `Authorization: Bearer <non-empty>` (else 401 without forwarding) and forwards `Authorization`. After 10 service 401s within 60 s (global) it answers 429 `rate_limited` without forwarding until the window passes.
- Body: read with `request.content.read()` in chunks up to `PROXY_MAX_BODY`; one byte more = 413 `too_large`. `Content-Length` over the cap = 413 before reading.
- Forwards only `contracts.FORWARD_HEADERS` (+ the two above), query string unchanged, path unchanged. Returns status, body and `contracts.RETURN_HEADERS`.
- Fails fast: semaphore 2 (busy = 503 at once, no queueing), connect 1 s, total 8 s, breaker 3 consecutive socket failures -> 503 for 30 s. Socket missing = 503 `integrations_unavailable`. No exception escapes.
- `/v1/info` gains `"int": 1` and `capabilities.inbox = "supported"`.

### Service (vhome-integrations, aiohttp on the unix socket)
Trusts `X-VNode-Phone` (socket is group `vhome-intsock` 0660). Phone routes without it = 401. Worker routes verify `sha256(token)` constant-time against stored worker tokens; the token decides the project.

## Phone routes

| Method | Path | Body / headers | Success |
|---|---|---|---|
| POST | `/v1/inbox/jobs` | raw body; `X-Inbox-Kind: text|url|md|txt`, `X-Idempotency-Key`, optional `X-Label`, `X-VNode-Nonce` | 201 `{"job": Job}`; same key+digest 200 `{"job": Job, "duplicate": true}` |
| GET | `/v1/inbox/jobs?limit=50` | | 200 `{"jobs": [Job], "counts": Counts}` newest first |
| GET | `/v1/inbox/jobs/{id}` | | 200 `{"job": Job}` |
| GET | `/v1/inbox/by-key/{key}` | | 200 `{"job": Job}` / 404 = never stored, safe to resend same key |
| POST | `/v1/inbox/jobs/{id}/cancel` | `X-VNode-Nonce`, empty body | 200 `{"job": Job}`; 409 `not_cancellable` unless queued |
| POST | `/v1/inbox/jobs/{id}/retry` | `X-VNode-Nonce`, empty body | 200 `{"job": Job}`; 409 `not_retryable` unless failed and retry_safe |
| GET | `/v1/inbox/brain-status` | | 200 BrainStatus |

Submit errors: 400 bad payload/key, 409 `key_conflict`, 413, 415, 429 `rate_limited` (30/min/phone) or `queue_full` (+`Retry-After`), 507 `disk_reserve`.

`Job` (phone view; never payload): `{"id","kind","label","status","created_at","updated_at","attempts","result_ref","error_code","error_msg","retry_safe"}`. Times are ISO-8601 UTC strings from the Pi wall clock (informational).

`Counts`: `{"queued","claimed","processing","unknown","completed","failed","cancelled"}`.

`BrainStatus`: `{"snapshot": object|null, "snapshot_age_s": int|null, "stale": bool, "worker_last_seen_age_s": int|null, "worker_stale": bool, "queue": Counts}`. `stale` is true when no snapshot or older than `SNAPSHOT_STALE_S`. UI labels the snapshot "reported by the delivery worker" (it may run on the Pi or the Mac). Status `completed` means "accepted into Brain inbox", never "processed".

## Worker routes (Bearer worker token)

| Method | Path | Body | Success |
|---|---|---|---|
| POST | `/v1/int/worker/claim` | `{"worker": str<=40}` | 200 `{"job": WorkJob}` or `{"job": null}` (empty queue writes nothing) |
| GET | `/v1/int/worker/jobs/{id}/payload` | header `X-Claim-Token` (never a query param) | 200 raw bytes, `Content-Type: application/octet-stream`, `X-Payload-Sha256` |
| POST | `/v1/int/worker/jobs/{id}/start` | `{"claim_token"}` | 200 `{"job": WorkJob}` (claimed -> processing) |
| POST | `/v1/int/worker/jobs/{id}/complete` | `{"claim_token","result_ref"?}` | 200; accepted from claimed, processing **or unknown** when claim_token matches; repeat = 200 |
| POST | `/v1/int/worker/jobs/{id}/fail` | `{"claim_token","error_code","error_msg","retryable":bool}` | 200; retryable and attempts < 5 -> queued with backoff, else failed |
| GET | `/v1/int/worker/unknown` | | 200 `{"jobs": [WorkJob]}` (claim_token included) |
| POST | `/v1/int/worker/reconcile` | `{"job_id","claim_token","action":"requeue"|"complete"|"fail","result_ref"?,"error_code"?,"error_msg"?}` | 200 |
| POST | `/v1/int/worker/brain-status` | JSON object <= 2 KB | 204; RAM only, never written to SD |
| POST | `/v1/int/worker/heartbeat` | `{"worker","version"}` | 204; RAM only |

`WorkJob`: `{"id","op","kind","idempotency_key","label","created_at","attempts","payload_sha256","payload_bytes","claim_token","status"}`. Wrong claim token = 409 `stale_claim`. A job from another project = 404.

## Delivery rules (Mac worker)
- text -> Brain `POST /api/capture {"text"}`; url -> `{"url","insight"?: label}`; both with `Authorization: Bearer $BRAIN_VNODE_TOKEN` and `X-Capture-Key: <idempotency_key>`. `result_ref` = Brain note id. `CF-Access-Client-Id` / `CF-Access-Client-Secret` are added to every Brain call when configured.
- Brain URL: `http` to loopback only, or `https` to exactly the host in `BRAIN_ALLOW_HOST` (default certificate verification).
- Snapshot posted to `/brain-status` (flat): `{"reachable","heartbeat","pending","processed_today","needs_review","failed","last_note_id","at","mode":"dry_run"|"live","auth_error":bool}`.
- Brain 3xx (Cloudflare Access login redirect, never followed) or a 200 HTML login page = `access_blocked` (sets `auth_error`). Any 3xx/401/403/404/408/429/5xx/connection error is environmental: the worker does `reconcile action=requeue` with `error_code` and a plain `error_msg` (attempts unchanged, the reason is kept on the queued job) and stops the pass; it never calls `fail` for these. Only 400/413/422 call `fail` with `retryable:false`.
- `error_code` values the phone maps: `brain_http_401`, `brain_http_403`, `access_blocked`, `brain_http_<5xx>`, `brain_http_<other>`, `name_conflict`, `write_failed`, `bad_payload`, `bad_job`. `error_msg` is a plain sentence, then optionally " Brain said: <60 chars of Brain's `what`, redacted>".
- `/api/status` is not a gate for claiming: only a dead transport to Brain skips the claim loop. A successful capture corrects the snapshot (`reachable` true, `auth_error` false). Snapshot `reachable` is false only for no answer, 404, 408 or 5xx; a login redirect or 401/403 gives `reachable` true, `auth_error` true.
- md/txt without `BRAIN_INBOX_PATH` -> Brain `POST /api/capture {"text": <content>}` with `X-Capture-Key: <idempotency_key>`; a sanitized label is prepended as `# label` only when the content has no markdown heading. `result_ref` = Brain note id.
- md/txt with `BRAIN_INBOX_PATH` -> file `<inbox_path>/<YYYY-MM-DD from created_at> vnode-<key[:16]>.<ext>`, written O_EXCL via temp + rename in the same dir; existing file with same sha256 = already delivered. Ledger `~/.vhome-int/delivered.db` records intent before, delivered after. `result_ref` = filename.
- On wake: `GET unknown` -> reconcile each (ledger says delivered -> complete; else text/url -> requeue (Brain dedupes by key); doc -> check file when an inbox path is set, otherwise requeue) -> then claim loop: 1 job/s, `WORKER_MAX_PER_RUN` per run (default and cap 20; the Pi unit uses 5), poll every `WORKER_POLL_S` (default 30; the Pi unit uses 60; backs off to 10 min while Brain is in trouble). With `WAIT_CLOCK_SYNC=1` no pass runs until `/run/systemd/timesync/synchronized` exists.
- Default `dry_run`: claim one job, log what would be done (id, kind, size), then `reconcile action=requeue` (claimed -> queued, attempts unchanged); never touches Brain. `--live` required to deliver. Heartbeat and brain-status are sent in both modes.
- `reconcile` accepts jobs in claimed, processing or unknown. `action=requeue` may carry `error_code`/`error_msg`; they are stored (redacted, 200 chars) on the queued job and attempts are not counted (except the existing unknown-state rule).

## Pi admin CLI `vnode-int` (admin socket 0600, run as vhome-int)
`stats`, `jobs [--status S]`, `show ID`, `recover --requeue|--fail ID --yes`, `purge --terminal --yes`, `worker-token create|list|revoke ID`, `vacuum`. Tokens are printed once at create and stored only as sha256.
