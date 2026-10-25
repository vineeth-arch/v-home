import asyncio
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
    kw.setdefault("glob", lambda pat: [p for p in files if p.startswith("/sys/class/hwmon/") and p.endswith("/name")])
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
