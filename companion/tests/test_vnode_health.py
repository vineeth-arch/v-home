import copy
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from vhome_companion.vnode.health import HealthHistory, build_health  # noqa: E402

SNAP = {
    "age_s": 0.4, "temp_c": 45.1, "throttled": 0, "volts": 1.35, "load": (0.04, 0.08, 0.08), "cpu_use": 3.0,
    "cpu_mhz": 1000, "cpu_max_mhz": 1000, "governor": "ondemand",
    "mem_total_kb": 436000, "mem_avail_kb": 372000, "swap_total_kb": 102400, "swap_free_kb": 102400,
    "disk_free_mb": 20000, "disk_total_mb": 28000, "uptime_s": 9000,
    "wifi": {"state": "up", "ip": "192.168.1.50", "dbm": -60, "bars": 3, "errors": 10},
    "bluetooth": {"present": True, "blocked": True}, "restarts": 0,
    "leds": {"supported": True, "age_s": 3.0, "unit": "active"},
}
STATUS = {
    "tv": {"state": "connected", "power": None, "foreground": "com.webos.app.livetv", "last_error": None},
    "watcher": {"state": "watching", "ok": 12, "failed": 0, "last_latency_s": 1.84, "last_failure": None},
}
NODE = {"version": "0.1.0-abc", "uptime_s": 3725}


def health(snap=None, status=None, ntp=True, phones=2, **over):
    s = copy.deepcopy(SNAP)
    s.update(over)
    if snap:
        s.update(snap)
    st = copy.deepcopy(STATUS)
    for k, v in (status or {}).items():
        st[k].update(v)
    return build_health(s, st, NODE, phones, ntp, 0.0)


def item(h, key):
    return next(i for i in h["items"] if i["key"] == key)


def level(key, **kw):
    return item(health(**kw), key)["level"]


class HealthyTest(unittest.TestCase):
    def test_healthy_pi_order_and_levels(self):
        h = health()
        self.assertEqual([(i["group"], i["key"]) for i in h["items"]], [
            ("node", "service"), ("node", "restarts"), ("node", "clock"), ("node", "leds_service"), ("node", "phones"),
            ("tv", "link"), ("tv", "foreground"), ("tv", "power"),
            ("watcher", "state"), ("watcher", "redirects"),
            ("pi", "temp"), ("pi", "throttle_now"), ("pi", "throttle_boot"), ("pi", "voltage"), ("pi", "cpu_load"),
            ("pi", "cpu_use"), ("pi", "cpu_freq"), ("pi", "memory"), ("pi", "swap"), ("pi", "disk"), ("pi", "uptime"),
            ("network", "wifi_link"), ("network", "wifi_signal"), ("network", "wifi_errors"), ("network", "bluetooth")])
        self.assertEqual((h["level"], h["problems"], h["age_s"]), ("ok", 0, 0.4))
        for i in h["items"]:
            self.assertEqual(set(i) - {"metric", "counts"}, {"group", "key", "label", "value", "level", "detail"})
            self.assertEqual(i["detail"], "")
            self.assertIn(i["level"], ("ok", "info"))
        self.assertEqual(item(h, "service")["value"], "0.1.0-abc · up 1 h 2 min")
        self.assertEqual(item(h, "temp")["value"], "45.1 °C")
        self.assertEqual(item(h, "power")["value"], "not reported by this TV")
        self.assertEqual(item(h, "bluetooth")["value"], "Off (not used)")
        self.assertEqual(item(h, "cpu_freq")["value"], "1000 / 1000 MHz · ondemand")
        self.assertEqual(item(h, "redirects")["value"], "12 ok, 0 failed · last 1.8 s")
        json.dumps(h)

    def test_tv_power_when_reported(self):
        self.assertEqual(item(health(status={"tv": {"power": "Active"}}), "power")["value"], "Active")


