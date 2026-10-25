#!/usr/bin/env bash
# Mac: build the bundle, copy it to the Pi and run install-pi.sh there. You type the sudo password in the ssh session.
# usage: deploy.sh [--host vnode.local] [--user vnode] [--stop-mac-watcher] [install|update|rollback|status|diag|backup|restore FILE|uninstall] [extra args]
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
  install|update|rollback|status|diag|backup|restore|uninstall) ;;
  *) echo "unknown command: $CMD" >&2; exit 2 ;;
esac

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
