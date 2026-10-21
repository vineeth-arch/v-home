"""Pure state machine: foreground events in, actions out. No I/O, no clock of its own.

Every input carries `now` (seconds, any monotonic origin). Outputs are Action tuples the runner
applies: launch (ask the TV to start V/HOME), log, pause (breaker tripped; runner writes the flag).
"""
from collections import deque, namedtuple

Action = namedtuple("Action", "kind text token app_id level", defaults=("", 0, "", "info"))

CONFIRM_S = 10.0       # launch response AND V/HOME in front within this
FAIL_WINDOW_S, FAIL_LIMIT = 60.0, 3
REDIRECT_WINDOW_S, REDIRECT_LIMIT = 120.0, 5
DOUBLE_HOME_S = 3.0


class ConfigError(ValueError):
    pass


def _log(text, level="info"):
    return Action("log", text=text, level=level)


class Watcher:
    def __init__(self, vhome_id, home_ids, double_home_escape=False):
        home_ids = tuple(i for i in (home_ids or ()) if isinstance(i, str) and i.strip())
        if not isinstance(vhome_id, str) or not vhome_id.strip():
            raise ConfigError("V/HOME app id is not set")
        if not home_ids:
            raise ConfigError("no LG Home app id configured; run `diag --observe 20`, press Home, "
                              "then `diag --save-home <id>`")
        if vhome_id in home_ids:
            raise ConfigError("the V/HOME app id must not be one of the LG Home ids")
        self.vhome_id, self.home_ids = vhome_id, home_ids
        self.double_home_escape = bool(double_home_escape)
        self.paused = False
        self.last_app = None
        self.pending = None
        self._token = 0
        self._redirects, self._failures, self._home_times = deque(), deque(), deque()
        self.stats = {"redirects": 0, "ok": 0, "failed": 0, "escapes": 0,
                      "last_latency_s": None, "last_failure": None}

    # ---- inputs -------------------------------------------------------------------------

    def on_connected(self, now):
        """New connection: forget the previous foreground so the first event is reconciled."""
        out = []
        if self.pending:
            self.pending = None
            out.append(_log("connection restarted while a launch was pending; not counted", "warning"))
        self.last_app = None
        return out

    def on_foreground(self, app_id, now):
        out = self._expire(now)
        app = app_id.strip() if isinstance(app_id, str) else ""
        if not app:
            return out + [_log("ignored foreground event without an app id", "debug")]
        if app == self.last_app:
            return out  # duplicate notification
        self.last_app = app
        out.append(_log(f"foreground: {app}"))
        if self.pending and app == self.vhome_id:
            self.pending["seen_at"] = now
            out += self._maybe_confirm(now)
        if app in self.home_ids:
            out += self._on_home(now)
        return out

    def on_launch_result(self, token, ok, now, error=""):
        out = self._expire(now)
        p = self.pending
        if not p or p["token"] != token:
            return out + [_log("late launch result ignored", "debug")]
        if not ok:
            return out + self._fail(now, f"launch rejected: {error or 'unknown error'}")
        p["ok"] = True
        return out + self._maybe_confirm(now)

    def on_tick(self, now):
        return self._expire(now)

    def next_deadline(self):
        return self.pending["sent_at"] + CONFIRM_S if self.pending else None

    def pause(self, reason="paused"):
        self.paused = True
        return [_log(f"paused: {reason}", "warning")]

    def resume(self):
        self.paused = False
        self.pending = None  # last_app kept: resume acts on the next real Home transition, not the screen already showing
        self._redirects.clear()
        self._failures.clear()
        self._home_times.clear()
        return [_log("resumed")]

    def snapshot(self):
        return {"paused": self.paused, "last_app": self.last_app, "pending": bool(self.pending),
                **self.stats}

    # ---- internals ----------------------------------------------------------------------

    def _on_home(self, now):
        while self._home_times and now - self._home_times[0] > DOUBLE_HOME_S:
            self._home_times.popleft()
        recent_home = bool(self._home_times)
        self._home_times.append(now)
        if self.paused:
            return [_log("LG Home seen while paused: observing only")]
        if self.double_home_escape and recent_home:
            self._home_times.clear()
            self.stats["escapes"] += 1
            return [_log("Home pressed twice: staying on LG Home")]
        if self.pending:
            return [_log("LG Home seen while a launch is in flight: not launching again")]
        while self._redirects and now - self._redirects[0] > REDIRECT_WINDOW_S:
            self._redirects.popleft()
        if len(self._redirects) >= REDIRECT_LIMIT:
            self.paused = True
            return [_log(f"more than {REDIRECT_LIMIT} redirects in {int(REDIRECT_WINDOW_S)} s; "
                         "pausing (is V/HOME crashing?)", "error"),
                    Action("pause", text="redirect loop breaker")]
        self._token += 1
        self._redirects.append(now)
        self.stats["redirects"] += 1
        self.pending = {"token": self._token, "sent_at": now, "ok": False, "seen_at": None}
        return [_log("LG Home -> V/HOME"),
                Action("launch", token=self._token, app_id=self.vhome_id)]

    def _maybe_confirm(self, now):
        p = self.pending
        if not (p and p["ok"] and p["seen_at"] is not None):
            return []
        self.pending = None
        self.stats["ok"] += 1
        self.stats["last_latency_s"] = round(p["seen_at"] - p["sent_at"], 3)
        return [_log(f"redirect ok in {self.stats['last_latency_s']} s")]

    def _expire(self, now):
        p = self.pending
        if p and now - p["sent_at"] > CONFIRM_S:
            if not p["ok"]:
                why = "no launch response from the TV"
            else:
                why = "V/HOME did not come to the front"
            return self._fail(now, f"{why} within {int(CONFIRM_S)} s")
        return []

    def _fail(self, now, reason):
        self.pending = None
        # last_app stays: repeated notifications of the same Home are not a new transition (brief: do not loop)
        self.stats["failed"] += 1
        self.stats["last_failure"] = reason
        self._failures.append(now)
        while self._failures and now - self._failures[0] > FAIL_WINDOW_S:
            self._failures.popleft()
        out = [_log(f"redirect failed: {reason}", "warning")]
        if len(self._failures) >= FAIL_LIMIT:
            self.paused = True
            out += [_log(f"{FAIL_LIMIT} failed redirects in {int(FAIL_WINDOW_S)} s; pausing", "error"),
                    Action("pause", text="failed redirect breaker")]
        return out
