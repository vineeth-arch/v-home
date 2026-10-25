# VNode integrations (opt-in)

An optional second process, `vhome-integrations`, runs beside `vhome-vnode` on the Pi. Phones submit text, URLs or small documents to the node. The node keeps them in a small queue, and a delivery worker picks them up and hands them to Brain. The worker runs on the Mac, or on the Pi itself (next section) so delivery keeps working with the Mac off. The two services share nothing except a unix socket: no `Requires=`, `BindsTo=` or `PartOf=` either way, and `vhome-vnode.service` is not modified. If integrations fail or are disabled, the TV keeps working and the inbox routes answer 503.

## Install (opt-in)

Off by default. Without the flag, install and update behave exactly as before.

    deploy.sh install --with-integrations      # or: update --with-integrations
    sudo bash vnode/install-pi.sh install --with-integrations   # on the Pi

With the flag the installer prints python, aiohttp and sqlite3 versions (sqlite3 >= 3.24 required; if lower, or the users can't be created, integrations are skipped, the TV install continues, and the installer ends with exit 3), creates user `vhome-int` and group `vhome-intsock`, adds `vhome` to `vhome-intsock`, installs the unit and `/usr/local/bin/vnode-int`, and starts the unit only after the TV health check passes. If the integrations unit does not come up within 90 s (a Pi Zero W needs ~25 s) it is disabled with a warning. The TV release is never rolled back or stopped because of integrations. Re-run with the flag to retry, and to restart integrations on a newer release (see below for plain `update` and `rollback`). The 2-release retention applies to both services, since they share `/opt/vhome-vnode/current`.

If `vhome-integrations` is enabled, a plain `update` and `rollback` also restart it (it runs from the same `current` symlink) and run the same 90 s check; when it is not enabled, they do nothing for integrations. If integrations fail to start, the installer disables them, keeps the TV release, prints `TV OK, integrations NOT running (see journalctl -u vhome-integrations)` as the last line and exits with code 3 (0 = all good, 1 = TV failure). `deploy.sh` runs under `set -e`, so it stops with that same code 3 and the line is the last thing shown.

`vhome-vnode` has to restart once after `vhome` joins the new group; the installer does this before its normal TV restart.

## Pi delivers to Brain (Mac off)

The delivery worker can run on the Pi as `vhome-int-deliver`. It talks to the node over its own unix socket (no TLS, no proxy) and to Brain over https at `https://cockpit.vineethnair.com`. Python stdlib only, about 15 MB of RAM; limits 48 MB, 20% CPU, Nice 15, one poll every 60 s, at most 5 jobs per poll, one connection per request. It waits for the clock to sync before the first call to Brain (a Pi Zero has no RTC and TLS needs a date). The TV controller is not touched and nothing orders this unit against it.

Owner steps (once):

1. On Brain, make sure the `vnode_token` exists. Add `/api/status` and `/api/failed` to the Cloudflare Access bypass beside `/api/capture`. Delivery works without that (only `/api/capture` is needed), but the phone then shows an Access warning until it is done. Alternative to the bypass: create a Cloudflare Access service token and pass it as `CF_ACCESS_CLIENT_ID` / `CF_ACCESS_CLIENT_SECRET`.
2. On the Mac, with the Pi reachable, run (replace the host, the secret stays in your shell, not in the command line):

       read -rs BRAIN_VNODE_TOKEN && export BRAIN_VNODE_TOKEN
       vnode/deploy.sh --host 192.168.29.9 update --with-worker

   Optional variables: `BRAIN_URL` (default `https://cockpit.vineethnair.com`), `BRAIN_ALLOW_HOST` (default: the host of `BRAIN_URL`), `CF_ACCESS_CLIENT_ID` + `CF_ACCESS_CLIENT_SECRET`, `VNODE_WORKER_TOKEN` (default: a new worker token is minted on the Pi). `--with-worker` implies `--with-integrations`. The values travel in a private temp file, become `/etc/vhome-int/deliver.env` (0640 root:vhome-int) and the temp file is deleted on both machines. Later updates need no variables: without `BRAIN_VNODE_TOKEN` the existing `deliver.env` is kept and the worker restarts onto the new release.
3. Check: `vnode/deploy.sh --host 192.168.29.9 int-status` shows the worker unit and the queue. The phone's Brain status should say "Reported by delivery worker" within a minute.
4. Stop the Mac worker so the status is not reported twice: `launchctl bootout gui/$(id -u)/com.designinnsaeit.vhome-int-worker`. Running both is safe (a claimed job goes to one worker, Brain dedupes by key), but the two would overwrite each other's status line.

Differences from the Mac worker: documents (`.md`, `.txt`) are sent to Brain as capture text (the job key is the capture key; a label becomes a `# title` line only when the text has no heading) because Brain has no file route and there is no vault folder on the Pi. The Mac worker still writes files when `BRAIN_INBOX_PATH` is set. https is accepted only for exactly the host in `BRAIN_ALLOW_HOST`, with normal certificate checks; `http` stays loopback only.

When Brain cannot be reached, refuses the token or sits behind the Access login, jobs go back to the queue untouched (no attempt is counted) with a plain reason on the job, and polling slows down (up to 10 minutes) until a capture succeeds. Only a 400, 413 or 422 from Brain fails a job. Known gap: a job that makes Brain answer 500 every time is retried forever and, being first in line, holds the queue; cancel it from the phone or `vnode-int recover --fail ID --yes`.

Operate: `journalctl -u vhome-int-deliver -n 50`, `sudo systemctl stop vhome-int-deliver` (stop), `sudo systemctl disable --now vhome-int-deliver` (off). The delivery ledger is in `/var/lib/vhome-int-deliver`. `install-pi.sh uninstall` removes the unit; `--purge` also removes `deliver.env` and the ledger.

## Limits

Unit: 64 MB RAM, 30% CPU, 32 tasks, Nice 10, low IO weight. Payload caps: text 8 KB, URL 2 KB, documents 256 KB, label 40 chars. Queue: 200 live jobs, 500 rows, 8 MB payload directory, 4 MB database, 30 submits per minute per phone. New jobs are refused when free disk is under 400 MB (health warning under 300 MB). Retries: 5 attempts, 30 s backoff doubling to 15 min.

## Retention

Completed and cancelled rows are kept 7 days, failed rows 30 days. A completed payload file is deleted after 1 day, a cancelled one at once. Terminal rows are purged oldest-first past 500 rows. Nothing is purged in the first 10 minutes of uptime or before the clock is synced.

## Encryption, honestly

Traffic is TLS with the node certificate pinned (phone to node, Mac worker to node); the Pi worker uses the local unix socket, and reaches Brain over https with normal certificate checks. Data at rest is NOT encrypted: the queue database and payload files are plaintext on the microSD card in `/var/lib/vhome-integrations`, mode 0700, owned by `vhome-int`. Anyone with the card or root on the Pi can read them. `vhome-int` is not in group `vhome` and cannot read `/var/lib/vhome-vnode` (0700).

Security note: the claim token is sent in the `X-Claim-Token` header. It replaced the query parameter, which leaked into logs and URLs.

## Backup

`deploy.sh backup` archives only `/var/lib/vhome-vnode`. The integrations state directory is NOT included, and `restore` does not touch it. Queued items are transient by design; if you need a copy, run `sudo tar czf ~/int-state.tgz -C /var/lib vhome-integrations` yourself and keep it private.

## Operate

    deploy.sh int-status         # systemctl status + vnode-int stats
    deploy.sh int-inspect        # journal (200 lines), disk free, stats

On the Pi, `vnode-int` runs the admin CLI as `vhome-int`:

    vnode-int stats
    vnode-int recover            # repair after a crash or a corrupt queue
    vnode-int purge              # drop terminal rows and orphan payloads
    vnode-int worker-token       # mint or rotate the Mac worker token

Run `vnode-int --help` for the exact options of each command.

## Disable and uninstall

Disable only (keeps data): `sudo systemctl disable --now vhome-integrations`. Re-enable with `sudo systemctl enable --now vhome-integrations`.

`install-pi.sh uninstall` also removes the integrations unit and wrapper and keeps `/var/lib/vhome-integrations` and the users; add `--purge` to delete the state directory, user `vhome-int` and group `vhome-intsock`.

## What "completed" means

A job is `completed` when Brain's inbox accepted it. It does not mean Brain processed it or filed it into the vault. `unknown` means a lease expired and the outcome is not known.
