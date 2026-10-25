#!/usr/bin/env bash
# V/HOME node installer. Runs on the Raspberry Pi as root, from inside the extracted bundle:
#   sudo bash vnode/install-pi.sh <command> [options] [args]
# Commands: install | update | rollback | uninstall [--purge] | backup [OUT] | restore FILE | status | diag
# Options:  --keep-wifi-powersave (leave Wi-Fi power save alone)   --no-leds (skip the LED service)
set -euo pipefail

BUNDLE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OPT=/opt/vhome-vnode
STATE=/var/lib/vhome-vnode
SVC_USER=vhome
HEALTH_URL=https://127.0.0.1:8443/v1/info
UNIT_DIR=/etc/systemd/system
POLKIT_FILE=/etc/polkit-1/rules.d/50-vhome.rules
AVAHI_FILE=/etc/avahi/services/vhome-vnode.service
JOURNALD_FILE=/etc/systemd/journald.conf.d/50-vhome.conf
NM_FILE=/etc/NetworkManager/conf.d/50-vhome-wifi-powersave.conf
WRAPPER=/usr/local/bin/vnode

KEEP_WIFI=0
NO_LEDS=0
PURGE=0

log() { printf '== %s\n' "$*"; }
warn() { printf 'WARNING: %s\n' "$*" >&2; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

# version_ge A B: true when dotted version A >= B (numeric parts only)
version_ge() {
  local IFS=. i
  local -a a b
  read -r -a a <<< "$1"
  read -r -a b <<< "$2"
  for i in 0 1 2 3; do
    if (( ${a[i]:-0} > ${b[i]:-0} )); then return 0; fi
    if (( ${a[i]:-0} < ${b[i]:-0} )); then return 1; fi
  done
  return 0
}

# archive_names_ok: reads tar member names on stdin; fails on absolute paths, '..' parts or names outside vhome-vnode/
archive_names_ok() {
  local n
  while IFS= read -r n; do
    case "$n" in
      /*) echo "absolute path in archive: $n" >&2; return 1 ;;
      ..|../*|*/..|*/../*) echo "'..' in archive: $n" >&2; return 1 ;;
      vhome-vnode|vhome-vnode/*) ;;
      *) echo "unexpected entry in archive: $n" >&2; return 1 ;;
    esac
  done
}

# archive_types_ok: reads `tar tv` lines on stdin; only regular files and directories are allowed (no links, devices)
archive_types_ok() {
  local line
  while IFS= read -r line; do
    case "${line:0:1}" in
      -|d) ;;
      *) echo "unsupported entry type in archive: $line" >&2; return 1 ;;
    esac
  done
}

has_leds() { [ "$NO_LEDS" = 0 ]; }

units() {
  if has_leds; then echo "vhome-vnode vhome-leds"; else echo "vhome-vnode"; fi
}

# ---- preflight -------------------------------------------------------------------------

preflight() {
  log "Preflight"
  [ "$(id -u)" -eq 0 ] || die "run as root: sudo bash $0 ..."
  if ! tr -d '\0' < /proc/device-tree/model 2>/dev/null | grep -q "Raspberry Pi"; then
    die "this is not a Raspberry Pi (/proc/device-tree/model)"
  fi
  local arch
  arch="$(uname -m)"
  case "$arch" in
    armv6l) ;;
    armv7l|aarch64) warn "architecture $arch (expected armv6l on a Zero W); continuing" ;;
    *) die "unsupported architecture $arch" ;;
  esac
  local ver
  # shellcheck source=/dev/null
  ver="$(. /etc/os-release && echo "${VERSION_ID:-0}")"
  version_ge "$ver" 12 || die "Raspberry Pi OS / Debian 12 or newer needed (found VERSION_ID=$ver)"
  python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' || die "python3 >= 3.11 needed"
  local free_mb
  free_mb="$(df -Pm / | awk 'NR == 2 { print $4 }')"
  [ "${free_mb:-0}" -ge 200 ] || die "only ${free_mb:-0} MB free on /, need at least 200 MB"
  if [ -f "$BUNDLE/SHA256SUMS" ]; then
    (cd "$BUNDLE" && sha256sum -c --quiet SHA256SUMS) || die "bundle checksum mismatch (corrupt copy?)"
  fi
  [ -f "$BUNDLE/VERSION" ] || die "bundle has no VERSION file; run from the extracted bundle"
  echo "ok: $(tr -d '\0' < /proc/device-tree/model), $arch, ${free_mb} MB free"
}

# ---- packages and user -----------------------------------------------------------------

install_packages() {
  log "Packages"
  local pkg
  local -a missing=() want=(python3-aiohttp python3-websockets polkitd avahi-daemon openssl)
  has_leds && want+=(python3-libgpiod)
  for pkg in "${want[@]}"; do
    dpkg -s "$pkg" >/dev/null 2>&1 || missing+=("$pkg")
  done
  if [ "${#missing[@]}" -gt 0 ]; then
    echo "installing: ${missing[*]}"
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "${missing[@]}"
  else
    echo "all packages present"
  fi
  python3 -c "import aiohttp, websockets; print('aiohttp', aiohttp.__version__, 'websockets', websockets.__version__)"
  if has_leds; then
    python3 -c "import gpiod; print('gpiod', getattr(gpiod, '__version__', '?'))" || die "python3 gpiod missing"
  fi
}

ensure_user() {
  log "Service user"
  if ! id "$SVC_USER" >/dev/null 2>&1; then
    useradd --system --home-dir "$STATE" --no-create-home --shell /usr/sbin/nologin "$SVC_USER"
  fi
  if has_leds; then
    if getent group gpio >/dev/null; then
      usermod -aG gpio "$SVC_USER"
    else
      warn "no gpio group; the LED service will not be able to open /dev/gpiochip0"
    fi
  fi
}

# ---- release ---------------------------------------------------------------------------

prune_releases() {
  local keep_a keep_b d
  keep_a="$(readlink -f "$OPT/current" 2>/dev/null || true)"
  keep_b="$(cat "$OPT/previous" 2>/dev/null || true)"
  for d in "$OPT"/releases/*; do
    [ -d "$d" ] || continue
    if [ "$d" != "$keep_a" ] && [ "$d" != "$keep_b" ]; then
      echo "removing old release $(basename "$d")"
      rm -rf "${d:?}"
    fi
  done
}

install_release() {
  log "Release"
  local version dest tmp prev
  version="$(tr -d '[:space:]' < "$BUNDLE/VERSION")"
  case "$version" in *[!A-Za-z0-9._+-]*|"") die "bad VERSION: $version" ;; esac
  dest="$OPT/releases/$version"
  mkdir -p "$OPT/releases"
  chown root:root "$OPT" "$OPT/releases"
  chmod 0755 "$OPT" "$OPT/releases"
  tmp="$dest.new"
  rm -rf "${tmp:?}"
  mkdir "$tmp"
  cp -R "$BUNDLE/vhome_companion" "$BUNDLE/tests" "$BUNDLE/VERSION" "$tmp/"
  find "$tmp" -name __pycache__ -prune -exec rm -rf {} +
  chown -R root:root "$tmp"
  find "$tmp" -type d -exec chmod 0755 {} +
  find "$tmp" -type f -exec chmod 0644 {} +
  prev="$(readlink -f "$OPT/current" 2>/dev/null || true)"
  rm -rf "${dest:?}"
  mv "$tmp" "$dest"
  if [ -n "$prev" ] && [ "$prev" != "$dest" ]; then
    printf '%s\n' "$prev" > "$OPT/previous"
  fi
  ln -sfn "$dest" "$OPT/current.tmp"
  mv -T "$OPT/current.tmp" "$OPT/current"
  prune_releases
  echo "current -> $dest"
}

# ---- state and certificate ---------------------------------------------------------------

make_cert() {
  local cn_args=(-x509 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -nodes -subj "/CN=vnode"
                 -keyout "$STATE/key.pem" -out "$STATE/cert.pem")
  # fixed validity so the identity never "expires" on a Pi without a clock
  if ! openssl req "${cn_args[@]}" -not_before 20200101000000Z -not_after 20991231235959Z 2>/dev/null; then
    openssl req "${cn_args[@]}" -days 27000
  fi
}

ensure_state() {
  log "State and certificate"
  mkdir -p "$STATE"
  chown "$SVC_USER:$SVC_USER" "$STATE"
  chmod 0700 "$STATE"
  if [ ! -s "$STATE/cert.pem" ] || [ ! -s "$STATE/key.pem" ]; then
    echo "generating the node certificate (once)"
    make_cert
  else
    echo "keeping the existing node certificate"
  fi
  chown "$SVC_USER:$SVC_USER" "$STATE/cert.pem" "$STATE/key.pem"
  chmod 0600 "$STATE/cert.pem" "$STATE/key.pem"
  if [ ! -f "$STATE/leds.json" ]; then
    printf '{"enabled": true, "brightness": 2}\n' > "$STATE/leds.json"
    chown "$SVC_USER:$SVC_USER" "$STATE/leds.json"
    chmod 0600 "$STATE/leds.json"
  fi
}

node_id16() {
  openssl x509 -in "$STATE/cert.pem" -outform DER | sha256sum | cut -c1-16
}

# ---- config files ------------------------------------------------------------------------

CHANGED=0
# put SRC DST MODE: install a file if different; sets CHANGED=1 when it wrote
put() {
  CHANGED=0
  if [ -f "$2" ] && cmp -s "$1" "$2"; then
    chmod "$3" "$2"
    return 0
  fi
  install -D -o root -g root -m "$3" "$1" "$2"
  CHANGED=1
}

install_files() {
  log "System files"
  local v="$BUNDLE/vnode" tmp
  put "$v/systemd/vhome-vnode.service" "$UNIT_DIR/vhome-vnode.service" 0644
  if has_leds; then
    put "$v/systemd/vhome-leds.service" "$UNIT_DIR/vhome-leds.service" 0644
  fi
  put "$v/polkit/50-vhome.rules" "$POLKIT_FILE" 0644

  tmp="$(mktemp)"
  sed "s/@NODE_ID16@/$(node_id16)/" "$v/avahi/vhome-vnode.service" > "$tmp"
  put "$tmp" "$AVAHI_FILE" 0644
  rm -f "$tmp"

  put "$v/conf/journald-vhome.conf" "$JOURNALD_FILE" 0644
  if [ "$CHANGED" = 1 ]; then
    systemd-tmpfiles --create --prefix /var/log/journal 2>/dev/null || true
    mkdir -p /var/log/journal
    systemctl restart systemd-journald
    echo "journald now persistent (16 MB cap)"
  fi

  if [ "$KEEP_WIFI" = 1 ]; then
    echo "keeping Wi-Fi power save as is (--keep-wifi-powersave)"
  else
    put "$v/conf/nm-wifi-powersave.conf" "$NM_FILE" 0644
    if [ "$CHANGED" = 1 ]; then
      echo "Wi-Fi power save drop-in written; it applies on the next Wi-Fi reconnect or reboot"
      echo "(NetworkManager is NOT restarted here, that could drop this SSH session)"
    fi
  fi

  put "$v/bin/vnode" "$WRAPPER" 0755
  systemctl daemon-reload
  systemctl reload avahi-daemon 2>/dev/null || warn "avahi-daemon not reloaded (is it running?)"
}

# ---- start and health ----------------------------------------------------------------------

HEALTH_PY='
import json, ssl, sys, urllib.request
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE   # local check only, never leaves this machine
with urllib.request.urlopen(sys.argv[1], timeout=3, context=ctx) as r:
    sys.exit(0 if json.load(r).get("api") == 1 else 1)
'

health_check() {
  local i
  log "Health check ($HEALTH_URL, up to 30 s)"
  for i in $(seq 1 30); do
    if python3 -c "$HEALTH_PY" "$HEALTH_URL" 2>/dev/null; then
      echo "healthy after ${i}s"
      return 0
    fi
    sleep 1
  done
  return 1
}

restart_units() {
  local u
  for u in $(units); do
    systemctl enable "$u" >/dev/null 2>&1
    systemctl restart "$u"
  done
  if has_leds; then
    sleep 2
    systemctl is-active --quiet vhome-leds || warn "vhome-leds is not running (no pHAT BEAT / gpio?): journalctl -u vhome-leds -n 20"
  fi
}

switch_to() {  # switch_to DIR: atomically repoint current
  ln -sfn "$1" "$OPT/current.tmp"
  mv -T "$OPT/current.tmp" "$OPT/current"
}

cmd_install() {
  preflight
  install_packages
  ensure_user
  install_release
  ensure_state
  install_files
  log "Start"
  restart_units
  if ! health_check; then
    journalctl -u vhome-vnode -n 50 --no-pager || true
    local prev
    prev="$(cat "$OPT/previous" 2>/dev/null || true)"
    if [ -n "$prev" ] && [ -d "$prev" ]; then
      warn "health check failed; rolling back to $prev"
      switch_to "$prev"
      restart_units
      health_check || warn "previous release is not healthy either"
    else
      warn "health check failed and there is no previous release"
    fi
    exit 1
  fi
  echo "node id: $(node_id16)...  version: $(basename "$(readlink -f "$OPT/current")")"
}

cmd_rollback() {
  [ "$(id -u)" -eq 0 ] || die "run as root"
  local cur prev
  cur="$(readlink -f "$OPT/current" 2>/dev/null || true)"
  prev="$(cat "$OPT/previous" 2>/dev/null || true)"
  [ -n "$prev" ] && [ -d "$prev" ] || die "no previous release to roll back to"
  switch_to "$prev"
  printf '%s\n' "$cur" > "$OPT/previous"
  echo "current -> $prev (previous -> $cur)"
  restart_units
  health_check || die "rolled back, but the node is not healthy"
}

cmd_uninstall() {
  [ "$(id -u)" -eq 0 ] || die "run as root"
  log "Uninstall"
  local u
  for u in vhome-vnode vhome-leds; do
    systemctl disable --now "$u" 2>/dev/null || true
    rm -f "$UNIT_DIR/$u.service"
  done
  rm -f "$POLKIT_FILE" "$AVAHI_FILE" "$JOURNALD_FILE" "$NM_FILE" "$WRAPPER"
  rm -rf "${OPT:?}"
  systemctl daemon-reload
  systemctl reload avahi-daemon 2>/dev/null || true
  if [ "$PURGE" = 1 ]; then
    rm -rf "${STATE:?}"
    if id "$SVC_USER" >/dev/null 2>&1; then userdel "$SVC_USER" || true; fi
    echo "purged $STATE and removed user $SVC_USER"
  else
    echo "kept $STATE (certificate, TV key, phone tokens) and user $SVC_USER; use --purge to remove them"
  fi
  echo "kept: apt packages, journald persistence is no longer configured (restart systemd-journald or reboot to apply)"
  echo "kept: Wi-Fi power save returns to the default on the next reconnect or reboot"
}

# ---- backup / restore ----------------------------------------------------------------------

default_backup_path() {
  local who="${SUDO_USER:-root}" home
  home="$(getent passwd "$who" | cut -d: -f6)"
  echo "${home:-/root}/vnode-backup-$(date +%Y%m%d-%H%M%S).tar.gz"
}

cmd_backup() {
  [ "$(id -u)" -eq 0 ] || die "run as root"
  local out="${1:-$(default_backup_path)}"
  [ -d "$STATE" ] || die "no state directory $STATE"
  (umask 077 && tar czf "$out" -C "$(dirname "$STATE")" "$(basename "$STATE")")
  chmod 0600 "$out"
  if [ -n "${SUDO_USER:-}" ]; then chown "$SUDO_USER" "$out"; fi
  echo "backup: $out"
  warn "this archive holds credentials (TV client key, node private key, phone token hashes). Keep it private."
}

cmd_restore() {
  [ "$(id -u)" -eq 0 ] || die "run as root"
  local file="${1:-}"
  [ -n "$file" ] && [ -f "$file" ] || die "usage: restore FILE"
  tar tzf "$file" | archive_names_ok || die "refusing to restore: unsafe archive"
  tar tvzf "$file" | archive_types_ok || die "refusing to restore: unsafe archive"
  log "Restore"
  local u
  for u in vhome-leds vhome-vnode; do systemctl stop "$u" 2>/dev/null || true; done
  if [ -d "$STATE" ]; then cmd_backup; fi
  mkdir -p "$STATE"
  tar xzf "$file" -C "$(dirname "$STATE")" --no-same-owner
  chown -R "$SVC_USER:$SVC_USER" "$STATE"
  chmod 0700 "$STATE"
  find "$STATE" -type d -exec chmod 0700 {} +
  find "$STATE" -type f -exec chmod 0600 {} +
  restart_units
  health_check || die "restored, but the node is not healthy"
}

# ---- status / diag --------------------------------------------------------------------------

cmd_status() {
  local u cur prev
  for u in vhome-vnode vhome-leds; do
    printf '%s: %s\n' "$u" "$(systemctl is-active "$u" 2>/dev/null || true)"
  done
  cur="$(readlink -f "$OPT/current" 2>/dev/null || true)"
  prev="$(cat "$OPT/previous" 2>/dev/null || true)"
  echo "current:  ${cur:+$(basename "$cur")}"
  echo "previous: ${prev:+$(basename "$prev")}"
  if systemctl is-active --quiet vhome-vnode && [ -x "$WRAPPER" ]; then
    "$WRAPPER" status || true
  fi
}

throttled_now() {
  local t d
  if command -v vcgencmd >/dev/null 2>&1 && t="$(vcgencmd get_throttled 2>/dev/null)" && [ -n "$t" ]; then
    echo "${t#throttled=}"; return
  fi
  for d in /sys/class/hwmon/hwmon*; do
    if [ "$(cat "$d/name" 2>/dev/null)" = rpi_volt ]; then
      if [ "$(cat "$d/in0_lcrit_alarm" 2>/dev/null)" = 1 ]; then echo "0x1 (under-voltage now)"; else echo 0x0; fi
      return
    fi
  done
  echo "unknown"
}

cmd_diag() {
  echo "model:     $(tr -d '\0' < /proc/device-tree/model 2>/dev/null)"
  # shellcheck source=/dev/null
  echo "os:        $(. /etc/os-release && echo "$PRETTY_NAME"), kernel $(uname -r) $(uname -m)"
  echo "python:    $(python3 --version 2>&1)"
  python3 -c "import aiohttp, websockets; print('libs:      aiohttp', aiohttp.__version__, 'websockets', websockets.__version__)" 2>&1 || true
  echo "uptime:    $(uptime -p)"
  if [ -r /sys/class/thermal/thermal_zone0/temp ]; then
    echo "temp:      $(awk '{printf "%.1f C", $1/1000}' /sys/class/thermal/thermal_zone0/temp)"
  fi
  echo "throttled: $(throttled_now)"
  echo "-- memory"; free -m
  echo "-- disk"; df -h /
  local pid
  pid="$(systemctl show -p MainPID --value vhome-vnode 2>/dev/null || echo 0)"
  if [ "${pid:-0}" != 0 ]; then
    echo "-- vhome-vnode process (rss KB, cpu %, elapsed)"
    ps -o rss,pcpu,etime -p "$pid"
  else
    echo "-- vhome-vnode is not running"
  fi
  echo "-- journal"; journalctl --disk-usage || true
  echo "-- last 30 lines (vhome-vnode, vhome-leds)"
  journalctl -u vhome-vnode -u vhome-leds -n 30 --no-pager || true
}

# ---- main -----------------------------------------------------------------------------------

usage() {
  echo "usage: install-pi.sh install|update|rollback|uninstall [--purge]|backup [OUT]|restore FILE|status|diag [--keep-wifi-powersave] [--no-leds]"
}

main() {
  local cmd="" arg
  local -a pos=()
  for arg in "$@"; do
    case "$arg" in
      --keep-wifi-powersave) KEEP_WIFI=1 ;;
      --no-leds) NO_LEDS=1 ;;
      --purge) PURGE=1 ;;
      -h|--help) usage; exit 0 ;;
      -*) usage >&2; die "unknown option $arg" ;;
      *) if [ -z "$cmd" ]; then cmd="$arg"; else pos+=("$arg"); fi ;;
    esac
  done
  case "$cmd" in
    install|update) cmd_install ;;
    rollback) cmd_rollback ;;
    uninstall) cmd_uninstall ;;
    backup) cmd_backup "${pos[0]:-}" ;;
    restore) cmd_restore "${pos[0]:-}" ;;
    status) cmd_status ;;
    diag) cmd_diag ;;
    *) usage >&2; exit 2 ;;
  esac
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  main "$@"
fi
