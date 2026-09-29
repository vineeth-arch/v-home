#!/usr/bin/env bash
# Install the newest IPK on the TV named "tv" in ~/.webos (shared with V/TV Sleep; that app is untouched).
set -euo pipefail
cd "$(dirname "$0")/.."
IPK=$(ls -t build/com.designinnsaeit.vhome_*.ipk | head -1)
node_modules/.bin/ares-install --device "${VTV_DEVICE:-tv}" "$IPK"
node_modules/.bin/ares-launch --device "${VTV_DEVICE:-tv}" com.designinnsaeit.vhome
