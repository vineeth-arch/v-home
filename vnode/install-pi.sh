#!/usr/bin/env bash
# V/HOME node installer. Runs on the Raspberry Pi as root, from inside the extracted bundle:
#   sudo bash vnode/install-pi.sh <command> [options] [args]
# Commands: install | update | rollback | uninstall [--purge] | backup [OUT] | restore FILE | status | diag
# Options:  --keep-wifi-powersave (leave Wi-Fi power save alone)   --no-leds (skip the LED service)
#           --with-integrations (opt-in: also install vhome-integrations; a failure there never touches the TV release)
#           --with-worker (opt-in, implies --with-integrations: delivery worker on the Pi, posts to Brain with the Mac off)
#           --worker-env-file FILE (with --with-worker: BRAIN_URL, BRAIN_VNODE_TOKEN, optional BRAIN_ALLOW_HOST,
#                                   CF_ACCESS_CLIENT_ID/SECRET, VNODE_WORKER_TOKEN; consumed and deleted on every exit path)
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
INT_UNIT=vhome-integrations
INT_USER=vhome-int
INT_GROUP=vhome-intsock
INT_STATE=/var/lib/vhome-integrations
INT_SOCKET=/run/vhome-integrations/int.sock
INT_WRAPPER=/usr/local/bin/vnode-int
DELIVER_UNIT=vhome-int-deliver
DELIVER_USER=vhome-deliver
DELIVER_DIR=/etc/vhome-int
DELIVER_ENV=$DELIVER_DIR/deliver.env
DELIVER_STATE=/var/lib/vhome-int-deliver

KEEP_WIFI=0
NO_LEDS=0
PURGE=0
WITH_INT=0
INT_OK=0
WITH_WORKER=0
WORKER_ENV_SRC=""

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
  # ssap.py needs websockets >= 13 (asyncio client); Debian 12 ships 10.4 and would fail only at TV connect time.
  python3 -c "from websockets.asyncio.client import connect" 2>/dev/null \
    || die "python3-websockets is too old (need >= 13; Raspberry Pi OS 13 trixie ships 15)"
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

# ---- integrations (opt-in, only reached with --with-integrations) -----------------------------

# int_preflight: print python, aiohttp, sqlite3 versions; fail (return 1) when integrations cannot run here.
int_preflight() {
  log "Integrations preflight"
  python3 -c "import sys, sqlite3, aiohttp; print('python', sys.version.split()[0], 'aiohttp', aiohttp.__version__, 'sqlite3', sqlite3.sqlite_version)" \
    || return 1
  python3 -c 'import sqlite3, sys; sys.exit(0 if sqlite3.sqlite_version_info >= (3, 24) else 1)' \
    || { warn "sqlite3 >= 3.24 needed for integrations"; return 1; }
}

ensure_int_users() {
  log "Integrations user"
  # Runs inside an `if` condition (int_prepare), where set -e is off: every command needs its own || return 1.
  getent group "$INT_GROUP" >/dev/null || groupadd --system "$INT_GROUP" || return 1
  if ! id "$INT_USER" >/dev/null 2>&1; then
    useradd --system --gid "$INT_GROUP" --home-dir "$INT_STATE" --no-create-home --shell /usr/sbin/nologin "$INT_USER" \
      || return 1
  fi
  # vhome joins the socket group so the TV process can reach int.sock. vhome-int is NOT added to group vhome.
  # Done before the TV restart in cmd_install: a process only sees new supplementary groups after it restarts.
  usermod -aG "$INT_GROUP" "$SVC_USER" || return 1
}

# int_prepare: never fails; sets INT_OK=1 only when integrations may be installed. TV install proceeds either way.
int_prepare() {
  if int_preflight && ensure_int_users; then
    INT_OK=1
  else
    warn "integrations skipped; the TV install continues without them"
  fi
}