class PiThresholdTest(unittest.TestCase):
    def test_temp(self):
        for t, lv in ((64.9, "ok"), (65.0, "warn"), (74.9, "warn"), (75.0, "error")):
            self.assertEqual(level("temp", temp_c=t), lv, t)

    def test_throttled_now_and_since_boot(self):
        cases = ((0x0, "ok", "ok"), (0x1, "error", "ok"), (0x2, "warn", "ok"), (0x4, "error", "ok"),
                 (0x8, "warn", "ok"), (0x50000, "ok", "warn"), (0x50005, "error", "warn"))
        for bits, now, boot in cases:
            h = health(throttled=bits)
            self.assertEqual((item(h, "throttle_now")["level"], item(h, "throttle_boot")["level"]), (now, boot), hex(bits))

    def test_undervoltage_detail_and_voltage_item(self):
        h = health(throttled=0x1)
        self.assertEqual(item(h, "throttle_now")["detail"], "The power supply is too weak; use a 5 V 2.5 A supply.")
        self.assertEqual(item(h, "voltage")["level"], "error")
        self.assertEqual(item(health(), "voltage")["level"], "info")
        self.assertEqual(item(health(), "voltage")["value"], "1.35 V")

    def test_load(self):
        for v, lv in ((1.5, "ok"), (1.51, "warn"), (3.0, "warn"), (3.01, "error")):
            self.assertEqual(level("cpu_load", load=(v, 0.1, 0.1)), lv, v)

    def test_memory_boundaries(self):
        total = 436000
        for avail_mb, lv in ((60, "ok"), (59, "warn"), (30, "warn"), (29, "error")):
            self.assertEqual(level("memory", mem_avail_kb=avail_mb * 1024), lv, avail_mb)
        self.assertEqual(total, 436000)

    def test_swap(self):
        for used_mb, lv in ((50, "ok"), (51, "warn")):
            self.assertEqual(level("swap", swap_free_kb=(100 - used_mb) * 1024, swap_total_kb=100 * 1024), lv, used_mb)

    def test_disk(self):
        for free, lv in ((300, "ok"), (299, "warn"), (150, "warn"), (149, "error")):
            self.assertEqual(level("disk", disk_free_mb=free), lv, free)

    def test_cpu_use_states(self):
        self.assertEqual(item(health(cpu_use="measuring"), "cpu_use")["value"], "measuring…")
        self.assertEqual(item(health(cpu_use=37.4), "cpu_use")["value"], "37 %")


class NetworkTest(unittest.TestCase):
    def wifi(self, **kw):
        return {"wifi": {**SNAP["wifi"], **kw}}

    def test_signal(self):
        for dbm, lv in ((-75, "ok"), (-76, "warn"), (-85, "warn"), (-86, "error")):
            self.assertEqual(level("wifi_signal", **self.wifi(dbm=dbm, bars=1)), lv, dbm)

    def test_link_down_is_error(self):
        h = health(**self.wifi(state="down", ip=None))
        self.assertEqual(item(h, "wifi_link")["level"], "error")
        self.assertEqual(item(health(), "wifi_link")["value"], "up · 192.168.1.50")

    def test_errors(self):
        for n, lv in ((100, "ok"), (101, "warn")):
            self.assertEqual(level("wifi_errors", **self.wifi(errors=n)), lv, n)

    def test_bluetooth(self):
        self.assertEqual(level("bluetooth", bluetooth={"present": True, "blocked": False}), "info")
        self.assertEqual(item(health(bluetooth={"present": True, "blocked": False}), "bluetooth")["value"], "On (not used)")
        self.assertEqual(item(health(bluetooth={"present": False, "blocked": None}), "bluetooth")["value"], "Not present")
        h = health()
        self.assertEqual((item(h, "bluetooth")["level"], h["problems"]), ("info", 0))


class NodeTest(unittest.TestCase):
    def test_restarts(self):
        self.assertEqual(level("restarts", restarts=0), "ok")
        self.assertEqual(level("restarts", restarts=1), "warn")

    def test_clock(self):
        self.assertEqual(level("clock", ntp=True), "ok")
        self.assertEqual(level("clock", ntp=False), "warn")
        self.assertEqual(item(health(ntp=None), "clock")["value"], "unavailable")

    def test_led_service(self):
        self.assertEqual(level("leds_service", leds={"supported": True, "age_s": 60.0, "unit": "active"}), "ok")
        self.assertEqual(level("leds_service", leds={"supported": True, "age_s": 61.0, "unit": "active"}), "warn")
        self.assertEqual(level("leds_service", leds={"supported": False, "age_s": None, "unit": None}), "info")

    def test_phones_is_info(self):
        i = item(health(phones=3), "phones")
        self.assertEqual((i["value"], i["level"]), ("3 paired", "info"))


