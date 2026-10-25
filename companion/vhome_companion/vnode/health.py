"""GET /v1/health: turns raw readings into the item list the app renders as-is (docs/contracts/vnode-api-v1.md).

Pure: no I/O. The node decides every level so the phone and the Pi never disagree.
"""
from . import contracts

OK, WARN, ERROR, INFO = "ok", "warn", "error", "info"
_RANK = {OK: 0, INFO: 0, WARN: 1, ERROR: 2}
UNAVAILABLE = "unavailable"

TEMP_WARN_C, TEMP_ERROR_C = 65.0, 75.0
LOAD_WARN, LOAD_ERROR = 1.5, 3.0
MEM_WARN_MB, MEM_ERROR_MB = 60, 30
SWAP_WARN_MB = 50
DISK_WARN_MB, DISK_ERROR_MB = 300, 150
WIFI_WARN_DBM, WIFI_ERROR_DBM = -75, -85
WIFI_ERRORS_WARN = 100

_THROTTLE_NOW = ((0, "under-voltage", ERROR), (1, "ARM frequency capped", WARN),
                 (2, "throttled", ERROR), (3, "soft temperature limit", WARN))
_TV_LINK = {
    "connected": ("Connected", OK, ""),
    "standby": ("TV in standby", OK, ""),
    "unreachable": ("Not reachable", WARN, "The TV does not answer; check that it is on and on the same Wi-Fi."),
    "unknown": ("Unknown", WARN, "The node has not heard from the TV yet; wait a moment or check the TV."),
    "pairing_required": ("Not paired", ERROR, "The node is not paired with the TV; pair it again from the app."),
    "certificate_mismatch": ("Certificate changed", ERROR,
                             "The TV's identity changed; pair it again from the app if you replaced the TV."),
    "permission_denied": ("Permission denied", ERROR,
                          "The TV refused the node; pair it again and accept the prompt on the TV."),
    "launcher_missing": ("V/HOME not found", ERROR, "V/HOME is not installed on the TV; install it from the app."),
}
_WATCHER = {
    "watching": ("Watching", OK, ""),
    "user_paused": ("Paused", WARN, "The watcher is paused; resume it from the app."),
    "disabled": ("Handed to the phone", WARN, "The node is not watching the TV; switch it back on in the app."),
    "safety_paused": ("Safety pause", ERROR, "The watcher stopped itself after repeated failures; check the TV, then resume."),
    "not_ready": ("Not ready", ERROR, "The TV is not paired yet, so nothing is watching; pair the TV first."),
}


def _dur(seconds):
    s = int(seconds)
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    m = s // 60
    if d:
        return "%d d %d h" % (d, h)
    if h:
        return "%d h %d min" % (h, m)
    return "%d min" % m if m else "%d s" % s


def _mb(kb):
    return kb / 1024.0


def _fmt_mb(mb):
    return "%d" % round(mb)


class _Items:
    def __init__(self):
        self.items = []

    def add(self, group, key, label, value, level=INFO, detail=""):
        self.items.append({"group": group, "key": key, "label": label, "value": contracts.redact(value),
                           "level": level, "detail": contracts.redact(detail) if level in (WARN, ERROR) else ""})

    def unavailable(self, group, key, label):
        self.add(group, key, label, UNAVAILABLE, INFO)


def build_health(device_snapshot, status, node_info, phones_count, ntp_ok, now):
    """-> {"level", "problems", "age_s", "items"}. `now` is accepted for call-site symmetry; every age is
    already computed on the node (snapshot["age_s"], status ages), so it is not used."""
    snap = device_snapshot or {}
    tv = (status or {}).get("tv", {})
    watcher = (status or {}).get("watcher", {})
    it = _Items()
    _node(it, snap, node_info or {}, phones_count, ntp_ok)
    _tv(it, tv)
    _watcher(it, watcher)
    _pi(it, snap)
    _network(it, snap)
    level = max((i["level"] for i in it.items), key=_RANK.get, default=OK)
    level = OK if level == INFO else level
    problems = sum(1 for i in it.items if i["level"] in (WARN, ERROR))
    return {"level": level, "problems": problems, "age_s": snap.get("age_s", 0.0), "items": it.items}


