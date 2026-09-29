#!/usr/bin/env bash
# Fails if a built bundle contains a real secret shape. Library strings like startsWith("sb_secret_") are ignored.
set -uo pipefail
cd "$(dirname "$0")/.."
bad=0
for f in dist/assets/*.js dist-tv/assets/*.js; do
  [ -f "$f" ] || continue
  if grep -Eq 'sb_secret_[A-Za-z0-9_-]{16,}|service_role"?[:=] *"?eyJ|eyJ[A-Za-z0-9_-]{20,}\.eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}' "$f"; then echo "SECRET-LIKE CONTENT in $f"; bad=1; fi
done
[ $bad -eq 0 ] && echo "clean: no secret-shaped strings in dist/ or dist-tv/"
exit $bad