class TvWatcherTest(unittest.TestCase):
    def test_every_tv_state(self):
        expect = {"connected": "ok", "standby": "ok", "unreachable": "warn", "unknown": "warn",
                  "pairing_required": "error", "certificate_mismatch": "error", "permission_denied": "error",
                  "launcher_missing": "error"}
        for state, lv in expect.items():
            i = item(health(status={"tv": {"state": state}}), "link")
            self.assertEqual(i["level"], lv, state)
            self.assertEqual(bool(i["detail"]), lv != "ok", state)

    def test_last_error_only_when_set(self):
        self.assertNotIn("last_error", [i["key"] for i in health()["items"]])
        i = item(health(status={"tv": {"last_error": "boom client-key=SECRET99 end"}}), "last_error")
        self.assertEqual(i["level"], "info")
        self.assertNotIn("SECRET99", i["value"])

    def test_watcher_states(self):
        expect = {"watching": "ok", "user_paused": "warn", "disabled": "warn", "safety_paused": "error", "not_ready": "error"}
        for state, lv in expect.items():
            self.assertEqual(item(health(status={"watcher": {"state": state}}), "state")["level"], lv, state)

    def test_redirect_failures_and_last_failure(self):
        h = health(status={"watcher": {"failed": 2, "last_failure": "timeout"}})
        self.assertEqual(item(h, "redirects")["level"], "warn")
        self.assertEqual(item(h, "last_failure")["value"], "timeout")
        self.assertEqual(item(h, "last_failure")["level"], "info")
        self.assertNotIn("last_failure", [i["key"] for i in health()["items"]])


class RollupTest(unittest.TestCase):
    def test_worst_level_and_problem_count(self):
        h = health(temp_c=66.0, restarts=1)  # two warns
        self.assertEqual((h["level"], h["problems"]), ("warn", 2))
        h = health(temp_c=80.0, restarts=1, disk_free_mb=100)  # error + warn + error
        self.assertEqual((h["level"], h["problems"]), ("error", 3))

    def test_info_counts_as_ok(self):
        h = health(cpu_use="measuring")
        self.assertEqual((h["level"], h["problems"]), ("ok", 0))

    def test_unavailable_is_info_and_not_a_problem(self):
        h = build_health({}, {}, {}, None, None, 0.0)
        self.assertEqual((h["level"], h["problems"]), ("ok", 0))
        by = {i["key"]: i for i in h["items"]}
        for key in ("service", "restarts", "clock", "leds_service", "phones", "link", "state", "redirects", "temp",
                    "throttle_now", "throttle_boot", "voltage", "cpu_load", "cpu_use", "cpu_freq", "memory", "swap",
                    "disk", "uptime", "wifi_link", "wifi_signal", "wifi_errors", "bluetooth"):
            self.assertEqual((by[key]["value"], by[key]["level"]), ("unavailable", "info"), key)
        self.assertEqual((by["power"]["value"], by["foreground"]["value"]), ("not reported by this TV", "unavailable"))



METRIC_KEYS = {"temp", "cpu_load", "cpu_use", "cpu_freq", "memory", "swap", "disk", "voltage", "wifi_signal"}


class MetricTest(unittest.TestCase):
    def metric(self, key, **kw):
        return item(health(**kw), key).get("metric")

    def test_only_the_listed_items_carry_a_metric(self):
        h = health()
        self.assertEqual({i["key"] for i in h["items"] if "metric" in i}, METRIC_KEYS)
        json.dumps(h)

    def test_temp(self):
        self.assertEqual(self.metric("temp"), {"value": 45.1, "min": 0, "max": 85, "unit": "°C", "warn": 65.0,
                                               "error": 75.0, "higher_is_worse": True})
        self.assertEqual(level("temp", temp_c=65.0), "warn")
        self.assertEqual(self.metric("temp", temp_c=80.0)["value"], 80.0)

    def test_cpu_load_uses_the_one_minute_value(self):
        self.assertEqual(self.metric("cpu_load", load=(2.0, 1.0, 0.5)),
                         {"value": 2.0, "min": 0, "max": 4, "unit": "", "warn": 1.5, "error": 3.0, "higher_is_worse": True})

    def test_cpu_use_and_measuring(self):
        self.assertEqual(self.metric("cpu_use"), {"value": 3.0, "min": 0, "max": 100, "unit": "%", "higher_is_worse": True})
        self.assertNotIn("metric", item(health(cpu_use="measuring"), "cpu_use"))

    def test_cpu_freq_is_info_with_max(self):
        m = self.metric("cpu_freq", cpu_mhz=600, cpu_max_mhz=1000)
        self.assertEqual((m["value"], m["min"], m["max"], m["unit"]), (600, 0, 1000, "MHz"))
        self.assertNotIn("warn", m)
        self.assertNotIn("metric", item(health(cpu_max_mhz=None), "cpu_freq"))

    def test_memory_thresholds_are_total_minus_60_and_30(self):
        m = self.metric("memory")   # total 436000 kB = 426 MB, available 372000 kB
        self.assertEqual((m["value"], m["min"], m["max"], m["unit"], m["warn"], m["error"]), (62, 0, 426, "MB", 366, 396))
        self.assertTrue(m["higher_is_worse"])

    def test_swap_used(self):
        m = self.metric("swap", swap_free_kb=102400 - 30720)
        self.assertEqual((m["value"], m["max"], m["warn"]), (30, 100, 50))
        self.assertNotIn("metric", item(health(swap_total_kb=0, swap_free_kb=0), "swap"))

    def test_disk_used_with_thresholds(self):
        m = self.metric("disk", disk_free_mb=1000, disk_total_mb=4000)
        self.assertEqual((m["value"], m["max"], m["warn"], m["error"], m["unit"]), (3000, 4000, 3700, 3850, "MB"))

    def test_voltage_is_info_range(self):
        self.assertEqual(self.metric("voltage"), {"value": 1.35, "min": 0.8, "max": 1.4, "unit": "V", "higher_is_worse": True})
        self.assertIn("metric", item(health(throttled=1), "voltage"))   # still present on under-voltage (error)

    def test_wifi_signal_lower_is_worse_with_bars(self):
        self.assertEqual(self.metric("wifi_signal"), {"value": -60, "min": -95, "max": -30, "unit": "dBm", "warn": -75,
                                                      "error": -85, "higher_is_worse": False, "bars": 3})
        self.assertEqual(self.metric("wifi_signal", wifi={"state": "up", "dbm": -80, "bars": 1})["bars"], 1)
        self.assertNotIn("bars", self.metric("wifi_signal", wifi={"state": "up", "dbm": -80, "bars": None}))

    def test_redirects_counts(self):
        h = health(status={"watcher": {"ok": 5, "failed": 2}})
        self.assertEqual(item(h, "redirects")["counts"], {"ok": 5, "failed": 2})
        self.assertEqual(item(health(), "redirects")["counts"], {"ok": 12, "failed": 0})
        self.assertNotIn("metric", item(h, "redirects"))

    def test_no_metric_or_counts_when_the_reading_is_unavailable(self):
        h = build_health({}, {"tv": {}, "watcher": {}}, {}, None, None, 0.0)
        for i in h["items"]:
            self.assertNotIn("metric", i)
            self.assertNotIn("counts", i)
        for key in METRIC_KEYS | {"redirects"}:
            self.assertEqual((item(h, key)["value"], item(h, key)["level"]), ("unavailable", "info"))


