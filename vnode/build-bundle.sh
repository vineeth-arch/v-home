#!/usr/bin/env bash
# Mac: build dist-vnode/vhome-vnode-<version>.tar.gz (package, tests, ops files, VERSION, SHA256SUMS).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

base="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' companion/vhome_companion/__init__.py)"
[ -n "$base" ] || { echo "cannot read __version__" >&2; exit 1; }
hash="$(git rev-parse --short HEAD 2>/dev/null || echo nogit)"
version="$base-$hash"
if [ -n "$(git status --porcelain -- companion vnode 2>/dev/null)" ]; then
  version="$version-dirty"
fi

stage="$(mktemp -d)"
cleanup() { rm -rf "${stage:?}"; }
trap cleanup EXIT

cp -R companion/vhome_companion "$stage/vhome_companion"
cp -R companion/tests "$stage/tests"
cp -R vnode "$stage/vnode"
printf '%s\n' "$version" > "$stage/VERSION"

find "$stage" \( -name __pycache__ -o -name .pytest_cache \) -prune -exec rm -rf {} +
find "$stage" \( -name .DS_Store -o -name '._*' -o -name '*.pyc' \) -delete

# shellcheck disable=SC2094  # SHA256SUMS is excluded from the find
(cd "$stage" && find . -type f ! -name SHA256SUMS -print0 | LC_ALL=C sort -z | xargs -0 shasum -a 256 > SHA256SUMS)

mkdir -p dist-vnode
out="$ROOT/dist-vnode/vhome-vnode-$version.tar.gz"
COPYFILE_DISABLE=1 tar --no-xattrs --no-mac-metadata -czf "$out" -C "$stage" .  # no macOS xattr headers for GNU tar
echo "$out"
