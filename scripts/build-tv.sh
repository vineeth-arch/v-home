#!/usr/bin/env bash
# Build the V/HOME TV IPK. Public values only. Run from repo root.
set -euo pipefail
cd "$(dirname "$0")/.."
# Public values only (URL + publishable key are designed to ship in a client bundle). Never put a service-role key here.
export VITE_SUPABASE_URL="${VITE_SUPABASE_URL:-https://kqmiuhnaeoshjynsttwa.supabase.co}"
export VITE_SUPABASE_PUBLISHABLE_KEY="${VITE_SUPABASE_PUBLISHABLE_KEY:-sb_publishable_-cAGVQpyp55-S8mw1P2giQ_oFiO098u}"
export VITE_PHONE_URL="${VITE_PHONE_URL:-https://v-home-psi.vercel.app}"
npm run check
./scripts/check-secrets.sh
mkdir -p build
node_modules/.bin/ares-package dist-tv -o build/
grep -q kqmiuhnaeoshjynsttwa dist-tv/assets/*.js || { echo 'FAIL: cloud URL missing from TV bundle'; exit 1; }
ls -1 build/*.ipk
