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


def _bars(dbm):
    if dbm is None:
        return None
    for floor, bars in ((-55, 4), (-65, 3), (-75, 2), (-85, 1)):
        if dbm >= floor:
            return bars
    return 0


class Device:
    def __init__(self, state_dir, *, run=_run, clock=time.monotonic, read=_read_file, wall=time.time,
                 mtime=os.path.getmtime, glob=glob.glob, restart_delay=1.0):
        self.state_dir = Path(state_dir)
        self._run, self._clock, self._read, self._wall, self._mtime = run, clock, read, wall, mtime
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