def _node(it, snap, info, phones, ntp_ok):
    g = "node"
    version, up = info.get("version"), info.get("uptime_s")
    if version is None and up is None:
        it.unavailable(g, "service", "Service")
    else:
        it.add(g, "service", "Service", "%s · up %s" % (version or "?", _dur(up) if up is not None else "?"), OK)
    r = snap.get("restarts")
    if r is None:
        it.unavailable(g, "restarts", "Restarts")
    elif r > 0:
        it.add(g, "restarts", "Restarts", str(r), WARN,
               "The service restarted %d time%s since boot; if it keeps happening, check the logs." % (r, "" if r == 1 else "s"))
    else:
        it.add(g, "restarts", "Restarts", "0", OK)
    if ntp_ok is None:
        it.unavailable(g, "clock", "Clock")
    elif ntp_ok:
        it.add(g, "clock", "Clock", "Synced", OK)
    else:
        it.add(g, "clock", "Clock", "Not synced", WARN,
               "The clock is not synced with the internet; timed pauses wait until it is. Check the Wi-Fi.")
    leds = snap.get("leds")
    if leds is None:
        it.unavailable(g, "leds_service", "LED service")
    elif not leds.get("supported"):
        it.add(g, "leds_service", "LED service", "Not installed", INFO)
    elif leds.get("age_s") is not None and leds["age_s"] > 60:
        it.add(g, "leds_service", "LED service", "No update for %s" % _dur(leds["age_s"]), WARN,
               "The LED service has stopped updating; restart the node from the app.")
    else:
        it.add(g, "leds_service", "LED service", "Running" if leds.get("age_s") is not None else UNAVAILABLE,
               OK if leds.get("age_s") is not None else INFO)
    if phones is None:
        it.unavailable(g, "phones", "Phones")
    else:
        it.add(g, "phones", "Phones", "%d paired" % phones, INFO)


def _tv(it, tv):
    g = "tv"
    state = tv.get("state")
    if state is None:
        it.unavailable(g, "link", "TV link")
    else:
        value, level, detail = _TV_LINK.get(state, (str(state), WARN, "The TV state is not recognised; update the app."))
        it.add(g, "link", "TV link", value, level, detail)
    it.add(g, "foreground", "In front", tv.get("foreground") or UNAVAILABLE, INFO)
    it.add(g, "power", "TV power", tv.get("power") or "not reported by this TV", INFO)
    if tv.get("last_error"):
        it.add(g, "last_error", "Last TV error", str(tv["last_error"])[:200], INFO)


def _watcher(it, w):
    g = "watcher"
    state = w.get("state")
    if state is None:
        it.unavailable(g, "state", "Watcher")
    else:
        value, level, detail = _WATCHER.get(state, (str(state), WARN, "The watcher state is not recognised; update the app."))
        it.add(g, "state", "Watcher", value, level, detail)
    if w.get("ok") is None and w.get("failed") is None:
        it.unavailable(g, "redirects", "Redirects")
    else:
        ok, failed, lat = w.get("ok") or 0, w.get("failed") or 0, w.get("last_latency_s")
        value = "%d ok, %d failed" % (ok, failed) + (" · last %.1f s" % lat if isinstance(lat, (int, float)) else "")
        if failed > 0:
            it.add(g, "redirects", "Redirects", value, WARN,
                   "Some attempts to open V/HOME on the TV failed; check the TV link and the last failure.")
        else:
            it.add(g, "redirects", "Redirects", value, OK)
    if w.get("last_failure"):
        it.add(g, "last_failure", "Last failure", str(w["last_failure"])[:200], INFO)


