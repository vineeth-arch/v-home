#!/usr/bin/env bash
# Mac: build the bundle, copy it to the Pi and run install-pi.sh there. You type the sudo password in the ssh session.
# usage: deploy.sh [--host vnode.local] [--user vnode] [--stop-mac-watcher] [install|update|rollback|status|diag|backup|restore FILE|uninstall|int-status|int-inspect] [extra args]
#   install|update accept --with-integrations (opt-in vhome-integrations; passed through to install-pi.sh).
#   install|update also accept --with-worker (implies --with-integrations): the delivery worker runs ON the Pi and posts to
#     Brain with the Mac off. Secrets come from environment variables on this Mac, never from arguments:
#       BRAIN_VNODE_TOKEN (required the first time)   BRAIN_URL (default https://cockpit.vineethnair.com)
#       BRAIN_ALLOW_HOST (default: host of BRAIN_URL)  CF_ACCESS_CLIENT_ID + CF_ACCESS_CLIENT_SECRET (optional, both)
#       VNODE_WORKER_TOKEN (optional; default: minted on the Pi)
#     They travel in a 0600 temp file (scp), which the Pi installer turns into /etc/vhome-int/deliver.env and deletes.
#     Without BRAIN_VNODE_TOKEN an existing deliver.env on the Pi is kept as is.
#   int-status / int-inspect only read from the Pi (no bundle is built or copied).
#   backup copies the archive to ./vnode-backups/ on the Mac; restore FILE sends a Mac-side archive to the Pi.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOST=vnode.local
USER_=vnode
STOP_MAC=0
LABEL=com.designinnsaeit.vhome-companion

while [ $# -gt 0 ]; do
  case "$1" in
    --host) HOST="${2:?--host needs a value}"; shift 2 ;;
    --user) USER_="${2:?--user needs a value}"; shift 2 ;;
    --stop-mac-watcher) STOP_MAC=1; shift ;;
    *) break ;;
  esac
done
CMD="${1:-install}"
if [ $# -gt 0 ]; then shift; fi
case "$CMD" in
  install|update|rollback|status|diag|backup|restore|uninstall|int-status|int-inspect) ;;
  *) echo "unknown command: $CMD" >&2; exit 2 ;;
esac

# Read-only integrations views; sudo is typed in the ssh session. vnode-int itself runs sudo -u vhome-int.
if [ "$CMD" = int-status ]; then
  ssh -t "$USER_@$HOST" "systemctl status vhome-integrations --no-pager; systemctl status vhome-int-deliver --no-pager 2>&1 | head -n 12; vnode-int stats"
  exit 0
elif [ "$CMD" = int-inspect ]; then
  ssh -t "$USER_@$HOST" "sudo journalctl -u vhome-integrations -n 200 --no-pager; sudo journalctl -u vhome-int-deliver -n 50 --no-pager; df -h / /var/lib/vhome-integrations; vnode-int stats"
  exit 0
fi

if [ "$CMD" = install ] || [ "$CMD" = update ]; then
  if launchctl print "gui/$(id -u)/$LABEL" >/dev/null 2>&1; then
    echo "WARNING: the Mac watcher ($LABEL) is loaded." >&2
    echo "WARNING: two watchers (Mac and Pi) will both launch V/HOME on the TV. Stop one before testing." >&2
    if [ "$STOP_MAC" = 1 ]; then
      launchctl bootout "gui/$(id -u)/$LABEL"
      echo "Mac watcher stopped (its files are untouched)." >&2
    else
      echo "WARNING: re-run with --stop-mac-watcher to stop it." >&2
    fi
  fi
fi

tarball="$("$HERE/build-bundle.sh" | tail -n 1)"
name="$(basename "$tarball")"
echo "Bundle: $tarball"

scp "$tarball" "$USER_@$HOST:/tmp/$name"

stamp="$(date +%Y%m%d-%H%M%S)"
if [ "$CMD" = restore ]; then
  local_file="${1:?restore needs the backup file on this Mac}"; shift
  scp "$local_file" "$USER_@$HOST:/tmp/vnode-restore-$stamp.tar.gz"
  set -- "/tmp/vnode-restore-$stamp.tar.gz" "$@"