install_int_files() {
  put "$BUNDLE/vnode/systemd/vhome-integrations.service" "$UNIT_DIR/$INT_UNIT.service" 0644
  put "$BUNDLE/vnode/bin/vnode-int" "$INT_WRAPPER" 0755
  if [ "$WITH_WORKER" = 1 ]; then put "$BUNDLE/vnode/systemd/$DELIVER_UNIT.service" "$UNIT_DIR/$DELIVER_UNIT.service" 0644; fi
}

# start_integrations: after the TV is healthy. On failure: disable integrations, warn, leave the TV alone.
start_integrations() {
  log "Integrations start"
  local i
  systemctl enable "$INT_UNIT" >/dev/null 2>&1 || true
  systemctl restart "$INT_UNIT" || true
  for i in $(seq 1 90); do   # Pi Zero W: first start took ~23 s (python imports)
    if systemctl is-active --quiet "$INT_UNIT" && [ -S "$INT_SOCKET" ]; then
      echo "integrations up after ${i}s"
      # the delivery worker runs from the same `current` release: move it onto the new one too (best effort)
      if systemctl is-enabled --quiet "$DELIVER_UNIT" 2>/dev/null; then
        systemctl restart "$DELIVER_UNIT" || warn "$DELIVER_UNIT did not restart: journalctl -u $DELIVER_UNIT"
      fi
      return 0
    fi
    sleep 1
  done
  journalctl -u "$INT_UNIT" -n 50 --no-pager || true
  systemctl disable --now "$INT_UNIT" >/dev/null 2>&1 || true
  warn "integrations failed to start and were disabled; the TV release is untouched. Retry: install --with-integrations"
  return 1
}

# ---- delivery worker on the Pi (opt-in, only reached with --with-worker) ---------------------------

# env_get FILE KEY: value of KEY=... (first match). Drops a trailing CR and ONE balanced pair of quotes, nothing else.
env_get() {
  local v
  [ -f "$1" ] || return 0
  v="$(sed -n "s/^$2=//p" "$1" | head -n 1 | tr -d '\r')"
  case "$v" in
    \"?*\") v="${v#\"}"; v="${v%\"}" ;;
    \'?*\') v="${v#\'}"; v="${v%\'}" ;;
  esac
  printf '%s' "$v"
}

# env_value_ok VALUE: printable ASCII without spaces, quotes, backslash or backtick (safe in a systemd EnvironmentFile).
env_value_ok() { local re='^[A-Za-z0-9._~:/?#@!$%&()*+,;=-]+$'; [[ "$1" =~ $re ]]; }

# brain_url_ok URL: https only, plain host, optional port and path, no userinfo.
brain_url_ok() { local re='^https://[A-Za-z0-9.-]+(:[0-9]+)?(/[^[:space:]]*)?$'; [[ "$1" =~ $re ]]; }

# parse_minted_token: stdin is `vnode-int worker-token create` output; prints only the token.
parse_minted_token() { sed -n 's/^token (shown once, store it now): //p' | head -n 1; }

# redact_output: stdin to stdout with anything after "store it now): " or "token" / "secret" labels blanked.
redact_output() {
  sed -E -e 's/(store it now\): ).*/\1<redacted>/' -e 's/([Tt]oken|[Ss]ecret|[Aa]uthorization)([^:=]*[:=] *).*/\1\2<redacted>/'
}

# mint_worker_token: prints the new token; on failure prints a redacted reason on stderr and returns 1.
mint_worker_token() {
  local out tok
  out="$("$INT_WRAPPER" worker-token create 2>&1)" || { printf '%s\n' "$out" | redact_output >&2; return 1; }
  tok="$(printf '%s\n' "$out" | parse_minted_token)"
  [ -n "$tok" ] || { printf '%s\n' "$out" | redact_output >&2; return 1; }
  printf '%s' "$tok"
}

# check_worker_token TOKEN: one read-only call on int.sock; 0 only if the service accepts the token. The token goes in the
# environment of that one process, not in argv.
check_worker_token() {
  VH_TOK="$1" VH_SOCK="$INT_SOCKET" python3 -c '
import http.client, os, socket, sys
class C(http.client.HTTPConnection):
    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX); self.sock.settimeout(10); self.sock.connect(os.environ["VH_SOCK"])
c = C("localhost")
c.request("GET", "/v1/int/worker/unknown", headers={"Authorization": "Bearer " + os.environ["VH_TOK"]})
sys.exit(0 if c.getresponse().status == 200 else 1)' 2>/dev/null
}