class HistoryTest(unittest.TestCase):
    def snap(self, i):
        return {"temp_c": 40.0 + i, "cpu_use": float(i), "load": (i / 10.0, 0, 0), "mem_total_kb": 1024 * 400,
                "mem_avail_kb": 1024 * (400 - i), "wifi": {"dbm": -50 - i}}

    def test_empty_at_start(self):
        h = health()
        self.assertEqual(h["history"], {"interval_s": 30, "temp": [], "cpu_use": [], "load": [], "mem_used_mb": [], "wifi_dbm": []})
        self.assertEqual(HealthHistory().as_dict(), h["history"])

    def test_oldest_first_and_values(self):
        hh = HealthHistory()
        for i in range(3):
            hh.add(self.snap(i))
        d = hh.as_dict()
        self.assertEqual(d["temp"], [40.0, 41.0, 42.0])
        self.assertEqual(d["load"], [0.0, 0.1, 0.2])
        self.assertEqual(d["mem_used_mb"], [0, 1, 2])
        self.assertEqual(d["wifi_dbm"], [-50, -51, -52])
        self.assertEqual(build_health(SNAP, STATUS, NODE, 1, True, 0.0, history=d)["history"], d)

    def test_capped_at_120(self):
        hh = HealthHistory()
        for i in range(150):
            hh.add(self.snap(i))
        d = hh.as_dict()
        self.assertTrue(all(len(d[k]) == 120 for k in ("temp", "cpu_use", "load", "mem_used_mb", "wifi_dbm")))
        self.assertEqual((d["temp"][0], d["temp"][-1]), (70.0, 189.0))
        over = build_health(SNAP, STATUS, NODE, 1, True, 0.0, history={"temp": list(range(500))})["history"]
        self.assertEqual((len(over["temp"]), over["temp"][0]), (120, 380))

    def test_missing_readings_are_null(self):
        hh = HealthHistory()
        hh.add({"cpu_use": "measuring"})
        hh.add(None)
        d = hh.as_dict()
        for k in ("temp", "cpu_use", "load", "mem_used_mb", "wifi_dbm"):
            self.assertEqual(d[k], [None, None], k)
        json.dumps(d)


class HwmonFallbackTest(unittest.TestCase):
    def test_since_boot_is_unavailable_when_only_hwmon_answered(self):
        h = health(throttled=0, throttled_source="hwmon")
        item = next(i for i in h["items"] if i["key"] == "throttle_boot")
        self.assertEqual((item["value"], item["level"]), ("unavailable", "info"))


if __name__ == "__main__":
    unittest.main()