def _pi(it, s):
    g = "pi"
    t = s.get("temp_c")
    if t is None:
        it.unavailable(g, "temp", "Temperature")
    elif t >= TEMP_ERROR_C:
        it.add(g, "temp", "Temperature", "%.1f °C" % t, ERROR, "The Pi is overheating; give it airflow or move it away from the TV's heat.")
    elif t >= TEMP_WARN_C:
        it.add(g, "temp", "Temperature", "%.1f °C" % t, WARN, "The Pi is getting hot; give it airflow.")
    else:
        it.add(g, "temp", "Temperature", "%.1f °C" % t, OK)

    th = s.get("throttled")
    if th is None:
        it.unavailable(g, "throttle_now", "Throttling now")
        it.unavailable(g, "throttle_boot", "Throttling since boot")
    else:
        now_bits = [(name, lvl) for bit, name, lvl in _THROTTLE_NOW if th & (1 << bit)]
        if not now_bits:
            it.add(g, "throttle_now", "Throttling now", "None", OK)
        else:
            level = ERROR if any(l == ERROR for _, l in now_bits) else WARN
            names = [n for n, _ in now_bits]
            if "under-voltage" in names:
                detail = "The power supply is too weak; use a 5 V 2.5 A supply."
            elif "throttled" in names:
                detail = "The Pi is slowing itself down; check the power supply and cooling."
            else:
                detail = "The Pi is limiting its speed; check the power supply and cooling."
            it.add(g, "throttle_now", "Throttling now", ", ".join(names).capitalize(), level, detail)
        since = [name for bit, name, _ in _THROTTLE_NOW if th & (1 << (16 + bit))]
        if since:
            it.add(g, "throttle_boot", "Throttling since boot", ", ".join(since).capitalize(), WARN,
                   "The Pi was throttled earlier since boot; check the power supply and cooling.")
        else:
            it.add(g, "throttle_boot", "Throttling since boot", "None", OK)

    v = s.get("volts")
    if v is None:
        it.unavailable(g, "voltage", "Core voltage")
    elif th is not None and th & 1:
        it.add(g, "voltage", "Core voltage", "%.2f V" % v, ERROR, "The power supply is too weak; use a 5 V 2.5 A supply.")
    else:
        it.add(g, "voltage", "Core voltage", "%.2f V" % v, INFO)

    ld = s.get("load")
    if ld is None:
        it.unavailable(g, "cpu_load", "CPU load")
    else:
        value = " / ".join("%.2f" % x for x in ld)
        if ld[0] > LOAD_ERROR:
            it.add(g, "cpu_load", "CPU load", value, ERROR, "The Pi is overloaded; restart the service from the app.")
        elif ld[0] > LOAD_WARN:
            it.add(g, "cpu_load", "CPU load", value, WARN, "The Pi is busy; if it stays like this, restart the service.")
        else:
            it.add(g, "cpu_load", "CPU load", value, OK)

    cu = s.get("cpu_use")
    if cu == "measuring":
        it.add(g, "cpu_use", "CPU use", "measuring…", INFO)
    elif cu is None:
        it.unavailable(g, "cpu_use", "CPU use")
    else:
        it.add(g, "cpu_use", "CPU use", "%.0f %%" % cu, INFO)

    mhz, top = s.get("cpu_mhz"), s.get("cpu_max_mhz")
    if mhz is None:
        it.unavailable(g, "cpu_freq", "CPU speed")
    else:
        value = "%d / %d MHz" % (mhz, top) if top else "%d MHz" % mhz
        if s.get("governor"):
            value += " · " + s["governor"]
        it.add(g, "cpu_freq", "CPU speed", value, INFO)

    total, avail = s.get("mem_total_kb"), s.get("mem_avail_kb")
    if total is None or avail is None:
        it.unavailable(g, "memory", "Memory")
    else:
        value = "%s / %s MB" % (_fmt_mb(_mb(total - avail)), _fmt_mb(_mb(total)))
        if _mb(avail) < MEM_ERROR_MB:
            it.add(g, "memory", "Memory", value, ERROR, "The Pi is almost out of memory; restart the service from the app.")
        elif _mb(avail) < MEM_WARN_MB:
            it.add(g, "memory", "Memory", value, WARN, "Memory is running low; restart the service if the app gets slow.")
        else:
            it.add(g, "memory", "Memory", value, OK)

    st, sf = s.get("swap_total_kb"), s.get("swap_free_kb")
    if st is None or sf is None:
        it.unavailable(g, "swap", "Swap")
    else:
        used = _mb(st - sf)
        value = "%s / %s MB" % (_fmt_mb(used), _fmt_mb(_mb(st)))
        if used > SWAP_WARN_MB:
            it.add(g, "swap", "Swap", value, WARN, "The Pi is using the SD card as memory, which is slow and wears it; restart the service.")
        else:
            it.add(g, "swap", "Swap", value, OK)

    free, dtotal = s.get("disk_free_mb"), s.get("disk_total_mb")
    if free is None or dtotal is None:
        it.unavailable(g, "disk", "Storage")
    else:
        value = "%d MB free of %d MB" % (free, dtotal)
        if free < DISK_ERROR_MB:
            it.add(g, "disk", "Storage", value, ERROR, "The SD card is almost full; free space or reinstall the node.")
        elif free < DISK_WARN_MB:
            it.add(g, "disk", "Storage", value, WARN, "The SD card is getting full; free some space.")
        else:
            it.add(g, "disk", "Storage", value, OK)

    up = s.get("uptime_s")
    if up is None:
        it.unavailable(g, "uptime", "Uptime")
    else:
        it.add(g, "uptime", "Uptime", _dur(up), INFO)