# write_deliver_env: build $DELIVER_ENV (0600 root:root; systemd reads it as root) from WORKER_ENV_SRC.
# Tokens are never echoed. Without a source file an existing deliver.env is kept (a plain update needs no secrets).
write_deliver_env() {
  local url token wtoken host tmp cfid cfsec allow k v
  if [ -z "$WORKER_ENV_SRC" ]; then
    if [ -f "$DELIVER_ENV" ]; then echo "keeping existing $DELIVER_ENV"; return 0; fi
    warn "no $DELIVER_ENV and no --worker-env-file: pass BRAIN_VNODE_TOKEN to deploy.sh --with-worker"
    return 1
  fi
  [ -f "$WORKER_ENV_SRC" ] || { warn "worker env file $WORKER_ENV_SRC not found"; return 1; }
  url="$(env_get "$WORKER_ENV_SRC" BRAIN_URL)"
  token="$(env_get "$WORKER_ENV_SRC" BRAIN_VNODE_TOKEN)"
  if [ -z "$url" ] || [ -z "$token" ]; then warn "worker env file needs BRAIN_URL and BRAIN_VNODE_TOKEN"; return 1; fi
  brain_url_ok "$url" || { warn "BRAIN_URL must look like https://host[:port][/path] (no user:password@)"; return 1; }
  allow="$(env_get "$WORKER_ENV_SRC" BRAIN_ALLOW_HOST)"
  if [ -z "$allow" ]; then   # https://host[:port]/... -> host
    host="${url#*://}"; host="${host%%/*}"; allow="${host%%:*}"
  fi
  cfid="$(env_get "$WORKER_ENV_SRC" CF_ACCESS_CLIENT_ID)"
  cfsec="$(env_get "$WORKER_ENV_SRC" CF_ACCESS_CLIENT_SECRET)"
  wtoken="$(env_get "$WORKER_ENV_SRC" VNODE_WORKER_TOKEN)"
  for v in "$url" "$token" "$allow" "$cfid" "$cfsec" "$wtoken"; do
    if [ -n "$v" ] && ! env_value_ok "$v"; then
      warn "a worker setting has characters that are not allowed (spaces, quotes, backslash or control characters)"
      return 1
    fi
  done
  if [ -n "$wtoken" ]; then
    check_worker_token "$wtoken" || { warn "the supplied VNODE_WORKER_TOKEN is not accepted by $INT_UNIT"; return 1; }
  else
    wtoken="$(env_get "$DELIVER_ENV" VNODE_WORKER_TOKEN)"   # re-run keeps the same worker token ...
    if [ -n "$wtoken" ] && ! check_worker_token "$wtoken"; then wtoken=""; fi   # ... unless it was revoked meanwhile
  fi
  if [ -z "$wtoken" ]; then
    k="$(mktemp)"
    wtoken="$(mint_worker_token 2>"$k")" || wtoken=""
    if [ -z "$wtoken" ]; then warn "could not mint a worker token: $(tr '\n' ' ' < "$k")"; rm -f "$k"; return 1; fi
    rm -f "$k"
  fi
  tmp="$(umask 077; mktemp)"
  {
    printf 'BRAIN_URL=%s\nBRAIN_ALLOW_HOST=%s\nBRAIN_VNODE_TOKEN=%s\n' "$url" "$allow" "$token"
    if [ -n "$cfid" ] && [ -n "$cfsec" ]; then printf 'CF_ACCESS_CLIENT_ID=%s\nCF_ACCESS_CLIENT_SECRET=%s\n' "$cfid" "$cfsec"; fi
    printf 'VNODE_SOCKET=%s\nVNODE_WORKER_TOKEN=%s\n' "$INT_SOCKET" "$wtoken"
    printf 'WORKER_NAME=pi-deliver\nWORKER_POLL_S=60\nWORKER_MAX_PER_RUN=5\nWAIT_CLOCK_SYNC=1\n'
  } > "$tmp"
  install -d -o root -g root -m 0700 "$DELIVER_DIR"
  install -o root -g root -m 0600 "$tmp" "$DELIVER_ENV"
  rm -f "$tmp" "$WORKER_ENV_SRC"
  echo "wrote $DELIVER_ENV (0600 root:root)"
}

