"""Raspberry Pi health readers, LED config and the fixed power actions."""
import asyncio
import glob
import json
import logging
import os
import shutil
import time
from pathlib import Path

from .. import cli
from . import contracts

log = logging.getLogger("vhome.device")

# The only commands this node ever runs. argv never comes from a request.
POWER_ACTIONS = {
    "restart-service": ["systemctl", "restart", "vhome-vnode.service"],
    "reboot": ["systemctl", "reboot"],
    "shutdown": ["systemctl", "poweroff"],
}
THERMAL = "/sys/class/thermal/thermal_zone0/temp"
HWMON_NAMES = "/sys/class/hwmon/hwmon*/name"  # the rpi_volt one exposes under-voltage (no vcgencmd: /dev/vchiq is blocked)
LED_STALE_S = 60.0
PROBE_TIMEOUT_S = 3.0
PROBE_CACHE_S = 10.0   # vcgencmd / systemctl / ip readings are reused for this long (monotonic)
PROBES = {
    "throttled": ["/usr/bin/vcgencmd", "get_throttled"],
    "volts": ["/usr/bin/vcgencmd", "measure_volts", "core"],
    "restarts": ["systemctl", "show", "vhome-vnode", "-p", "NRestarts", "--value"],
    "leds_unit": ["systemctl", "show", "vhome-leds", "-p", "ActiveState", "--value"],
}


class RateLimited(Exception):
    pass


def _read_file(path):
    with open(path) as f:
        return f.read()


async def _run(argv):
    """-> (returncode, stderr text). No shell; 10 s limit."""
    proc = await asyncio.create_subprocess_exec(
        *argv, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
    try:
        _, err = await asyncio.wait_for(proc.communicate(), 10)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return -1, "timed out after 10 s"
    return proc.returncode, err.decode(errors="replace")


async def _run_out(argv):
    """-> (returncode, stdout text). No shell; 3 s limit; used only for read-only health probes."""
    proc = await asyncio.create_subprocess_exec(
        *argv, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), PROBE_TIMEOUT_S)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return -1, "timed out"
    return proc.returncode, out.decode(errors="replace")


def _num(text, cast=int):
    try:
        return cast(str(text).strip())
    except (TypeError, ValueError):
        return None


def _bars(dbm):
    if dbm is None:
        return None
    for floor, bars in ((-55, 4), (-65, 3), (-75, 2), (-85, 1)):
        if dbm >= floor:
            return bars
    return 0


