import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from vhome_companion import cli  # noqa: E402
from vhome_companion.vnode.store import Store  # noqa: E402


def mode(p):
    return Path(p).stat().st_mode & 0o777


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d = Path(self.tmp.name) / "state"
        self.s = Store(self.d)

    def test_defaults_without_files(self):
        c = self.s.load_control()
        self.assertEqual(c, {"paused": False, "pause_reason": None, "paused_until": None,
                             "watcher_enabled": True, "power_on_launch": False})
        tv = self.s.tv_config()
        self.assertEqual(tv["home_ids"], ["com.webos.app.home"])
        self.assertEqual((tv["host"], tv["key"], tv["pin"]), ("", None, None))

    def test_control_roundtrip_is_0600(self):
        self.s.save_control({"paused": True, "pause_reason": "user", "paused_until": "2030-01-01T00:00:00Z",
                             "watcher_enabled": False, "power_on_launch": True})
        self.assertEqual(mode(self.d / "control.json"), 0o600)
        again = Store(self.d).load_control()
        self.assertTrue(again["paused"] and not again["watcher_enabled"] and again["power_on_launch"])
        self.assertEqual(again["paused_until"], "2030-01-01T00:00:00Z")

    def test_corrupt_control_gives_defaults_and_one_warning(self):
        (self.d / "control.json").write_text("{not json")
        with self.assertLogs("vhome.vnode.store", "WARNING") as cm:
            self.assertTrue(self.s.load_control()["watcher_enabled"])
            self.assertFalse(self.s.load_control()["paused"])
        self.assertEqual(len(cm.output), 1)

    def test_wrong_field_types_fall_back_per_field(self):
        (self.d / "control.json").write_text(json.dumps(
            {"paused": "yes", "pause_reason": "x", "paused_until": 5, "watcher_enabled": False}))
        c = self.s.load_control()
        self.assertFalse(c["paused"])
        self.assertFalse(c["watcher_enabled"])
        self.assertIsNone(c["paused_until"])

    def test_unpaused_clears_reason_and_deadline(self):
        c = self.s.save_control({"paused": False, "pause_reason": "user", "paused_until": "2030-01-01T00:00:00Z"})
        self.assertIsNone(c["pause_reason"])
        self.assertIsNone(c["paused_until"])

    def test_pairing_files_and_bak_on_repair(self):
        self.s.save_tv_pairing("192.168.1.9", "key-one", "pin-one")
        self.assertEqual(self.s.paired(), ("key-one", "pin-one"))
        self.assertEqual(cli.load_config(self.d)["host"], "192.168.1.9")
        self.assertFalse((self.d / "client-key.bak").exists())
        self.s.save_tv_pairing("192.168.1.10", "key-two", "pin-two")
        self.assertEqual(self.s.paired(), ("key-two", "pin-two"))
        self.assertEqual((self.d / "client-key.bak").read_text().strip(), "key-one")
        self.assertEqual((self.d / "cert.sha256.bak").read_text().strip(), "pin-one")
        for name in ("client-key", "cert.sha256", "client-key.bak", "cert.sha256.bak", "config.json"):
            self.assertEqual(mode(self.d / name), 0o600, name)

    def test_pairing_keeps_other_config_values(self):
        cli.save_config(self.d, {**cli.DEFAULTS, "home_ids": ["x.home"], "double_home_escape": True})
        self.s.save_tv_pairing("tv.local", "k", "p")
        tv = self.s.tv_config()
        self.assertEqual(tv["home_ids"], ["x.home"])
        self.assertTrue(tv["double_home_escape"])
        self.assertEqual(tv["host"], "tv.local")


if __name__ == "__main__":
    unittest.main()