# ensure_deliver_user: own system user, group vhome-intsock only (enough to open int.sock, nothing else).
ensure_deliver_user() {
  getent group "$INT_GROUP" >/dev/null || return 1
  if ! id "$DELIVER_USER" >/dev/null 2>&1; then
    useradd --system --gid "$INT_GROUP" --home-dir "$DELIVER_STATE" --no-create-home --shell /usr/sbin/nologin "$DELIVER_USER" \
      || return 1
  fi
}

# setup_worker: after integrations are up. Never touches the TV or integrations; failure returns 1.
setup_worker() {
  log "Delivery worker"
  local i since
  ensure_deliver_user || { warn "could not create user $DELIVER_USER"; return 1; }
  write_deliver_env || return 1
  systemctl enable "$DELIVER_UNIT" >/dev/null 2>&1 || true
  since="$(date '+%Y-%m-%d %H:%M:%S')"
  systemctl restart "$DELIVER_UNIT" || true
  for i in $(seq 1 45); do   # a bad config exits 78 within seconds; python imports take ~10-25 s on a Zero W
    if ! systemctl is-active --quiet "$DELIVER_UNIT"; then
      journalctl -u "$DELIVER_UNIT" -n 30 --no-pager || true
      systemctl disable --now "$DELIVER_UNIT" >/dev/null 2>&1 || true
      warn "delivery worker stopped right after start and was disabled. Fix the cause, then re-run with --with-worker"
      return 1
    fi
    if journalctl -u "$DELIVER_UNIT" --since "$since" --no-pager 2>/dev/null | grep -q "started mode="; then
      echo "delivery worker running after ${i}s"
      return 0
    fi
    sleep 1
  done
  journalctl -u "$DELIVER_UNIT" -n 30 --no-pager || true
  systemctl disable --now "$DELIVER_UNIT" >/dev/null 2>&1 || true
  warn "delivery worker did not report 'started' within 45 s and was disabled"
  return 1
}

# int_enabled: true when the integrations unit is enabled (it runs from the same current symlink as the TV).
int_enabled() { systemctl is-enabled --quiet "$INT_UNIT" 2>/dev/null; }

# int_failed_exit: TV is fine but integrations are not; distinct final line and exit code 3.
int_failed_exit() {
  echo "TV OK, integrations NOT running (see journalctl -u $INT_UNIT)"
  exit 3
}