elif [ "$CMD" = backup ]; then
  set -- "/tmp/vnode-backup-$stamp.tar.gz"
fi

# --with-worker: hand the Brain settings to the Pi through a private file, not through argv or the terminal.
WORKER_TMP=""
WORKER_REMOTE=""
want_worker=0
for a in "$@"; do if [ "$a" = --with-worker ]; then want_worker=1; fi; done
if [ "$want_worker" = 1 ] && [ -n "${BRAIN_VNODE_TOKEN:-}" ]; then
  WORKER_TMP="$(umask 077; mktemp)"
  # also runs when the installer exits non-zero (set -e), so the secrets file never lingers on either machine
  cleanup_worker() {
    rm -f "$WORKER_TMP"
    # shellcheck disable=SC2029  # path expands on the Mac on purpose
    if [ -n "$WORKER_REMOTE" ]; then ssh "$USER_@$HOST" "rm -f $WORKER_REMOTE" || true; fi
  }
  trap cleanup_worker EXIT
  {
    printf 'BRAIN_URL=%s\n' "${BRAIN_URL:-https://cockpit.vineethnair.com}"
    printf 'BRAIN_VNODE_TOKEN=%s\n' "$BRAIN_VNODE_TOKEN"
    if [ -n "${BRAIN_ALLOW_HOST:-}" ]; then printf 'BRAIN_ALLOW_HOST=%s\n' "$BRAIN_ALLOW_HOST"; fi
    if [ -n "${CF_ACCESS_CLIENT_ID:-}" ] && [ -n "${CF_ACCESS_CLIENT_SECRET:-}" ]; then
      printf 'CF_ACCESS_CLIENT_ID=%s\nCF_ACCESS_CLIENT_SECRET=%s\n' "$CF_ACCESS_CLIENT_ID" "$CF_ACCESS_CLIENT_SECRET"
    fi
    if [ -n "${VNODE_WORKER_TOKEN:-}" ]; then printf 'VNODE_WORKER_TOKEN=%s\n' "$VNODE_WORKER_TOKEN"; fi
  } > "$WORKER_TMP"
  WORKER_REMOTE="/tmp/vnode-deliver-env-$stamp"
  scp -q "$WORKER_TMP" "$USER_@$HOST:$WORKER_REMOTE"
  rm -f "$WORKER_TMP"
  set -- "$@" --worker-env-file "$WORKER_REMOTE"
elif [ "$want_worker" = 1 ]; then
  echo "BRAIN_VNODE_TOKEN is not set: keeping the delivery settings already on the Pi (if any)." >&2
fi

extra=""
if [ $# -gt 0 ]; then extra="$(printf '%q ' "$@")"; fi
qname="$(printf '%q' "$name")"
# shellcheck disable=SC2029  # expansion on the Mac side is intended
ssh -t "$USER_@$HOST" "cd /tmp && rm -rf vhome-vnode-bundle && mkdir vhome-vnode-bundle && tar xzf $qname -C vhome-vnode-bundle && sudo bash vhome-vnode-bundle/vnode/install-pi.sh $CMD $extra"

if [ "$CMD" = backup ]; then
  mkdir -p "$HERE/../vnode-backups"; chmod 700 "$HERE/../vnode-backups"
  scp "$USER_@$HOST:/tmp/vnode-backup-$stamp.tar.gz" "$HERE/../vnode-backups/"
  chmod 600 "$HERE/../vnode-backups/vnode-backup-$stamp.tar.gz"
  # shellcheck disable=SC2029  # stamp expands on the Mac on purpose
  ssh "$USER_@$HOST" "rm -f /tmp/vnode-backup-$stamp.tar.gz"
  echo "Backup saved on this Mac: vnode-backups/vnode-backup-$stamp.tar.gz (contains credentials; keep it private)"
elif [ "$CMD" = restore ]; then
  # shellcheck disable=SC2029  # stamp expands on the Mac on purpose
  ssh "$USER_@$HOST" "rm -f /tmp/vnode-restore-$stamp.tar.gz"
fi