def _network(it, s):
    g = "network"
    w = s.get("wifi") or {}
    state = w.get("state")
    if state is None:
        it.unavailable(g, "wifi_link", "Wi-Fi link")
    else:
        value = "%s · %s" % (state, w.get("ip") or "no IPv4 address")
        if state == "up":
            it.add(g, "wifi_link", "Wi-Fi link", value, OK)
        else:
            it.add(g, "wifi_link", "Wi-Fi link", value, ERROR, "The Wi-Fi is down; check the router and the node's Wi-Fi settings.")
    dbm = w.get("dbm")
    if dbm is None:
        it.unavailable(g, "wifi_signal", "Wi-Fi signal")
    else:
        value = "%d dBm · %s/4 bars" % (dbm, w.get("bars") if w.get("bars") is not None else "?")
        if dbm < WIFI_ERROR_DBM:
            it.add(g, "wifi_signal", "Wi-Fi signal", value, ERROR, "The Wi-Fi signal is very weak; move the node or the router closer.")
        elif dbm < WIFI_WARN_DBM:
            it.add(g, "wifi_signal", "Wi-Fi signal", value, WARN, "The Wi-Fi signal is weak; move the node or the router closer.")
        else:
            it.add(g, "wifi_signal", "Wi-Fi signal", value, OK)
    errs = w.get("errors")
    if errs is None:
        it.unavailable(g, "wifi_errors", "Wi-Fi errors")
    elif errs > WIFI_ERRORS_WARN:
        it.add(g, "wifi_errors", "Wi-Fi errors", str(errs), WARN, "The Wi-Fi link is losing packets; check the signal and interference.")
    else:
        it.add(g, "wifi_errors", "Wi-Fi errors", str(errs), OK)
    bt = s.get("bluetooth")
    if bt is None:
        it.unavailable(g, "bluetooth", "Bluetooth")
    elif not bt.get("present"):
        it.add(g, "bluetooth", "Bluetooth", "Not present", INFO)
    elif bt.get("blocked"):
        it.add(g, "bluetooth", "Bluetooth", "Off (not used)", INFO)
    else:
        it.add(g, "bluetooth", "Bluetooth", "On (not used)", INFO)