uninstall_integrations() {
  systemctl disable --now "$DELIVER_UNIT" 2>/dev/null || true
  systemctl disable --now "$INT_UNIT" 2>/dev/null || true
  rm -f "$UNIT_DIR/$DELIVER_UNIT.service" "$UNIT_DIR/$INT_UNIT.service" "$INT_WRAPPER"
  if [ "$PURGE" = 1 ]; then
    rm -rf "${INT_STATE:?}" "${DELIVER_STATE:?}" "${DELIVER_DIR:?}"
    if id "$DELIVER_USER" >/dev/null 2>&1; then userdel "$DELIVER_USER" || true; fi
    if id "$INT_USER" >/dev/null 2>&1; then userdel "$INT_USER" || true; fi
    if getent group "$INT_GROUP" >/dev/null; then groupdel "$INT_GROUP" || true; fi
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
  prev="$(readlink -f "$OPT/current" 2>/dev/null || true)"
  # Same version again (e.g. a re-run): never delete the directory the running service uses.
  if [ "$prev" = "$dest" ]; then dest="$dest-r$(date +%s)"; fi
  tmp="$dest.new"
  rm -rf "${tmp:?}"
  mkdir "$tmp"
  cp -R "$BUNDLE/vhome_companion" "$BUNDLE/tests" "$BUNDLE/vnode" "$BUNDLE/VERSION" "$tmp/"  # vnode/: install-pi.sh and heat-test.sh stay on the Pi
  find "$tmp" -name __pycache__ -prune -exec rm -rf {} +
  chown -R root:root "$tmp"
  find "$tmp" -type d -exec chmod 0755 {} +
  find "$tmp" -type f -exec chmod 0644 {} +
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
  if [ "$INT_OK" = 1 ]; then install_int_files; fi
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
  if [ "$WITH_INT" = 1 ]; then int_prepare; fi
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
  local int_failed=0 worker_failed=0
  if [ "$WITH_INT" = 1 ] && [ "$INT_OK" = 1 ]; then
    start_integrations || int_failed=1
  elif [ "$WITH_INT" = 1 ]; then
    int_failed=1   # asked for integrations, preflight/users refused them: TV is fine, say so loudly
  elif int_enabled; then
    start_integrations || int_failed=1   # plain update: integrations share `current`, so restart onto the new release
  fi
  if [ "$WITH_WORKER" = 1 ] && [ "$WITH_INT" = 1 ] && [ "$int_failed" = 0 ]; then
    setup_worker || worker_failed=1
  fi
  echo "node id: $(node_id16)...  version: $(basename "$(readlink -f "$OPT/current")")"
  if [ "$int_failed" = 1 ]; then int_failed_exit; fi
  if [ "$worker_failed" = 1 ]; then
    echo "TV OK, integrations OK, delivery worker NOT running (see journalctl -u $DELIVER_UNIT)"
    exit 3
  fi
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
  if int_enabled; then start_integrations || int_failed_exit; fi
}

cmd_uninstall() {
  [ "$(id -u)" -eq 0 ] || die "run as root"
  log "Uninstall"
  local u
  for u in vhome-vnode vhome-leds; do
    systemctl disable --now "$u" 2>/dev/null || true
    rm -f "$UNIT_DIR/$u.service"
  done
  uninstall_integrations
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
  if [ "$PURGE" != 1 ] && [ -d "$INT_STATE" ]; then echo "kept $INT_STATE and user $INT_USER (queued items); --purge removes them"; fi
  if [ "$PURGE" != 1 ] && [ -f "$DELIVER_ENV" ]; then echo "kept $DELIVER_ENV (Brain token); --purge removes it"; fi
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
  if [ -d "$STATE" ]; then
    cmd_backup
    rm -rf "${STATE:?}"   # replace, don't merge: a stale tv-revoked or phones.json must not survive
  fi
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
  echo "usage: install-pi.sh install|update|rollback|uninstall [--purge]|backup [OUT]|restore FILE|status|diag [--keep-wifi-powersave] [--no-leds] [--with-integrations] [--with-worker [--worker-env-file FILE]]"
}

main() {
  local cmd="" arg
  local -a pos=()
  while [ $# -gt 0 ]; do
    arg="$1"; shift
    case "$arg" in
      --with-worker) WITH_WORKER=1; WITH_INT=1 ;;
      --worker-env-file) WORKER_ENV_SRC="${1:?--worker-env-file needs a path}"; shift ;;
      --keep-wifi-powersave) KEEP_WIFI=1 ;;
      --no-leds) NO_LEDS=1 ;;
      --with-integrations) WITH_INT=1 ;;
      --purge) PURGE=1 ;;
      -h|--help) usage; exit 0 ;;
      -*) usage >&2; die "unknown option $arg" ;;
      *) if [ -z "$cmd" ]; then cmd="$arg"; else pos+=("$arg"); fi ;;
    esac
  done
  # the secrets file is removed whatever happens (error, die, ctrl-C), not only when write_deliver_env gets to run
  if [ -n "$WORKER_ENV_SRC" ]; then trap 'rm -f "$WORKER_ENV_SRC"' EXIT; fi
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
