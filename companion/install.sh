#!/usr/bin/env bash
# V/HOME companion: user LaunchAgent. No sudo, does not touch Mac sleep settings.
#   install.sh install|update        copy the package, (re)build the venv, (re)load the agent (idempotent)
#   install.sh uninstall [--purge]   remove agent, venv and package copy; --purge also removes pairing and logs
# Test hooks: VHOME_COMPANION_DIR (state dir), VHOME_NO_LAUNCHCTL=1 (do not talk to launchd).
set -euo pipefail

LABEL="com.designinnsaeit.vhome-companion"
SRC="$(cd "$(dirname "$0")" && pwd)"
STATE="${VHOME_COMPANION_DIR:-$HOME/Library/Application Support/vhome-companion}"
AGENT="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$(id -u)"

launchctl_() { [ "${VHOME_NO_LAUNCHCTL:-}" = 1 ] || launchctl "$@"; }

install() {
  local py="${PYTHON:-python3}"
  "$py" -c 'import sys; sys.exit(sys.version_info < (3, 11))' || { echo "Python 3.11+ needed (set PYTHON=...)"; exit 1; }
  mkdir -p "$STATE" "$HOME/Library/LaunchAgents"
  chmod 700 "$STATE"
  rm -rf "$STATE/app"; mkdir "$STATE/app"
  cp -R "$SRC/vhome_companion" "$STATE/app/"
  find "$STATE/app" -name __pycache__ -prune -exec rm -rf {} +
  [ -x "$STATE/venv/bin/python" ] || "$py" -m venv "$STATE/venv"
  "$STATE/venv/bin/python" -m pip install --quiet --disable-pip-version-check -r "$SRC/requirements.txt"
  # lets `venv/bin/python -m vhome_companion ...` work from any directory
  site="$("$STATE/venv/bin/python" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"
  printf '%s\n' "$STATE/app" > "$site/vhome_companion.pth"
  # XML-escaped substitution (paths may contain & < > |)
  "$py" -c 'import sys,html; t=open(sys.argv[1]).read(); e=lambda v: html.escape(v, quote=False); sys.stdout.write(t.replace("@PYTHON@", e(sys.argv[2])).replace("@STATE_DIR@", e(sys.argv[3])))' \
    "$SRC/launchd/$LABEL.plist" "$STATE/venv/bin/python" "$STATE" > "$AGENT"
  launchctl_ bootout "$DOMAIN/$LABEL" 2>/dev/null || true
  launchctl_ bootstrap "$DOMAIN" "$AGENT"
  echo "Installed. Python for manual commands: $STATE/venv/bin/python -m vhome_companion <cmd>"
  [ -s "$STATE/client-key" ] || echo "Not paired yet: run pair, then diag --observe, then re-run this script (see docs/COMPANION.md)."
}

uninstall() {
  launchctl_ bootout "$DOMAIN/$LABEL" 2>/dev/null || true
  rm -f "$AGENT"
  rm -rf "$STATE/venv" "$STATE/app"
  if [ "${1:-}" = "--purge" ]; then
    # only our own files, so a mis-set VHOME_COMPANION_DIR can never wipe an unrelated folder
    rm -f "$STATE"/client-key "$STATE"/cert.sha256 "$STATE"/config.json "$STATE"/state.json "$STATE"/paused "$STATE"/*.lock "$STATE"/companion.log*
    rmdir "$STATE" 2>/dev/null || echo "Left $STATE (it contains other files)."
    echo "Removed agent, venv, pairing, config and logs."
  else
    echo "Removed agent and venv. Pairing and logs kept in: $STATE (use --purge to delete)."
  fi
}

case "${1:-}" in
  install|update) install ;;
  uninstall) uninstall "${2:-}" ;;
  *) echo "usage: $0 install|update|uninstall [--purge]"; exit 2 ;;
esac
