#!/usr/bin/env bash
# Pi, as root: measure what the LEDs add to the SoC temperature.
# usage: heat-test.sh MINUTES_OFF MINUTES_ON [OUT.csv]
# Phase "off" = leds.json enabled=false, phase "on" = enabled=true (brightness unchanged). The LED service rereads
# its config every 10 s. The original leds.json is restored at the end.
set -euo pipefail

OFF_MIN="${1:?usage: heat-test.sh MINUTES_OFF MINUTES_ON [OUT.csv]}"
ON_MIN="${2:?usage: heat-test.sh MINUTES_OFF MINUTES_ON [OUT.csv]}"
OUT="${3:-heat-test-$(date +%Y%m%d-%H%M%S).csv}"
CFG=/var/lib/vhome-vnode/leds.json
[ "$(id -u)" -eq 0 ] || { echo "run as root (sudo)" >&2; exit 1; }
[ -f "$CFG" ] || { echo "missing $CFG (install first)" >&2; exit 1; }

backup="$(mktemp)"
cat "$CFG" > "$backup"
restore() { cat "$backup" > "$CFG"; rm -f "$backup"; echo "restored $CFG" >&2; }
trap restore EXIT
trap 'exit 130' INT TERM

set_enabled() {  # writes into the same inode, so owner and mode stay
  python3 - "$CFG" "$1" <<'PY'
import json, sys
path, val = sys.argv[1], sys.argv[2] == "true"
try:
    cfg = json.load(open(path))
except ValueError:
    cfg = {}
cfg["enabled"] = val
cfg.setdefault("brightness", 2)
with open(path, "w") as f:
    json.dump(cfg, f)
PY
}

temp_c() { awk '{printf "%.1f", $1/1000}' /sys/class/thermal/thermal_zone0/temp; }

throttled() {
  local t d
  if command -v vcgencmd >/dev/null 2>&1 && t="$(vcgencmd get_throttled 2>/dev/null)" && [ -n "$t" ]; then
    echo "${t#throttled=}"; return
  fi
  for d in /sys/class/hwmon/hwmon*; do
    if [ "$(cat "$d/name" 2>/dev/null)" = rpi_volt ]; then
      if [ "$(cat "$d/in0_lcrit_alarm" 2>/dev/null)" = 1 ]; then echo 0x1; else echo 0x0; fi
      return
    fi
  done
  echo NA
}

echo "epoch,phase,temp_c,throttled,leds_enabled,load1" > "$OUT"

run_phase() {  # phase enabled minutes
  local phase="$1" enabled="$2" minutes="$3" end
  set_enabled "$enabled"
  end=$(( $(date +%s) + minutes * 60 ))
  while [ "$(date +%s)" -lt "$end" ]; do
    echo "$(date +%s),$phase,$(temp_c),$(throttled),$enabled,$(cut -d' ' -f1 /proc/loadavg)" >> "$OUT"
    sleep 30
  done
}

run_phase off false "$OFF_MIN"
run_phase on true "$ON_MIN"

awk -F, 'NR > 1 { n[$2]++; s[$2] += $3; if (!($2 in m) || $3 > m[$2]) m[$2] = $3 }
  END {
    for (p in n) printf "%s: mean %.1f C, max %.1f C (%d samples)\n", p, s[p]/n[p], m[p], n[p]
    if (n["off"] && n["on"]) printf "delta (on - off): mean %+.1f C, max %+.1f C\n", s["on"]/n["on"] - s["off"]/n["off"], m["on"] - m["off"]
  }' "$OUT"
echo "CSV: $OUT"
