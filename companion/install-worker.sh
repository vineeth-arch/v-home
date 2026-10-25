#!/usr/bin/env bash
# VNode Mac worker: installs the user LaunchAgent (dry run). No sudo. Does NOT load it unless --load is given.
#   install-worker.sh [--load]
# Test hooks: HOME (everything lives under it), VHOME_NO_LAUNCHCTL=1.
set -euo pipefail

LABEL="com.designinnsaeit.vhome-int-worker"
SRC="$(cd "$(dirname "$0")" && pwd)"
AGENT="$HOME/Library/LaunchAgents/$LABEL.plist"
DIR="$HOME/.vhome-int"
ENVF="$DIR/worker.env"
LOAD=0
case "${1:-}" in
  "") ;;
  --load) LOAD=1 ;;
  *) echo "usage: $0 [--load]"; exit 2 ;;
esac

mkdir -p "$DIR" "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
chmod 700 "$DIR"

if [ ! -e "$ENVF" ]; then
  umask 077
  cat > "$ENVF" <<'ENV'
VNODE_HOST=vnode.local
VNODE_PORT=8443
VNODE_NODE_ID=
VNODE_WORKER_TOKEN=
BRAIN_URL=http://127.0.0.1:8000
BRAIN_VNODE_TOKEN=
BRAIN_INBOX_PATH=
ENV
  chmod 600 "$ENVF"
  echo "Created template $ENVF (empty values)."
else
  echo "Kept existing $ENVF."
fi

# Re-running must not silently revert a live agent to dry run: keep --live if the installed plist has it.
KEEP_LIVE=0
if [ -f "$AGENT" ] && grep -q -e '<string>--live</string>' "$AGENT"; then KEEP_LIVE=1; fi

# XML-escaped substitution (paths may contain & < >)
/usr/bin/python3 -c 'import sys,html; t=open(sys.argv[1]).read(); e=lambda v: html.escape(v, quote=False); t=t.replace("@COMPANION_DIR@", e(sys.argv[2])).replace("@HOME@", e(sys.argv[3])); m="<string>vhome_companion.integrations.worker.main</string>"; t=t.replace(m, m + "\n    <string>--live</string>") if sys.argv[4]=="1" else t; sys.stdout.write(t)' \
  "$SRC/launchd/$LABEL.plist" "$SRC" "$HOME" "$KEEP_LIVE" > "$AGENT"
if [ "$KEEP_LIVE" = 1 ]; then echo "Wrote $AGENT (mode: LIVE, kept --live from the previous install)."
else echo "Wrote $AGENT (mode: dry run, no --live)."; fi

if [ "$LOAD" = 1 ]; then
  [ "${VHOME_NO_LAUNCHCTL:-}" = 1 ] || { launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true; launchctl bootstrap "gui/$(id -u)" "$AGENT"; }
  echo "Agent loaded. Log: $HOME/Library/Logs/vhome-int-worker.log"
else
  cat <<NEXT
Next steps:
  1. Fill in $ENVF (VNODE_HOST can be an IP; node id = sha256 of the Pi cert DER; tokens; BRAIN_INBOX_PATH absolute).
  2. Try one pass: PYTHONPATH="$SRC" /usr/bin/python3 -m vhome_companion.integrations.worker.main --once
  3. Load the agent: $0 --load
  4. After a clean dry-run log, add "--live" to ProgramArguments in $AGENT and reload.
NEXT
fi
