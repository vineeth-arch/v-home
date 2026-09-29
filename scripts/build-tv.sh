#!/usr/bin/env bash
# Build the V/HOME TV IPK. Public values only. Run from repo root.
set -euo pipefail
cd "$(dirname "$0")/.."
export VITE_PHONE_URL="${VITE_PHONE_URL:-https://v-home-psi.vercel.app}"
npm run check
mkdir -p build
node_modules/.bin/ares-package dist-tv -o build/
ls -1 build/*.ipk
