import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from vhome_companion import appswatch as a  # noqa: E402

LP = [{"id": "netflix"}, {"id": "hotstar"}, {"id": "com.webos.app.hidden", "hidden": True}, {"id": "x", "visible": False}, "junk", {"id": 5}]
DEV = [{"appId": "com.webos.app.hdmi1"}, {"nope": 1}]


class AppsWatchTests(unittest.TestCase):
    def test_app_ids_keeps_hidden_skips_junk(self):
        self.assertEqual(a.app_ids(LP, DEV), frozenset({"netflix", "hotstar", "com.webos.app.hidden", "x", "com.webos.app.hdmi1"}))
        self.assertEqual(a.app_ids(None, None), frozenset())

    def test_known_ids_and_diff(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(a.known_ids(d))  # no catalog yet: never report a change
            Path(d, "catalog.json").write_text(json.dumps({"entries": [{"id": "netflix"}, {"id": "gone"}, {"id": "com.webos.app.hdmi1"}]}))
            known = a.known_ids(d)
            added, removed = a.diff(a.app_ids(LP, DEV), known)
            self.assertEqual(added, {"hotstar", "com.webos.app.hidden", "x"})
            self.assertEqual(removed, {"gone"})
            Path(d, "catalog.json").write_text("{bad")
            self.assertIsNone(a.known_ids(d))
        self.assertEqual(a.diff(frozenset({"a"}), None), (frozenset(), frozenset()))

    def test_decide(self):
        add, none = frozenset({"new"}), frozenset()
        self.assertEqual(a.decide(none, none, None, True, "cmd", True, 0, None), (None, None))
        act, sig = a.decide(add, none, None, False, "", True, 0, None)
        self.assertEqual(act, "notify")
        self.assertEqual(a.decide(add, none, sig, False, "", True, 1, None)[0], None)  # already told
        self.assertEqual(a.decide(add, none, None, True, "cmd", True, 0, None)[0], "refresh")
        self.assertEqual(a.decide(add, none, None, True, "cmd", False, 0, None)[0], "notify")  # another app is in front: never refresh
        self.assertEqual(a.decide(add, none, sig, True, "", True, 0, None)[0], None)  # auto on but no command
        self.assertEqual(a.decide(add, none, sig, True, "cmd", True, 100, 0)[0], None)  # too soon after the last refresh
        self.assertEqual(a.decide(add, none, sig, True, "cmd", True, a.REFRESH_MIN_GAP_S + 1, 0)[0], "refresh")


if __name__ == "__main__":
    unittest.main()
