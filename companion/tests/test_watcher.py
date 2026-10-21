import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from vhome_companion.watcher import ConfigError, Watcher  # noqa: E402

VH, HOME = "com.designinnsaeit.vhome", "com.webos.app.home"


def kinds(actions):
    return [a.kind for a in actions]


def launches(actions):
    return [a for a in actions if a.kind == "launch"]


def make(**kw):
    return Watcher(VH, [HOME], **kw)


def redirect_ok(w, t):
    """Home at t, launch accepted, V/HOME in front at t+1. Returns the launch action."""
    out = w.on_foreground(HOME, t)
    (a,) = launches(out)
    w.on_launch_result(a.token, True, t + 0.5)
    w.on_foreground(VH, t + 1)
    return a


class WatcherTests(unittest.TestCase):
    def test_config_errors(self):
        with self.assertRaises(ConfigError):
            Watcher(VH, [])
        with self.assertRaises(ConfigError):
            Watcher(VH, ["", None])
        with self.assertRaises(ConfigError):
            Watcher("", [HOME])
        with self.assertRaises(ConfigError):
            Watcher(VH, [VH])

    def test_home_launches_once_and_confirms(self):
        w = make()
        out = w.on_foreground(HOME, 0)
        (a,) = launches(out)
        self.assertEqual(a.app_id, VH)
        w.on_launch_result(a.token, True, 0.4)
        self.assertIsNotNone(w.pending)  # still waiting for V/HOME to be in front
        out = w.on_foreground(VH, 1.0)
        self.assertIsNone(w.pending)
        self.assertEqual(w.stats["ok"], 1)
        self.assertEqual(w.stats["last_latency_s"], 1.0)
        self.assertFalse(launches(out))

    def test_duplicate_events_do_not_relaunch(self):
        w = make()
        total = launches(w.on_foreground(HOME, 0)) + launches(w.on_foreground(HOME, 0.1)) \
            + launches(w.on_foreground(HOME, 0.2))
        self.assertEqual(len(total), 1)

    def test_vhome_in_front_before_response(self):
        w = make()
        (a,) = launches(w.on_foreground(HOME, 0))
        w.on_foreground(VH, 0.5)
        self.assertIsNotNone(w.pending)  # still needs the launch response
        w.on_launch_result(a.token, True, 0.8)
        self.assertIsNone(w.pending)
        self.assertEqual(w.stats["ok"], 1)

    def test_unknown_foreground_is_never_home(self):
        w = make()
        for app in ("", None, "   ", "some.other.app", 42):
            self.assertFalse(launches(w.on_foreground(app, 0)))
        self.assertEqual(w.stats["redirects"], 0)

    def test_empty_event_does_not_make_a_new_transition(self):
        w = make()
        n = len(launches(w.on_foreground(HOME, 0)))
        n += len(launches(w.on_foreground("", 0.1)))
        n += len(launches(w.on_foreground(HOME, 0.2)))
        self.assertEqual(n, 1)

    def test_launch_denied_is_a_failure_without_retry(self):
        w = make()
        (a,) = launches(w.on_foreground(HOME, 0))
        out = w.on_launch_result(a.token, False, 0.3, "insufficient permissions")
        self.assertIsNone(w.pending)
        self.assertEqual(w.stats["failed"], 1)
        self.assertIn("insufficient permissions", w.stats["last_failure"])
        self.assertFalse(launches(out))
        self.assertFalse(launches(w.on_tick(30)))
        self.assertFalse(launches(w.on_foreground(HOME, 40)))  # same Home still showing: dedupe

    def test_launch_timeout_no_response(self):
        w = make()
        w.on_foreground(HOME, 0)
        self.assertEqual(w.next_deadline(), 10.0)
        self.assertEqual(w.on_tick(10.0), [])  # exactly at the limit is still fine
        out = w.on_tick(10.1)
        self.assertIsNone(w.pending)
        self.assertIn("no launch response", w.stats["last_failure"])
        self.assertTrue(out)

    def test_response_ok_but_vhome_never_appears(self):
        w = make()
        (a,) = launches(w.on_foreground(HOME, 0))
        w.on_launch_result(a.token, True, 0.5)
        w.on_tick(10.5)
        self.assertIn("did not come to the front", w.stats["last_failure"])

    def test_vhome_late_after_deadline_is_failure(self):
        w = make()
        (a,) = launches(w.on_foreground(HOME, 0))
        w.on_launch_result(a.token, True, 0.5)
        w.on_foreground(VH, 11)
        self.assertEqual(w.stats["failed"], 1)
        self.assertEqual(w.stats["ok"], 0)

    def test_missing_vhome_app(self):
        w = make()
        (a,) = launches(w.on_foreground(HOME, 0))
        w.on_launch_result(a.token, False, 0.2, "Application not found")
        self.assertEqual(w.stats["failed"], 1)

    def test_late_result_ignored(self):
        w = make()
        (a,) = launches(w.on_foreground(HOME, 0))
        w.on_tick(11)
        w.on_launch_result(a.token, True, 12)
        self.assertEqual(w.stats["ok"], 0)

    def test_breaker_three_failures_in_60s(self):
        w = make()
        pauses = []
        for i, t in enumerate((0, 10, 20)):
            (a,) = launches(w.on_foreground(HOME, t))
            pauses += [x for x in w.on_launch_result(a.token, False, t + 1, "nope") if x.kind == "pause"]
            w.on_foreground("x.other", t + 2)
        self.assertEqual(len(pauses), 1)
        self.assertTrue(w.paused)
        self.assertFalse(launches(w.on_foreground(HOME, 30)))

    def test_failures_spread_out_do_not_trip(self):
        w = make()
        for t in (0, 40, 80, 120):
            (a,) = launches(w.on_foreground(HOME, t))
            w.on_launch_result(a.token, False, t + 1, "nope")
            w.on_foreground("x.other", t + 2)
        self.assertFalse(w.paused)

    def test_breaker_more_than_five_redirects_in_120s(self):
        w = make()
        for i in range(5):
            redirect_ok(w, i * 10)
        out = w.on_foreground(HOME, 55)
        self.assertEqual(kinds(out).count("launch"), 0)
        self.assertIn("pause", kinds(out))
        self.assertTrue(w.paused)

    def test_redirects_spread_beyond_window_do_not_trip(self):
        w = make()
        for i in range(8):
            redirect_ok(w, i * 30)
        self.assertFalse(w.paused)
        self.assertEqual(w.stats["redirects"], 8)

    def test_resume_clears_breaker_and_needs_a_new_transition(self):
        w = make()
        for i in range(5):
            redirect_ok(w, i * 10)
        w.on_foreground(HOME, 55)  # trips
        w.resume()
        self.assertFalse(launches(w.on_foreground(HOME, 60)))  # Home never left: no new transition
        w.on_foreground("x.other", 61)
        self.assertEqual(len(launches(w.on_foreground(HOME, 62))), 1)

    def test_paused_observes_only(self):
        w = make()
        w.pause("test")
        self.assertFalse(launches(w.on_foreground(HOME, 0)))
        w.on_foreground("x.other", 1)
        self.assertFalse(launches(w.on_foreground(HOME, 2)))
        self.assertEqual(w.stats["redirects"], 0)
        w.resume()
        w.on_foreground("x.other", 3)
        self.assertEqual(len(launches(w.on_foreground(HOME, 4))), 1)

    def test_reconnect_reconciles_current_foreground(self):
        w = make()
        w.on_foreground("netflix", 0)
        w.on_connected(5)
        self.assertFalse(launches(w.on_foreground("netflix", 5)))  # other app: never interrupted
        w.on_connected(6)
        self.assertFalse(launches(w.on_foreground(VH, 6)))
        w.on_connected(7)
        self.assertEqual(len(launches(w.on_foreground(HOME, 7))), 1)  # TV is on Home: act

    def test_reconnect_drops_pending_launch_without_counting(self):
        w = make()
        w.on_foreground(HOME, 0)
        w.on_connected(1)
        self.assertIsNone(w.pending)
        self.assertEqual(w.stats["failed"], 0)

    def test_hdmi_input_is_never_interrupted(self):
        w = make()
        self.assertFalse(launches(w.on_foreground("com.webos.app.hdmi1", 0)))

    def _double_press(self, w):
        redirect_ok(w, 0)
        w.on_foreground("netflix", 1)
        return launches(w.on_foreground(HOME, 2))

    def test_double_home_off_redirects_twice(self):
        self.assertEqual(len(self._double_press(make())), 1)

    def test_double_home_on_skips_second(self):
        w = make(double_home_escape=True)
        self.assertEqual(self._double_press(w), [])
        self.assertEqual(w.stats["escapes"], 1)

    def test_double_home_on_slow_second_press_redirects(self):
        w = make(double_home_escape=True)
        redirect_ok(w, 0)
        w.on_foreground("netflix", 1)
        self.assertEqual(len(launches(w.on_foreground(HOME, 3.5))), 1)

    def test_double_home_on_duplicate_notification_is_not_a_second_press(self):
        w = make(double_home_escape=True)
        out = w.on_foreground(HOME, 0) + w.on_foreground(HOME, 0.5)
        self.assertEqual(len(launches(out)), 1)
        self.assertEqual(w.stats["escapes"], 0)

    def test_home_during_inflight_launch_does_not_double_launch(self):
        w = make()
        w.on_foreground(HOME, 0)
        w.on_foreground("x.other", 1)
        self.assertFalse(launches(w.on_foreground(HOME, 2)))


if __name__ == "__main__":
    unittest.main()
