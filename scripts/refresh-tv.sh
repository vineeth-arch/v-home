#!/usr/bin/env bash
# One command: read the TV's apps and icons, rebuild V/HOME with them, install it on the TV and open it.
# The Mac helper can run this by itself (python -m vhome_companion autorefresh on).
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"   # launchd starts with a minimal PATH
STATE="${VHOME_COMPANION_DIR:-$HOME/Library/Application Support/vhome-companion}"
PY="${VHOME_PY:-$STATE/venv/bin/python}"
[ -x "$PY" ] || PY=python3
PYTHONPATH=companion "$PY" -m vhome_companion sync-catalog
./scripts/build-tv.sh
./scripts/install-tv.sh
