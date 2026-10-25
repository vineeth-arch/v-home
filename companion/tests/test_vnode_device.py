import asyncio
import fnmatch
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from vhome_companion.vnode import contracts  # noqa: E402
from vhome_companion.vnode.device import Device, RateLimited  # noqa: E402

WIRELESS = """Inter-| sta-|   Quality        |   Discarded packets               | Missing
 face | tus | link level noise |  nwid  crypt   frag  retry   misc | beacon
 wlan0: 0000   41.  -69.  -256        0      0      0      0      0        0
"""
FILES = {
    "/sys/class/thermal/thermal_zone0/temp": "43300\n",
    "/sys/class/hwmon/hwmon2/name": "rpi_volt\n",
    "/sys/class/hwmon/hwmon2/in0_lcrit_alarm": "0\n",
    "/proc/meminfo": "MemTotal:  436000 kB\nMemFree: 1 kB\nMemAvailable:  372000 kB\n",
    "/proc/uptime": "9000.55 100.0\n",
    "/proc/net/wireless": WIRELESS,
}


class Clock:
    t = 0.0

    def __call__(self):
        return self.t


def make(files, **kw):
    def read(path):
        try:
            return files[path]
        except KeyError:
            raise FileNotFoundError(path) from None
    kw.setdefault("glob", lambda pat: sorted(p for p in files if fnmatch.fnmatch(p, pat)))
    return Device(Path(tempfile.mkdtemp()), read=read, **kw)


class StatusTest(unittest.TestCase):
    def test_parses_fake_proc_and_sys(self):
        s = make(FILES).status()
        self.assertEqual((s["temp_c"], s["throttled"], s["uptime_s"]), (43.3, "0x0", 9000))
        self.assertEqual((s["mem_total_mb"], s["mem_used_mb"]), (425, 62))
        self.assertEqual(s["wifi"], {"dbm": -69, "bars": 2})
        self.assertIsNone(s["leds"])
        self.assertGreater(s["disk_free_mb"], 0)

    def test_undervoltage(self):
        s = make({**FILES, "/sys/class/hwmon/hwmon2/in0_lcrit_alarm": "1"}).status()
        self.assertEqual(s["throttled"], "0x1")

    def test_other_hwmon_ignored(self):
        files = {k: v for k, v in FILES.items() if "hwmon" not in k}
        files["/sys/class/hwmon/hwmon0/name"] = "cpu_thermal\n"
        self.assertIsNone(make(files).status()["throttled"])

    def test_missing_files_are_none(self):
        s = make({}).status()
        for k in ("temp_c", "throttled", "mem_used_mb", "mem_total_mb", "uptime_s"):
            self.assertIsNone(s[k], k)
        self.assertEqual(s["wifi"], {"dbm": None, "bars": None})

    def test_bars(self):
        for dbm, bars in ((-50, 4), (-55, 4), (-60, 3), (-69, 2), (-80, 1), (-90, 0)):
            w = WIRELESS.replace("-69.", "%d." % dbm)
            self.assertEqual(make({"/proc/net/wireless": w}).status()["wifi"]["bars"], bars)

    def test_leds_state_and_staleness(self):
        files = {**FILES, contracts.LED_STATE_FILE: json.dumps(
            {"enabled": True, "brightness": 2, "bars": 2, "thermal_off": False})}
        fresh = make(files, wall=lambda: 104.0, mtime=lambda p: 100.0).status()["leds"]
        self.assertEqual(fresh, {"enabled": True, "brightness": 2, "bars": 2, "thermal_off": False, "age_s": 4.0})
        self.assertIsNone(make(files, wall=lambda: 200.0, mtime=lambda p: 100.0).status()["leds"])

    def test_set_leds_writes_private_config(self):
        d = make({})
        out = d.set_leds(True, 3)
        self.assertEqual(out["outcome"], "accepted")
        p = d.state_dir / contracts.LED_CONFIG_FILE
        self.assertEqual(json.loads(p.read_text()), {"enabled": True, "brightness": 3})
        self.assertEqual(p.stat().st_mode & 0o777, 0o600)


class PowerTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.calls, self.clock, self.rc = [], Clock(), 0

    def device(self, **kw):
        async def run(argv):
            self.calls.append(argv)
            return self.rc, "boom\n"
        return make({}, run=run, clock=self.clock, **kw)

    async def test_exact_argv(self):
        for action, argv in (("reboot", ["systemctl", "reboot"]), ("shutdown", ["systemctl", "poweroff"])):
            self.calls.clear()
            d = self.device()
            self.assertEqual((await d.power(action))["outcome"], "accepted")
            self.assertEqual(self.calls, [argv])

    async def test_restart_is_delayed(self):
        d = self.device(restart_delay=0.05)
        self.assertEqual((await d.power("restart-service"))["outcome"], "accepted")
        self.assertEqual(self.calls, [])
        await asyncio.sleep(0.15)
        self.assertEqual(self.calls, [["systemctl", "restart", "vhome-vnode.service"]])

    async def test_rate_limit(self):
        d = self.device()
        await d.power("reboot")
        self.clock.t += contracts.POWER_ACTION_GAP_S - 1
        with self.assertRaises(RateLimited):
            await d.power("shutdown")
        self.clock.t += 2
        await d.power("shutdown")
        self.assertEqual(len(self.calls), 2)

    async def test_nonzero_exit_is_failed(self):
        self.rc = 1
        out = await self.device().power("reboot")
        self.assertEqual(out["outcome"], "failed")
        self.assertIn("boom", out["detail"])

    async def test_unknown_action_never_runs(self):
        with self.assertRaises(KeyError):
            await self.device().power("rm -rf /")
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()


PI = {
    **FILES,
    "/proc/stat": "cpu  71044 8652 24055 1283681 5719 0 1334 0 0 0\ncpu0 1 1 1 1 1 0 0 0 0 0\n",
    "/proc/loadavg": "0.04 0.08 0.08 1/111 6714\n",
    "/proc/meminfo": "MemTotal:  436000 kB\nMemAvailable:  372000 kB\nSwapTotal: 102400 kB\nSwapFree: 102400 kB\n",
    "/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq": "1000000\n",
    "/sys/devices/system/cpu/cpu0/cpufreq/scaling_max_freq": "1000000\n",
    "/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor": "ondemand\n",
    "/sys/class/rfkill/rfkill0/type": "bluetooth\n", "/sys/class/rfkill/rfkill0/soft": "1\n",
    "/sys/class/rfkill/rfkill0/hard": "0\n",
    "/sys/class/rfkill/rfkill1/type": "wlan\n", "/sys/class/rfkill/rfkill1/soft": "0\n",
    "/sys/class/bluetooth/hci0": "",
    "/sys/class/net/wlan0/operstate": "up\n",
    "/sys/class/net/wlan0/statistics/rx_errors": "1\n", "/sys/class/net/wlan0/statistics/tx_errors": "2\n",
    "/sys/class/net/wlan0/statistics/rx_dropped": "3\n", "/sys/class/net/wlan0/statistics/tx_dropped": "4\n",
}
OUT = {
    "get_throttled": "throttled=0x50005\n",
    "measure_volts": "volt=1.3500V\n",
    "addr": "3: wlan0    inet 192.168.1.50/24 brd 192.168.1.255 scope global dynamic wlan0\\       valid_lft 85000sec\n",
    "NRestarts": "2\n",
    "ActiveState": "active\n",
}


def make_out(files, outputs=None, **kw):
    outputs, calls = dict(OUT if outputs is None else outputs), []

    async def run_out(argv):
        calls.append(list(argv))
        for k, v in outputs.items():
            if k in argv or k in " ".join(argv):
                return 0, v
        return 1, ""
    return make(files, run_out=run_out, **kw), calls