class Device:
    def __init__(self, state_dir, *, run=_run, clock=time.monotonic, read=_read_file, wall=time.time,
                 mtime=os.path.getmtime, glob=glob.glob, restart_delay=1.0, run_out=_run_out,
                 disk=shutil.disk_usage):
        self.state_dir = Path(state_dir)
        self._run, self._clock, self._read, self._wall, self._mtime = run, clock, read, wall, mtime
        self._run_out, self._disk = run_out, disk
        self._probe_warned = set()
        self._probe_cache = {}      # name -> (monotonic time, stdout text or None)
        self._probe_lock = asyncio.Lock()
        self._cpu_prev = None       # (busy, total) jiffies from the previous health call
        self._glob = glob
        self._delay = restart_delay
        self._last_power = None
        self._tasks = set()

    def _try(self, path):
        try:
            return self._read(path)
        except (OSError, ValueError):
            return None

    def has_leds(self):
        return self._try(contracts.LED_STATE_FILE) is not None

    def status(self):
        out = {"temp_c": None, "throttled": None, "mem_used_mb": None, "mem_total_mb": None,
               "disk_free_mb": None, "uptime_s": None, "wifi": {"dbm": None, "bars": None},
               "leds": self._leds(), "age_s": 0.0}
        t = self._try(THERMAL)
        try:
            out["temp_c"] = round(int(t) / 1000, 1)
        except (TypeError, ValueError):
            pass
        out["throttled"] = self._throttled()
        mem = {}
        for line in (self._try("/proc/meminfo") or "").splitlines():
            k, _, v = line.partition(":")
            if v.split():
                try:
                    mem[k] = int(v.split()[0])  # kB
                except ValueError:
                    pass
        if "MemTotal" in mem and "MemAvailable" in mem:
            out["mem_total_mb"] = mem["MemTotal"] // 1024
            out["mem_used_mb"] = (mem["MemTotal"] - mem["MemAvailable"]) // 1024
        try:
            out["disk_free_mb"] = shutil.disk_usage(self.state_dir).free // (1024 * 1024)
        except OSError:
            pass
        try:
            out["uptime_s"] = int(float((self._try("/proc/uptime") or "").split()[0]))
        except (IndexError, ValueError):
            pass
        out["wifi"] = self._wifi()
        return out

    async def _probe(self, name):
        now = self._clock()
        hit = self._probe_cache.get(name)
        if hit is None or now - hit[0] >= PROBE_CACHE_S:
            try:
                rc, out = await self._run_out(list(PROBES[name]))
            except Exception as e:  # noqa: BLE001 - a missing binary is just "unavailable"
                rc, out = -1, f"{type(e).__name__}: {e}"
            if rc != 0 and name not in self._probe_warned:   # once per probe, so the reason is visible
                self._probe_warned.add(name)
                log.warning("health probe %s failed (rc %s): %s", name, rc, contracts.redact(out.strip())[:200])
            hit = self._probe_cache[name] = (now, out if rc == 0 else None)
        return hit

    def _cpu_use(self):
        """Busy % since the previous call. "measuring" on the first call, None when unreadable."""
        parts = (self._try("/proc/stat") or "").split("\n", 1)[0].split()
        try:
            vals = [int(v) for v in parts[1:9]]
        except ValueError:
            return None
        if parts[:1] != ["cpu"] or len(vals) < 4:
            return None
        total = sum(vals)
        busy = total - vals[3] - vals[4] if len(vals) > 4 else total - vals[3]  # minus idle and iowait
        prev, self._cpu_prev = self._cpu_prev, (busy, total)
        if prev is None:
            return "measuring"
        if total <= prev[1]:
            return None
        return round(max(0.0, min(100.0, 100.0 * (busy - prev[0]) / (total - prev[1]))), 1)

    def _meminfo_kb(self):
        mem = {}
        for line in (self._try("/proc/meminfo") or "").splitlines():
            k, _, v = line.partition(":")
            if v.split():
                n = _num(v.split()[0])
                if n is not None:
                    mem[k] = n
        return mem

    def _net_errors(self):
        total = 0
        for name in ("rx_errors", "tx_errors", "rx_dropped", "tx_dropped"):
            n = _num(self._try("/sys/class/net/wlan0/statistics/" + name))
            if n is None:
                return None
            total += n
        return total

    def _bluetooth(self):
        present = bool(self._glob("/sys/class/bluetooth/hci*"))
        blocked = None
        for tpath in sorted(self._glob("/sys/class/rfkill/rfkill*/type")):
            if (self._try(tpath) or "").strip() == "bluetooth":
                base = tpath[:-len("type")]
                present = True
                flags = [(self._try(base + k) or "").strip() for k in ("soft", "hard")]
                blocked = "1" in flags
                break
        return {"present": present, "blocked": blocked}

    def _led_service(self, unit_state):
        raw = self._try(contracts.LED_STATE_FILE)
        age = None
        if raw is not None:
            try:
                age = round(max(self._wall() - self._mtime(contracts.LED_STATE_FILE), 0.0), 1)
            except OSError:
                pass
        return {"supported": raw is not None, "age_s": age, "unit": unit_state}

    async def health_snapshot(self):
        """Raw readings for health.build_health. Never raises; an unreadable value is None."""
        async with self._probe_lock:
            names = list(PROBES)
            got = dict(zip(names, await asyncio.gather(*(self._probe(n) for n in names))))
            text = {n: got[n][1] for n in names}
            now = self._clock()
            age = round(max(now - got[n][0] for n in names), 1)
            throttled = None
            if text["throttled"] is not None:
                throttled = _num(text["throttled"].strip().partition("=")[2], lambda v: int(v, 16))
            throttled_source = "vcgencmd" if throttled is not None else None
            if throttled is None:  # vcgencmd unavailable: the rpi_volt hwmon only knows under-voltage now
                hw = self._throttled()
                throttled = int(hw, 16) if hw else None
                throttled_source = "hwmon" if hw else None
            volts = None
            if text["volts"] is not None:
                volts = _num(text["volts"].strip().partition("=")[2].rstrip("V"), float)
            ip = self._ipv4("wlan0")
            load = None
            try:
                load = tuple(float(v) for v in (self._try("/proc/loadavg") or "").split()[:3])
                if len(load) != 3:
                    load = None
            except ValueError:
                pass
            cur = _num(self._try("/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq"))
            top = _num(self._try("/sys/devices/system/cpu/cpu0/cpufreq/scaling_max_freq"))
            mem = self._meminfo_kb()
            try:
                du = self._disk("/")
                disk = (du.free // (1024 * 1024), du.total // (1024 * 1024))
            except OSError:
                disk = (None, None)
            try:
                uptime = int(float((self._try("/proc/uptime") or "").split()[0]))
            except (IndexError, ValueError):
                uptime = None
            temp = _num(self._try(THERMAL))
            wifi = self._wifi()
            state = (self._try("/sys/class/net/wlan0/operstate") or "").strip() or None
            return {
                "age_s": age,
                "temp_c": None if temp is None else round(temp / 1000, 1),
                "throttled": throttled, "throttled_source": throttled_source, "volts": volts, "load": load,
                "cpu_use": self._cpu_use(),
                "cpu_mhz": None if cur is None else cur // 1000,
                "cpu_max_mhz": None if top is None else top // 1000,
                "governor": (self._try("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor") or "").strip() or None,
                "mem_total_kb": mem.get("MemTotal"), "mem_avail_kb": mem.get("MemAvailable"),
                "swap_total_kb": mem.get("SwapTotal"), "swap_free_kb": mem.get("SwapFree"),
                "disk_free_mb": disk[0], "disk_total_mb": disk[1], "uptime_s": uptime,
                "wifi": {"state": state, "ip": ip, "dbm": wifi["dbm"], "bars": wifi["bars"],
                         "errors": self._net_errors()},
                "bluetooth": self._bluetooth(),
                "restarts": _num(text["restarts"]),
                "leds": self._led_service((text["leds_unit"] or "").strip() or None),
            }

    def _ipv4(self, ifname):
        """IPv4 of an interface via SIOCGIFADDR; None when it has none or the call fails."""
        import fcntl, socket, struct
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sk:
                raw = fcntl.ioctl(sk.fileno(), 0x8915, struct.pack("256s", ifname.encode()[:15]))
            return socket.inet_ntoa(raw[20:24])
        except OSError:
            return None

    def _throttled(self):
        for name_path in sorted(self._glob(HWMON_NAMES)):
            if (self._try(name_path) or "").strip() == "rpi_volt":
                alarm = (self._try(name_path[:-len("name")] + "in0_lcrit_alarm") or "").strip()
                if alarm in ("0", "1"):
                    return "0x1" if alarm == "1" else "0x0"
        return None

    def _wifi(self):
        for line in (self._try("/proc/net/wireless") or "").splitlines():
            name, _, rest = line.partition(":")
            if name.strip() == "wlan0":
                try:
                    dbm = int(float(rest.split()[2].rstrip(".")))
                except (IndexError, ValueError):
                    break
                return {"dbm": dbm, "bars": _bars(dbm)}
        return {"dbm": None, "bars": None}

    def _leds(self):
        raw = self._try(contracts.LED_STATE_FILE)
        if raw is None:
            return None
        try:
            data = json.loads(raw)
            age = self._wall() - self._mtime(contracts.LED_STATE_FILE)
        except (ValueError, OSError):
            return None
        if not isinstance(data, dict) or age > LED_STALE_S:
            return None
        leds = {k: data.get(k) for k in ("enabled", "brightness", "bars", "thermal_off")}
        leds["age_s"] = round(max(age, 0.0), 1)
        return leds

    def set_leds(self, enabled, brightness):
        cli.write_private(self.state_dir / contracts.LED_CONFIG_FILE,
                          json.dumps({"enabled": bool(enabled), "brightness": int(brightness)}))
        return contracts.outcome("accepted", "LED service applies it within 10 s")

    async def power(self, action):
        argv = POWER_ACTIONS[action]  # KeyError = programming error; the API only passes whitelisted names
        now = self._clock()
        if self._last_power is not None and now - self._last_power < contracts.POWER_ACTION_GAP_S:
            raise RateLimited("one power action per %d s" % contracts.POWER_ACTION_GAP_S)
        self._last_power = now
        log.info("power action: %s", action)
        if action == "restart-service":  # the reply must leave before the service dies
            asyncio.get_running_loop().call_later(self._delay, self._spawn, argv)
            return contracts.outcome("accepted", "restarting in %g s" % self._delay)
        return await self._exec(argv)

    def _spawn(self, argv):
        task = asyncio.ensure_future(self._exec(argv))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _exec(self, argv):
        try:
            rc, err = await self._run(list(argv))
        except Exception as e:  # noqa: BLE001 - report any launch failure as an outcome
            rc, err = -1, "%s: %s" % (type(e).__name__, e)
        if rc != 0:
            log.warning("%s exited %s", argv[1], rc)
            return contracts.outcome("failed", "exit %s: %s" % (rc, err.strip()[-200:]))
        return contracts.outcome("accepted", "")
