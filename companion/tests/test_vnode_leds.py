import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from vhome_companion.vnode import contracts, leds  # noqa: E402

SAMPLE = ("Inter-| sta-|   Quality        |   Discarded packets               | Missed | WE\n"
          " face | tus | link level noise |  nwid  crypt   frag  retry   misc | beacon | 22\n"
          " wlan0: 0000   41.  -69.  -256        0      0      0     45      0        0\n")


class FakeDriver:
    def __init__(self):
        self.writes = []

    def write(self, data):
        self.writes.append(data)


class PureTests(unittest.TestCase):
    def test_rssi_and_bars(self):
        self.assertEqual(leds.rssi_dbm(SAMPLE), -69)
        self.assertEqual(leds.bars(-69), 2)

    def test_missing_wlan0(self):
        self.assertIsNone(leds.rssi_dbm(" eth0: 0000 1. 2. 3.\n"))
        self.assertIsNone(leds.rssi_dbm(""))
        self.assertEqual(leds.bars(None), 0)

    def test_bar_thresholds(self):
        for dbm, n in ((-40, 4), (-55, 4), (-56, 3), (-65, 3), (-66, 2), (-75, 2), (-76, 1), (-85, 1), (-86, 0)):
            self.assertEqual(leds.bars(dbm), n, dbm)

    def test_colour(self):
        self.assertEqual(leds.colour(4), leds.GREEN)
        self.assertEqual(leds.colour(3), leds.GREEN)
        self.assertEqual(leds.colour(2), leds.AMBER)
        self.assertEqual(leds.colour(1), leds.RED)
        self.assertEqual(leds.colour(0), leds.RED)

    def test_frame_two_pixels_exact(self):
        # start frame, then 0xE0|brightness, B, G, R per LED, then the end frame
        self.assertEqual(leds.frame([(1, 2, 3), (4, 5, 6)], 2),
                         bytes([0, 0, 0, 0, 0xE2, 3, 2, 1, 0xE2, 6, 5, 4, 0, 0, 0, 0, 0]))

    def test_brightness_cap(self):
        self.assertEqual(leds.frame([(1, 1, 1)], 31)[4], 0xE0 | leds.MAX_BRIGHTNESS)
        self.assertEqual(leds.frame([(1, 1, 1)], -3)[4], 0xE0)
        self.assertEqual(leds.parse_config('{"enabled": true, "brightness": 20}')["brightness"], leds.MAX_BRIGHTNESS)

    def test_render_lights_first_bars_only(self):
        data = leds.render(2, True, False, 2)
        px = [data[4 + 4 * i: 8 + 4 * i] for i in range(leds.NUM_LEDS)]
        self.assertEqual(px[0], bytes([0xE2, 0, 20, 40]))
        self.assertEqual(px[1], px[0])
        self.assertTrue(all(p == bytes([0xE2, 0, 0, 0]) for p in px[2:]))

    def test_render_off_cases(self):
        off = leds.render(0, True, False, 2)
        self.assertEqual(leds.render(4, False, False, 2), off)
        self.assertEqual(leds.render(4, True, True, 2), off)

    def test_config_defaults_and_corrupt(self):
        self.assertEqual(leds.parse_config("{not json"), leds.DEFAULT_CONFIG)
        self.assertEqual(leds.parse_config('{"enabled": "yes", "brightness": "x"}'), leds.DEFAULT_CONFIG)
        self.assertEqual(leds.parse_config('{"enabled": false, "brightness": 3}'), {"enabled": False, "brightness": 3})

    def test_apa102_bit_order(self):
        pins = []
        leds.Apa102(lambda p, v: pins.append((p, v))).write(bytes([0b10100000]))
        data = [v for p, v in pins if p == leds.PIN_DATA]
        self.assertEqual(data, [1, 0, 1, 0, 0, 0, 0, 0])
        self.assertEqual([p for p, _ in pins[:3]], [23, 24, 24])
        self.assertEqual([v for p, v in pins[:3] if p == 24], [1, 0])