class HealthSnapshotTest(unittest.IsolatedAsyncioTestCase):
    async def test_parses_everything(self):
        dev, calls = make_out(PI)
        s = await dev.health_snapshot()
        self.assertEqual((s["throttled"], s["volts"], s["restarts"]), (0x50005, 1.35, 2))
        self.assertEqual(s["wifi"], {"state": "up", "ip": "192.168.1.50", "dbm": -69, "bars": 2, "errors": 10})
        self.assertEqual((s["load"], s["cpu_mhz"], s["cpu_max_mhz"], s["governor"]), ((0.04, 0.08, 0.08), 1000, 1000, "ondemand"))
        self.assertEqual((s["mem_total_kb"], s["mem_avail_kb"], s["swap_total_kb"], s["swap_free_kb"]),
                         (436000, 372000, 102400, 102400))
        self.assertEqual(s["bluetooth"], {"present": True, "blocked": True})
        self.assertEqual(s["cpu_use"], "measuring")
        self.assertEqual(s["leds"], {"supported": False, "age_s": None, "unit": "active"})
        self.assertGreater(s["disk_total_mb"], 0)
        self.assertEqual(len(calls), 5)
        self.assertTrue(all(isinstance(a, list) for a in calls))

    async def test_cache_runs_each_probe_once_within_10s(self):
        clock = Clock()
        dev, calls = make_out(PI, clock=clock)
        await dev.health_snapshot()
        clock.t = 9.9
        await dev.health_snapshot()
        self.assertEqual(len(calls), 5)
        clock.t = 10.0
        s = await dev.health_snapshot()
        self.assertEqual(len(calls), 10)
        self.assertEqual(s["age_s"], 0.0)

    async def test_failed_probe_is_cached_too(self):
        clock = Clock()
        dev, calls = make_out(PI, outputs={}, clock=clock)
        s = await dev.health_snapshot()
        await dev.health_snapshot()
        self.assertEqual(len(calls), 5)
        self.assertEqual((s["volts"], s["restarts"], s["wifi"]["ip"], s["leds"]["unit"]), (None, None, None, None))
        self.assertEqual(s["throttled"], 0)  # falls back to the rpi_volt hwmon (alarm 0)

    async def test_vcgencmd_missing_uses_hwmon_undervoltage(self):
        dev, _ = make_out({**PI, "/sys/class/hwmon/hwmon2/in0_lcrit_alarm": "1\n"}, outputs={})
        self.assertEqual((await dev.health_snapshot())["throttled"], 1)

    async def test_runner_exception_is_unavailable(self):
        async def boom(argv):
            raise FileNotFoundError(argv[0])
        s = await make(PI, run_out=boom).health_snapshot()
        self.assertEqual((s["volts"], s["restarts"]), (None, None))

    async def test_cpu_use_from_two_snapshots(self):
        files = dict(PI)
        dev, _ = make_out(files)
        await dev.health_snapshot()
        # +100 jiffies busy (user 60, system 40), +100 idle -> 50 %
        files["/proc/stat"] = "cpu  71104 8652 24095 1283781 5719 0 1334 0 0 0\n"
        self.assertEqual((await dev.health_snapshot())["cpu_use"], 50.0)
        # no time passed -> not computable
        self.assertIsNone((await dev.health_snapshot())["cpu_use"])

    async def test_cpu_use_ignores_iowait_as_busy(self):
        files = dict(PI)
        dev, _ = make_out(files)
        await dev.health_snapshot()
        files["/proc/stat"] = "cpu  71044 8652 24055 1283681 5819 0 1334 0 0 0\n"  # only iowait grew
        self.assertEqual((await dev.health_snapshot())["cpu_use"], 0.0)

    async def test_bluetooth_states(self):
        on = {**PI, "/sys/class/rfkill/rfkill0/soft": "0\n"}
        self.assertEqual((await make_out(on)[0].health_snapshot())["bluetooth"], {"present": True, "blocked": False})
        none = {k: v for k, v in PI.items() if "rfkill0" not in k and "bluetooth/" not in k}
        self.assertEqual((await make_out(none)[0].health_snapshot())["bluetooth"], {"present": False, "blocked": None})

    async def test_led_service_age(self):
        files = {**PI, contracts.LED_STATE_FILE: "{}"}
        s = await make_out(files, wall=lambda: 130.0, mtime=lambda p: 100.0)[0].health_snapshot()
        self.assertEqual(s["leds"], {"supported": True, "age_s": 30.0, "unit": "active"})

    async def test_missing_everything(self):
        s = await make_out({}, outputs={}, disk=lambda p: (_ for _ in ()).throw(OSError()))[0].health_snapshot()
        for k in ("temp_c", "throttled", "volts", "load", "cpu_use", "cpu_mhz", "mem_total_kb", "swap_total_kb",
                  "disk_free_mb", "uptime_s", "restarts", "governor"):
            self.assertIsNone(s[k], k)
        self.assertEqual(s["wifi"], {"state": None, "ip": None, "dbm": None, "bars": None, "errors": None})