class ThermalGuardTests(unittest.TestCase):
    def test_hysteresis(self):
        g = leds.ThermalGuard()
        self.assertTrue(g.update(69.0, "0x0"))
        self.assertFalse(g.update(70.0, "0x0"))
        self.assertFalse(g.update(65.0, "0x0"))
        self.assertFalse(g.update(60.0, "0x0"))
        self.assertTrue(g.update(59.0, "0x0"))

    def test_throttled_bits(self):
        g = leds.ThermalGuard()
        self.assertTrue(g.update(40.0, "0x50000"))     # historic bits only
        self.assertFalse(g.update(40.0, "0x4"))        # throttled right now
        self.assertFalse(g.update(40.0, "0x50005"))
        self.assertTrue(g.update(40.0, "0x50000"))

    def test_unknown_temp_keeps_state(self):
        g = leds.ThermalGuard()
        self.assertTrue(g.update(None, None))
        g.update(75.0, "0x0")
        self.assertFalse(g.update(None, None))
        self.assertFalse(g.update(None, "garbage"))


class ReadThrottledTests(unittest.TestCase):
    def test_hwmon_rpi_volt(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(leds.read_throttled(d + "/hwmon*"))
            for n, name, alarm in (("hwmon0", "cpu_thermal", None), ("hwmon1", "rpi_volt", "1")):
                (Path(d) / n).mkdir()
                (Path(d) / n / "name").write_text(name + "\n")
                if alarm:
                    (Path(d) / n / "in0_lcrit_alarm").write_text(alarm + "\n")
            self.assertEqual(leds.read_throttled(d + "/hwmon*"), "0x1")
            (Path(d) / "hwmon1" / "in0_lcrit_alarm").write_text("0\n")
            self.assertEqual(leds.read_throttled(d + "/hwmon*"), "0x0")


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.wifi = self.dir / "wireless"
        self.wifi.write_text(SAMPLE)
        self.state = self.dir / "state.json"
        self.driver = FakeDriver()
        self.temp = 45.0
        self.svc = leds.LedService(self.driver, self.dir, state_file=self.state, wireless_path=self.wifi,
                                   temp_reader=lambda: self.temp, throttled_reader=lambda: "0x0")

    def test_writes_only_on_change_and_publishes_state(self):
        self.svc.step()
        self.svc.step()
        self.assertEqual(len(self.driver.writes), 1)
        st = json.loads(self.state.read_text())
        self.assertEqual((st["enabled"], st["brightness"], st["bars"], st["dbm"], st["thermal_off"]),
                         (True, 2, 2, -69, False))
        self.assertEqual(st["temp_c"], 45.0)
        self.assertTrue(st["updated"].endswith("+00:00"))
        self.wifi.write_text(SAMPLE.replace("-69.", "-50."))
        self.svc.step()
        self.assertEqual(len(self.driver.writes), 2)
        self.assertEqual(json.loads(self.state.read_text())["bars"], 4)

    def test_config_reload_turns_leds_off(self):
        self.svc.step()
        (self.dir / contracts.LED_CONFIG_FILE).write_text('{"enabled": false, "brightness": 2}')
        self.svc.step()
        self.assertEqual(self.driver.writes[-1], leds.render(0, False, False, 2))
        self.assertFalse(json.loads(self.state.read_text())["enabled"])

    def test_thermal_off(self):
        self.temp = 72.0
        self.svc.step()
        self.assertEqual(self.driver.writes[-1], leds.render(0, True, True, 2))
        self.assertTrue(json.loads(self.state.read_text())["thermal_off"])

    def test_missing_wifi_is_dark_with_null_dbm(self):
        self.wifi.unlink()
        self.svc.step()
        st = json.loads(self.state.read_text())
        self.assertEqual((st["bars"], st["dbm"]), (0, None))

    def test_failed_write_is_retried(self):
        calls = []

        def flaky(data):
            calls.append(data)
            if len(calls) == 1:
                raise OSError("busy")
        self.driver.write = flaky
        with self.assertRaises(OSError):
            self.svc.step()
        self.svc.step()
        self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
